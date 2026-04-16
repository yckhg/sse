"""US-006: 문의(US-005 mail.mail) → CRM 영업건(crm.lead) 22건 생성.

- type='opportunity', stage_id=1 (New), user_id=2 (admin), team_id=1 (Sales).
- expected_revenue = qty × product.list_price (US-007 견적 amount_total 와 정합).
- 마커: <!-- ralph-demo-flow id=greenpr:lead:<partner_id>:<planned_date> -->
- create_date 는 XML-RPC 로 입력 불가 → create 직후 SQL UPDATE 로 backfill
  (방금 만든 id 화이트리스트만, 기존 레코드 절대 안 건드림).

실행:
    # 호스트 (게이트웨이 경유, KST/UTC 환경변수 고정 권장)
    ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/create_leads.py
    # 컨테이너 내부
    docker cp customers/greenpr/scripts/create_leads.py ycerp-web-greenpr:/tmp/
    docker exec ycerp-web-greenpr python3 /tmp/create_leads.py

인자:
    --dry-run               생성하지 않고 계획만 출력
    --limit N               앞 N 건만 처리 (테스트용)
    --skip-backfill         create_date SQL UPDATE 생략 (디버깅용)
    --db-container NAME     기본 ycerp-db-greenpr
    --partners-json P       기본: 스크립트 옆 ../docs/target-partners.json
    --products-json P       기본: 스크립트 옆 ../docs/products.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odoo_client import OdooClient  # noqa: E402
from send_inquiries import (  # noqa: E402  US-005 와 동일 plan 재사용
    DELIVERY_OFFSETS_DAYS,
    FALLBACK_FROM,
    MARKER_PREFIX,
    TENANT_KEY,
    container_name_arg,
    find_docs_path,
    load_partners,
    load_products,
    plan_flows,
)


LEAD_MARKER_NS = "lead"  # ralph-demo-flow id=greenpr:lead:<partner>:<date>
INQUIRY_MARKER_NS = ""   # US-005 marker has no extra namespace
DEFAULT_STAGE_ID = 1     # crm.stage "New"
DEFAULT_USER_ID = 2      # admin / green PR
DEFAULT_TEAM_ID = 1      # Sales
DEFAULT_DB_CONTAINER = "ycerp-db-greenpr"


def lead_marker(partner_id: int, planned_date: str) -> str:
    return f"{TENANT_KEY}:{LEAD_MARKER_NS}:{partner_id}:{planned_date}"


def inquiry_marker_needle(partner_id: int, planned_date: str) -> str:
    # 접미 ` -->` 를 포함해 HTML 주석 종단을 앵커 — `:1:...` 가 `:10:...` 에 섞이지 않는다.
    return f"{MARKER_PREFIX}{TENANT_KEY}:{partner_id}:{planned_date} -->"


def lead_marker_needle(partner_id: int, planned_date: str) -> str:
    return f"{MARKER_PREFIX}{lead_marker(partner_id, planned_date)} -->"


def fetch_product_prices(cli: OdooClient, product_ids: list[int]) -> dict[int, dict]:
    if not product_ids:
        return {}
    rows = cli.read("product.product", product_ids, ["id", "name", "list_price", "uom_id"])
    return {r["id"]: r for r in rows}


def fetch_partner_info(cli: OdooClient, partner_ids: list[int]) -> dict[int, dict]:
    rows = cli.read(
        "res.partner", partner_ids, ["id", "name", "email", "phone", "is_company"]
    )
    return {r["id"]: r for r in rows}


def find_inquiry_mail_id(cli: OdooClient, partner_id: int, planned_date: str) -> int | None:
    needle = inquiry_marker_needle(partner_id, planned_date)
    found = cli.search("mail.mail", [["body_html", "like", needle]], limit=1)
    return found[0] if found else None


def build_description(flow: dict, mail_id: int | None) -> str:
    marker = lead_marker(flow["partner_id"], flow["planned_date"])
    delivery_dt = dt.date.fromisoformat(flow["planned_date"]) + dt.timedelta(
        days=DELIVERY_OFFSETS_DAYS[flow["tone_idx"] % len(DELIVERY_OFFSETS_DAYS)]
    )
    inquiry_link = (
        f"문의 mail.mail id=<b>{mail_id}</b>" if mail_id is not None else "문의 mail.mail 미연결"
    )
    body_text = (
        f"파트너 \"{flow['partner_name']}\"(id={flow['partner_id']}) 문의 접수 - "
        f"{flow['product_name']} (id={flow['product_id']}) 약 {flow['qty']}개. "
        f"희망 납기 {delivery_dt.isoformat()}. {inquiry_link}."
    )
    return (
        f"<p>{html.escape(body_text)}</p>"
        f"<hr/>"
        f"<p style='color:#888;font-size:12px;'>접수일: {flow['planned_date']} / "
        f"product_id={flow['product_id']} / qty={flow['qty']} / "
        f"expected_revenue={flow['expected_revenue']:,}</p>"
        f"<!-- {MARKER_PREFIX}{lead_marker(flow['partner_id'], flow['planned_date'])} -->"
    )


def build_name(flow: dict) -> str:
    return f"[문의] {flow['product_name']} 견적 - {flow['partner_name']}"


def build_lead_vals(flow: dict, partner: dict, mail_id: int | None) -> dict:
    planned = flow["planned_date"]
    date_open = f"{planned} 09:00:00"
    deadline = (dt.date.fromisoformat(planned) + dt.timedelta(days=14)).isoformat()
    return {
        "name": build_name(flow),
        "type": "opportunity",
        "partner_id": flow["partner_id"],
        "partner_name": partner.get("name") or flow["partner_name"],
        "email_from": (partner.get("email") or FALLBACK_FROM),
        "phone": partner.get("phone") or False,
        "stage_id": DEFAULT_STAGE_ID,
        "user_id": DEFAULT_USER_ID,
        "team_id": DEFAULT_TEAM_ID,
        "expected_revenue": flow["expected_revenue"],
        "date_open": date_open,
        "date_deadline": deadline,
        "description": build_description(flow, mail_id),
    }


_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def backfill_create_date(
    db_container: str, lead_to_dt: dict[int, str]
) -> None:
    """방금 만든 lead id 화이트리스트만 SQL UPDATE 로 create_date 보정.

    lead_to_dt: {lead_id: 'YYYY-MM-DD HH:MM:SS' (UTC)}

    안전성: SQL literal 문자열 보간 대신 COPY FROM STDIN + TEMP 테이블로
    데이터를 SQL과 분리한다. id/ts 값은 엄격히 검증한다.
    """
    if not lead_to_dt:
        return
    data_lines: list[str] = []
    for lid, ts in lead_to_dt.items():
        if not isinstance(lid, int):
            raise ValueError(f"lead id must be int, got {lid!r}")
        if not _TS_RE.match(ts):
            raise ValueError(f"invalid timestamp literal: {ts!r}")
        data_lines.append(f"{lid}\t{ts}")
    sql_script = (
        "BEGIN;\n"
        "CREATE TEMP TABLE _backfill_ts (id bigint PRIMARY KEY, ts timestamp NOT NULL) ON COMMIT DROP;\n"
        "COPY _backfill_ts (id, ts) FROM STDIN;\n"
        + "\n".join(data_lines) + "\n"
        "\\.\n"
        "UPDATE crm_lead l SET create_date = b.ts, write_date = b.ts, date_open = b.ts\n"
        "FROM _backfill_ts b WHERE l.id = b.id;\n"
        "COMMIT;\n"
    )
    cmd = [
        "docker", "exec", "-i", db_container,
        "psql", "-U", "odoo", "-d", "odoo", "-v", "ON_ERROR_STOP=1",
    ]
    subprocess.run(cmd, input=sql_script, check=True, text=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--skip-backfill", action="store_true")
    ap.add_argument(
        "--db-container", default=DEFAULT_DB_CONTAINER, type=container_name_arg,
    )
    ap.add_argument("--partners-json", type=Path, default=None)
    ap.add_argument("--products-json", type=Path, default=None)
    ap.add_argument(
        "--log-path", type=Path, default=None,
        help="lead-log.md 경로. 기본: docs/lead-log.md",
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

    # 1) product.list_price 캐시 → expected_revenue 채우기
    uniq_product_ids = sorted({f["product_id"] for f in flows})
    prod_map = fetch_product_prices(cli, uniq_product_ids)
    for f in flows:
        prod = prod_map.get(f["product_id"], {})
        list_price = float(prod.get("list_price") or 0.0)
        f["list_price"] = list_price
        f["expected_revenue"] = round(list_price * f["qty"], 2)

    # 2) 파트너 정보 (이름/이메일/전화)
    uniq_partner_ids = sorted({f["partner_id"] for f in flows})
    partner_map = fetch_partner_info(cli, uniq_partner_ids)

    print(
        f"[plan] partners={len(partners)} products={len(products)} flows={len(flows)} "
        f"uniq_products_priced={len(prod_map)}"
    )

    if args.dry_run:
        for f in flows:
            print(
                f"  {f['planned_date']}  partner_id={f['partner_id']:>4}  "
                f"product_id={f['product_id']:>4}  qty={f['qty']:>3}  "
                f"list_price={f['list_price']:>10.2f}  exp_rev={f['expected_revenue']:>12.2f}  "
                f"name={f['partner_name']}"
            )
        return 0

    created: dict[int, str] = {}  # lead_id -> backfill ts (UTC)
    skipped = 0
    log_rows = []
    for f in flows:
        partner = partner_map.get(f["partner_id"], {})
        marker = lead_marker(f["partner_id"], f["planned_date"])
        existing = cli.search(
            "crm.lead", [["description", "like", lead_marker_needle(f["partner_id"], f["planned_date"])]],
            limit=1,
        )
        if existing:
            print(f"  [skip] marker={marker} -> crm.lead {existing[0]}")
            log_rows.append({**f, "lead_id": existing[0], "status": "skipped", "marker": marker})
            skipped += 1
            continue

        mail_id = find_inquiry_mail_id(cli, f["partner_id"], f["planned_date"])
        vals = build_lead_vals(f, partner, mail_id)
        # mail.create_uid context 트래킹 메일 생성 줄임
        ctx = {"tracking_disable": True, "mail_create_nolog": True, "mail_notrack": True}
        lead_id = cli.execute_kw("crm.lead", "create", [[vals]], {"context": ctx})
        if isinstance(lead_id, list):
            lead_id = lead_id[0]
        # 09:00 KST → 00:00 UTC. 데모용으로 단순히 09:00:00 을 UTC 그대로 저장 (KST 표시 18:00).
        backfill_ts = f"{f['planned_date']} 09:00:00"
        created[lead_id] = backfill_ts
        print(
            f"  [ok]   crm.lead id={lead_id:>4}  partner_id={f['partner_id']:>4}  "
            f"date_open={backfill_ts}  exp_rev={f['expected_revenue']:>12.2f}  mail.mail={mail_id}"
        )
        log_rows.append({
            **f, "lead_id": lead_id, "status": "created", "marker": marker, "mail_mail_id": mail_id,
        })

    print()
    print(f"[summary] created={len(created)} skipped={skipped} total={len(flows)}")

    if created and not args.skip_backfill:
        try:
            backfill_create_date(args.db_container, created)
            print(f"[backfill] create_date/date_open updated for {len(created)} leads via SQL")
        except subprocess.CalledProcessError as e:
            print(f"[backfill] WARN: SQL UPDATE failed: {e}", file=sys.stderr)

    log_path = args.log_path or (Path(__file__).resolve().parent.parent / "docs" / "lead-log.md")
    try:
        append_log(log_path, log_rows, len(created), skipped)
        print(f"[log] appended to {log_path}")
    except Exception as e:
        print(f"[log] WARN: {e}", file=sys.stderr)

    return 0


def append_log(path: Path, rows: list[dict], created: int, skipped: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header_needed = not path.exists()
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    if header_needed:
        lines.append("# Lead Log (US-006)\n")
        lines.append("US-006 `create_leads.py` 실행 이력. 각 섹션은 1회 실행.\n")
    lines.append(f"\n## {now} — created={created} skipped={skipped} total={len(rows)}\n")
    lines.append(
        "| crm.lead id | partner_id | partner | date_open | product_id | qty | exp_rev | mail.mail | status | marker |\n"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|\n")
    for r in rows:
        lines.append(
            "| {lid} | {pid} | {pname} | {d} | {prod} | {qty} | {er} | {mid} | {st} | {mk} |\n".format(
                lid=r.get("lead_id", "-"),
                pid=r["partner_id"],
                pname=r["partner_name"],
                d=r["planned_date"],
                prod=r["product_id"],
                qty=r["qty"],
                er=f"{r.get('expected_revenue', 0):,.0f}",
                mid=r.get("mail_mail_id", "-"),
                st=r["status"],
                mk=r["marker"],
            )
        )
    with path.open("a", encoding="utf-8") as f:
        f.writelines(lines)


if __name__ == "__main__":
    sys.exit(main())
