"""US-007: crm.lead(US-006) → sale.order(+line) 22건 생성 + action_confirm.

각 flow 당:
  1. crm.lead 찾기 (US-006 marker search, lead.description)
  2. sale.order create (order_line 1개 포함 — 같은 product_id/qty/list_price 사용)
  3. action_confirm → state='sale'
  4. amount_total 읽어 crm.lead.expected_revenue 로 덮어쓰기 (정합성)

Idempotent marker: <!-- ralph-demo-flow id=greenpr:so:<partner_id>:<planned_date> -->
저장 필드: sale.order.note

실행:
    # 호스트 (게이트웨이 경유)
    ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/create_sale_orders.py
    # 컨테이너 내부
    docker cp customers/greenpr/scripts/ ycerp-web-greenpr:/tmp/
    docker exec ycerp-web-greenpr python3 /tmp/scripts/create_sale_orders.py

인자:
    --dry-run              계획만 출력
    --limit N              앞 N 건만 처리
    --skip-confirm         action_confirm 생략
    --skip-lead-write      lead.expected_revenue 재-write 생략
    --partners-json P      기본: ../docs/target-partners.json
    --products-json P      기본: ../docs/products.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odoo_client import OdooClient  # noqa: E402
from send_inquiries import (  # noqa: E402  동일 plan 재사용 → mail.mail ↔ lead ↔ SO 1:1
    MARKER_PREFIX,
    TENANT_KEY,
    container_name_arg,
    find_docs_path,
    load_partners,
    load_products,
    plan_flows,
)


SO_MARKER_NS = "so"           # ralph-demo-flow id=greenpr:so:<partner>:<date>
LEAD_MARKER_NS = "lead"       # US-006
INQUIRY_MARKER_NS = ""        # US-005 (no extra namespace)
DEFAULT_USER_ID = 2
DEFAULT_TEAM_ID = 1
DEFAULT_COMPANY_ID = 1
DEFAULT_WAREHOUSE_ID = 1
DEFAULT_PRICELIST_ID = 1
DATE_ORDER_OFFSETS_DAYS = [0, 1, 2]  # flow_idx 로 결정적 선택
DEFAULT_DB_CONTAINER = "ycerp-db-greenpr"


def so_marker(partner_id: int, planned_date: str) -> str:
    return f"{TENANT_KEY}:{SO_MARKER_NS}:{partner_id}:{planned_date}"


def so_marker_needle(partner_id: int, planned_date: str) -> str:
    # 접미 ` -->` 를 포함해 HTML 주석 종단을 앵커 — `:1:...` 가 `:10:...` 에 섞이지 않는다.
    return f"{MARKER_PREFIX}{so_marker(partner_id, planned_date)} -->"


def lead_marker_needle(partner_id: int, planned_date: str) -> str:
    return f"{MARKER_PREFIX}{TENANT_KEY}:{LEAD_MARKER_NS}:{partner_id}:{planned_date} -->"


def inquiry_marker_needle(partner_id: int, planned_date: str) -> str:
    return f"{MARKER_PREFIX}{TENANT_KEY}:{partner_id}:{planned_date} -->"


def fetch_product_prices(cli: OdooClient, product_ids: list[int]) -> dict[int, dict]:
    if not product_ids:
        return {}
    rows = cli.read("product.product", product_ids, ["id", "name", "list_price", "uom_id"])
    return {r["id"]: r for r in rows}


def find_lead_id(cli: OdooClient, partner_id: int, planned_date: str) -> int | None:
    needle = lead_marker_needle(partner_id, planned_date)
    found = cli.search("crm.lead", [["description", "like", needle]], limit=1)
    return found[0] if found else None


def find_mail_id(cli: OdooClient, partner_id: int, planned_date: str) -> int | None:
    needle = inquiry_marker_needle(partner_id, planned_date)
    found = cli.search("mail.mail", [["body_html", "like", needle]], limit=1)
    return found[0] if found else None


def build_note(flow: dict, lead_id: int | None, mail_id: int | None) -> str:
    marker = so_marker(flow["partner_id"], flow["planned_date"])
    body = (
        f"견적서 ({flow['partner_name']} / {flow['product_name']} × {flow['qty']}). "
        f"lead_id={lead_id} mail.mail={mail_id} planned_date={flow['planned_date']}."
    )
    return (
        f"<p>{html.escape(body)}</p>"
        f"<!-- {MARKER_PREFIX}{marker} -->"
    )


def build_date_order(planned_date: str, flow_idx: int) -> str:
    """planned_date 에서 0/1/2 일 오프셋 후 09:30:00 (UTC) 로 확정적 분배."""
    offset = DATE_ORDER_OFFSETS_DAYS[flow_idx % len(DATE_ORDER_OFFSETS_DAYS)]
    d = dt.date.fromisoformat(planned_date) + dt.timedelta(days=offset)
    return f"{d.isoformat()} 09:30:00"


_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def backfill_date_order(db_container: str, so_to_ts: dict[int, str]) -> None:
    """방금 create+confirm 한 sale.order 만 대상으로 `date_order` / `create_date` SQL UPDATE.

    action_confirm 이 date_order 를 now() 로 덮기 때문에 backfill 필요 (PRD AC "date_order 는 lead
    create_date 와 같거나 1~2일 후").

    so_to_ts: {so_id: 'YYYY-MM-DD HH:MM:SS' UTC}

    안전성: SQL literal 문자열 보간 대신 COPY FROM STDIN + TEMP 테이블로
    데이터를 SQL과 분리한다. id/ts 값은 엄격히 검증한다.
    """
    if not so_to_ts:
        return
    data_lines: list[str] = []
    for sid, ts in so_to_ts.items():
        if not isinstance(sid, int):
            raise ValueError(f"sale.order id must be int, got {sid!r}")
        if not _TS_RE.match(ts):
            raise ValueError(f"invalid timestamp literal: {ts!r}")
        data_lines.append(f"{sid}\t{ts}")
    sql_script = (
        "BEGIN;\n"
        "CREATE TEMP TABLE _backfill_ts (id bigint PRIMARY KEY, ts timestamp NOT NULL) ON COMMIT DROP;\n"
        "COPY _backfill_ts (id, ts) FROM STDIN;\n"
        + "\n".join(data_lines) + "\n"
        "\\.\n"
        "UPDATE sale_order s SET date_order = b.ts, create_date = b.ts, write_date = b.ts\n"
        "FROM _backfill_ts b WHERE s.id = b.id;\n"
        "COMMIT;\n"
    )
    cmd = [
        "docker", "exec", "-i", db_container,
        "psql", "-U", "odoo", "-d", "odoo", "-v", "ON_ERROR_STOP=1",
    ]
    subprocess.run(cmd, input=sql_script, check=True, text=True)


def build_so_vals(
    flow: dict, lead_id: int | None, mail_id: int | None, flow_idx: int, list_price: float
) -> dict:
    line_vals = {
        "product_id": flow["product_id"],
        "product_uom_qty": flow["qty"],
        "price_unit": list_price,
        "name": flow["product_name"],
    }
    return {
        "partner_id": flow["partner_id"],
        "opportunity_id": lead_id or False,
        "date_order": build_date_order(flow["planned_date"], flow_idx),
        "user_id": DEFAULT_USER_ID,
        "team_id": DEFAULT_TEAM_ID,
        "company_id": DEFAULT_COMPANY_ID,
        "warehouse_id": DEFAULT_WAREHOUSE_ID,
        "pricelist_id": DEFAULT_PRICELIST_ID,
        "origin": f"CRM Lead #{lead_id}" if lead_id else "",
        "client_order_ref": f"문의 #{mail_id}" if mail_id else "",
        "note": build_note(flow, lead_id, mail_id),
        "order_line": [(0, 0, line_vals)],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--skip-confirm", action="store_true")
    ap.add_argument("--skip-lead-write", action="store_true")
    ap.add_argument("--skip-backfill", action="store_true",
                    help="action_confirm 직후 date_order SQL UPDATE 생략 (디버깅용)")
    ap.add_argument(
        "--db-container", default=DEFAULT_DB_CONTAINER, type=container_name_arg,
    )
    ap.add_argument("--partners-json", type=Path, default=None)
    ap.add_argument("--products-json", type=Path, default=None)
    ap.add_argument(
        "--log-path", type=Path, default=None,
        help="so-log.md 경로. 기본: docs/so-log.md",
    )
    args = ap.parse_args()

    partners_path = args.partners_json or find_docs_path("target-partners.json")
    products_path = args.products_json or find_docs_path("products.json")
    partners = load_partners(partners_path)
    products = load_products(products_path)
    flows = plan_flows(partners, products)
    if args.limit is not None:
        flows = flows[: args.limit]

    cli = OdooClient()
    cli.authenticate()
    print(f"[auth] uid={cli.uid} version={cli.version().get('server_version')}")

    uniq_product_ids = sorted({f["product_id"] for f in flows})
    prod_map = fetch_product_prices(cli, uniq_product_ids)
    for f in flows:
        prod = prod_map.get(f["product_id"], {})
        f["list_price"] = float(prod.get("list_price") or 0.0)

    print(
        f"[plan] partners={len(partners)} products={len(products)} flows={len(flows)} "
        f"uniq_products_priced={len(prod_map)}"
    )

    if args.dry_run:
        for idx, f in enumerate(flows):
            lid = find_lead_id(cli, f["partner_id"], f["planned_date"])
            mid = find_mail_id(cli, f["partner_id"], f["planned_date"])
            print(
                f"  {f['planned_date']}  partner_id={f['partner_id']:>4}  "
                f"product_id={f['product_id']:>4}  qty={f['qty']:>3}  "
                f"list_price={f['list_price']:>10.2f}  lead={lid}  mail={mid}  "
                f"date_order={build_date_order(f['planned_date'], idx)}  name={f['partner_name']}"
            )
        return 0

    ctx = {"tracking_disable": True, "mail_create_nolog": True, "mail_notrack": True}
    created: list[dict] = []
    created_backfill: dict[int, str] = {}  # so_id -> planned date_order (UTC)
    confirmed = 0
    lead_updated = 0
    skipped = 0
    log_rows = []
    for flow_idx, f in enumerate(flows):
        marker = so_marker(f["partner_id"], f["planned_date"])
        existing = cli.search(
            "sale.order", [["note", "like", so_marker_needle(f["partner_id"], f["planned_date"])]],
            limit=1,
        )
        if existing:
            so_row = cli.read("sale.order", existing, ["id", "name", "state", "amount_total", "opportunity_id"])[0]
            print(f"  [skip] marker={marker} -> sale.order {so_row['id']} ({so_row['name']}, state={so_row['state']})")
            log_rows.append({**f, "so_id": so_row["id"], "so_name": so_row["name"], "state": so_row["state"],
                             "amount_total": so_row["amount_total"], "status": "skipped", "marker": marker})
            skipped += 1
            continue

        lead_id = find_lead_id(cli, f["partner_id"], f["planned_date"])
        mail_id = find_mail_id(cli, f["partner_id"], f["planned_date"])
        vals = build_so_vals(f, lead_id, mail_id, flow_idx, f["list_price"])
        so_id = cli.execute_kw("sale.order", "create", [[vals]], {"context": ctx})
        if isinstance(so_id, list):
            so_id = so_id[0]

        planned_date_order = build_date_order(f["planned_date"], flow_idx)
        if not args.skip_confirm:
            cli.call_method("sale.order", "action_confirm", [so_id])
        # action_confirm resets date_order to now(); remember the planned value for SQL backfill.
        created_backfill[so_id] = planned_date_order
        so_row = cli.read("sale.order", [so_id], ["id", "name", "state", "amount_total", "amount_untaxed", "date_order"])[0]

        if lead_id and not args.skip_lead_write:
            cli.write("crm.lead", [lead_id], {"expected_revenue": so_row["amount_total"]})
            lead_updated += 1

        created.append({**so_row, "lead_id": lead_id, "mail_id": mail_id})
        if so_row["state"] == "sale":
            confirmed += 1
        print(
            f"  [ok]   sale.order id={so_row['id']:>4} ({so_row['name']})  "
            f"partner_id={f['partner_id']:>4}  date_order={so_row['date_order']}  "
            f"state={so_row['state']:>6}  amount_total={so_row['amount_total']:>12.2f}  "
            f"lead={lead_id}  mail={mail_id}"
        )
        log_rows.append({
            **f, "so_id": so_row["id"], "so_name": so_row["name"], "state": so_row["state"],
            "amount_total": so_row["amount_total"], "amount_untaxed": so_row["amount_untaxed"],
            "lead_id": lead_id, "mail_id": mail_id, "status": "created", "marker": marker,
        })

    print()
    print(
        f"[summary] created={len(created)} confirmed={confirmed} "
        f"lead_expected_revenue_updated={lead_updated} skipped={skipped} total={len(flows)}"
    )

    if created_backfill and not args.skip_backfill:
        try:
            backfill_date_order(args.db_container, created_backfill)
            print(f"[backfill] date_order/create_date updated for {len(created_backfill)} sale.orders via SQL")
        except subprocess.CalledProcessError as e:
            print(f"[backfill] WARN: SQL UPDATE failed: {e}", file=sys.stderr)

    log_path = args.log_path or (Path(__file__).resolve().parent.parent / "docs" / "so-log.md")
    try:
        append_log(log_path, log_rows, len(created), skipped, confirmed, lead_updated)
        print(f"[log] appended to {log_path}")
    except Exception as e:
        print(f"[log] WARN: {e}", file=sys.stderr)

    return 0


def append_log(
    path: Path, rows: list[dict], created: int, skipped: int, confirmed: int, lead_updated: int
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header_needed = not path.exists()
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    if header_needed:
        lines.append("# Sale Order Log (US-007)\n")
        lines.append("US-007 `create_sale_orders.py` 실행 이력. 각 섹션은 1회 실행.\n")
    lines.append(
        f"\n## {now} — created={created} confirmed={confirmed} "
        f"lead_updated={lead_updated} skipped={skipped} total={len(rows)}\n"
    )
    lines.append(
        "| sale.order id | name | partner_id | partner | date | state | amount_total | lead | mail | status |\n"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|\n")
    for r in rows:
        lines.append(
            "| {sid} | {sname} | {pid} | {pname} | {d} | {st} | {at} | {lid} | {mid} | {stat} |\n".format(
                sid=r.get("so_id", "-"),
                sname=r.get("so_name", "-"),
                pid=r["partner_id"],
                pname=r["partner_name"],
                d=r["planned_date"],
                st=r.get("state", "-"),
                at=f"{r.get('amount_total', 0):,.0f}",
                lid=r.get("lead_id", "-"),
                mid=r.get("mail_id", "-"),
                stat=r["status"],
            )
        )
    with path.open("a", encoding="utf-8") as f:
        f.writelines(lines)


if __name__ == "__main__":
    sys.exit(main())
