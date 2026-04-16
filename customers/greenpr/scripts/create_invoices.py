"""US-008: sale.order(US-007) → account.move (out_invoice) 22건 생성 + action_post.

각 flow 당:
  1. sale.order 찾기 (US-007 marker via sale.order.note → so_id)
  2. SO 가 이미 invoice 보유시 backfill marker 만 처리하고 skip
  3. sale.advance.payment.inv 위저드로 _create_invoices() 트리거
     (위저드 return value 의 None 마샬 에러는 swallow — side effect 만 사용)
  4. SO.invoice_ids diff 로 새 invoice id 회수
  5. invoice_date / date / ref / narration(marker) write
  6. account.move.action_post → state='posted'
  7. 금액 정합 검증 (so.amount_total == invoice.amount_total)

Idempotent marker: <!-- ralph-demo-flow id=greenpr:inv:<partner_id>:<planned_date> -->
저장 필드: account.move.narration

실행:
    # 호스트 (게이트웨이 경유)
    ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/create_invoices.py
    # 컨테이너 내부
    docker cp customers/greenpr/scripts/ ycerp-web-greenpr:/tmp/
    docker exec ycerp-web-greenpr python3 /tmp/scripts/create_invoices.py

인자:
    --dry-run           계획만 출력
    --limit N           앞 N 건만 처리
    --skip-post         action_post 생략 (디버그)
    --skip-narration    narration marker write 생략 (idempotency 깨짐)
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import sys
import xmlrpc.client
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odoo_client import OdooClient  # noqa: E402
from send_inquiries import (  # noqa: E402
    MARKER_PREFIX,
    TENANT_KEY,
    find_docs_path,
    load_partners,
    load_products,
    plan_flows,
)
from create_sale_orders import so_marker_needle  # noqa: E402

INV_MARKER_NS = "inv"
INVOICE_DATE_OFFSETS_DAYS = [1, 2, 3]  # flow_idx % 3 → +1/+2/+3 일


def inv_marker(partner_id: int, planned_date: str) -> str:
    return f"{TENANT_KEY}:{INV_MARKER_NS}:{partner_id}:{planned_date}"


def inv_marker_needle(partner_id: int, planned_date: str) -> str:
    # 접미 ` -->` 를 포함해 HTML 주석 종단을 앵커 — `:1:...` 가 `:10:...` 에 섞이지 않는다.
    return f"{MARKER_PREFIX}{inv_marker(partner_id, planned_date)} -->"


def find_so_id(cli: OdooClient, partner_id: int, planned_date: str) -> int | None:
    found = cli.search(
        "sale.order", [["note", "like", so_marker_needle(partner_id, planned_date)]],
        limit=1,
    )
    return found[0] if found else None


def find_invoice_by_marker(cli: OdooClient, partner_id: int, planned_date: str) -> int | None:
    found = cli.search(
        "account.move", [["narration", "like", inv_marker_needle(partner_id, planned_date)]],
        limit=1,
    )
    return found[0] if found else None


def build_invoice_date(planned_date: str, flow_idx: int) -> str:
    """SO date_order 와 별개로 planned_date(=lead 기준일) + 1/2/3 일."""
    offset = INVOICE_DATE_OFFSETS_DAYS[flow_idx % len(INVOICE_DATE_OFFSETS_DAYS)]
    d = dt.date.fromisoformat(planned_date) + dt.timedelta(days=offset)
    return d.isoformat()


def build_narration(flow: dict, so_id: int, lead_id: int | None) -> str:
    marker = inv_marker(flow["partner_id"], flow["planned_date"])
    body = (
        f"청구서 (SO #{so_id} / {flow['partner_name']} / "
        f"{flow['product_name']} × {flow['qty']}). "
        f"lead_id={lead_id} planned_date={flow['planned_date']}."
    )
    return (
        f"<p>{html.escape(body)}</p>"
        f"<!-- {MARKER_PREFIX}{marker} -->"
    )


def _is_marshal_none_fault(exc: Exception) -> bool:
    """위저드 create_invoices return action dict 안의 None 때문에 server 가
    'cannot marshal None' Fault 1 을 던지는 케이스만 swallow."""
    if not isinstance(exc, xmlrpc.client.Fault):
        return False
    return "cannot marshal None" in (exc.faultString or "")


def trigger_create_invoices(cli: OdooClient, so_id: int) -> None:
    """sale.advance.payment.inv 위저드 경유로 _create_invoices() 호출.

    위저드 return value 의 None 마샬 에러는 swallow (side effect 는 정상 수행됨)."""
    ctx = {"active_model": "sale.order", "active_ids": [so_id], "active_id": so_id}
    wiz_id = cli.execute_kw(
        "sale.advance.payment.inv", "create",
        [{
            "advance_payment_method": "delivered",
            "sale_order_ids": [(6, 0, [so_id])],
        }],
        {"context": ctx},
    )
    if isinstance(wiz_id, list):
        wiz_id = wiz_id[0]
    try:
        cli.execute_kw(
            "sale.advance.payment.inv", "create_invoices",
            [[wiz_id]],
            {"context": ctx},
        )
    except xmlrpc.client.Fault as e:
        if not _is_marshal_none_fault(e):
            raise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--skip-post", action="store_true")
    ap.add_argument("--skip-narration", action="store_true")
    ap.add_argument("--partners-json", type=Path, default=None)
    ap.add_argument("--products-json", type=Path, default=None)
    ap.add_argument(
        "--log-path", type=Path, default=None,
        help="invoice-log.md 경로. 기본: docs/invoice-log.md",
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
    print(f"[plan] partners={len(partners)} products={len(products)} flows={len(flows)}")

    if args.dry_run:
        for idx, f in enumerate(flows):
            sid = find_so_id(cli, f["partner_id"], f["planned_date"])
            inv_existing = find_invoice_by_marker(cli, f["partner_id"], f["planned_date"])
            inv_date = build_invoice_date(f["planned_date"], idx)
            print(
                f"  {f['planned_date']}  partner_id={f['partner_id']:>4}  "
                f"so={sid}  existing_inv={inv_existing}  invoice_date={inv_date}  "
                f"name={f['partner_name']}"
            )
        return 0

    created = 0
    posted = 0
    skipped = 0
    backfilled = 0
    log_rows: list[dict] = []

    for flow_idx, f in enumerate(flows):
        marker = inv_marker(f["partner_id"], f["planned_date"])
        # Step 1: locate SO from US-007 marker
        so_id = find_so_id(cli, f["partner_id"], f["planned_date"])
        if not so_id:
            print(f"  [skip] no SO for partner={f['partner_id']} date={f['planned_date']}")
            log_rows.append({**f, "status": "missing_so", "marker": marker})
            skipped += 1
            continue
        so = cli.read(
            "sale.order", [so_id],
            ["id", "name", "amount_total", "invoice_ids", "invoice_status",
             "partner_id", "partner_invoice_id", "date_order", "opportunity_id"],
        )[0]

        # Step 2: idempotency check (marker)
        existing_inv_id = find_invoice_by_marker(cli, f["partner_id"], f["planned_date"])
        if existing_inv_id:
            inv = cli.read("account.move", [existing_inv_id],
                           ["id", "name", "state", "amount_total", "invoice_date"])[0]
            print(
                f"  [skip] marker={marker} -> account.move {inv['id']} "
                f"({inv['name']}, state={inv['state']}, total={inv['amount_total']:,.0f})"
            )
            log_rows.append({
                **f, "so_id": so_id, "so_name": so["name"], "inv_id": inv["id"],
                "inv_name": inv["name"], "state": inv["state"],
                "amount_total": inv["amount_total"], "status": "skipped", "marker": marker,
            })
            skipped += 1
            continue

        # Step 2b: SO already invoiced (no marker yet) → backfill marker, no new create
        live_existing = []
        if so["invoice_ids"]:
            invs = cli.read("account.move", so["invoice_ids"],
                            ["id", "state", "narration", "amount_total", "name", "invoice_date"])
            live_existing = [i for i in invs if i["state"] != "cancel"]

        if live_existing:
            inv = live_existing[0]
            new_narration = build_narration(f, so_id, _opportunity_id(so))
            if not args.skip_narration:
                cli.write("account.move", [inv["id"]], {"narration": new_narration})
                backfilled += 1
            print(
                f"  [backfill] SO {so['name']} already invoiced → account.move {inv['id']} "
                f"({inv['name']}, state={inv['state']}, total={inv['amount_total']:,.0f})  marker added"
            )
            log_rows.append({
                **f, "so_id": so_id, "so_name": so["name"], "inv_id": inv["id"],
                "inv_name": inv["name"], "state": inv["state"],
                "amount_total": inv["amount_total"], "status": "backfilled", "marker": marker,
            })
            continue

        # Step 3: trigger _create_invoices via wizard
        before_ids = set(so["invoice_ids"])
        trigger_create_invoices(cli, so_id)
        so2 = cli.read("sale.order", [so_id], ["invoice_ids"])[0]
        new_ids = [i for i in so2["invoice_ids"] if i not in before_ids]
        if not new_ids:
            # 스테이지 규약 §4.1: silent continue 금지 — skipped 로 카운트해 [summary] 합계 정합.
            print(f"  [ERR] wizard ran but no new invoice for SO {so['name']}", file=sys.stderr)
            log_rows.append({**f, "so_id": so_id, "so_name": so["name"],
                             "status": "create_failed", "marker": marker})
            skipped += 1
            continue
        inv_id = new_ids[0]
        created += 1

        # Step 4: write invoice_date / date / ref / narration
        invoice_date_iso = build_invoice_date(f["planned_date"], flow_idx)
        write_vals: dict = {
            "invoice_date": invoice_date_iso,
            "date": invoice_date_iso,
            "ref": f"SO #{so_id}",
        }
        if not args.skip_narration:
            write_vals["narration"] = build_narration(f, so_id, _opportunity_id(so))
        cli.write("account.move", [inv_id], write_vals)

        # Step 5: action_post
        if not args.skip_post:
            cli.call_method("account.move", "action_post", [inv_id])
            posted += 1

        # Step 6: read back + amount verify
        inv = cli.read(
            "account.move", [inv_id],
            ["id", "name", "state", "amount_total", "amount_untaxed",
             "invoice_date", "date", "partner_id"],
        )[0]
        amount_match = abs(float(inv["amount_total"]) - float(so["amount_total"])) < 0.01
        flag = "OK" if amount_match else "MISMATCH"
        print(
            f"  [{flag:^7}] account.move id={inv['id']:>4} ({inv['name']})  "
            f"so={so['name']}  partner_id={f['partner_id']:>4}  "
            f"invoice_date={inv['invoice_date']}  state={inv['state']:>6}  "
            f"amount_total={inv['amount_total']:>12,.2f}  (so={so['amount_total']:>12,.2f})"
        )
        log_rows.append({
            **f, "so_id": so_id, "so_name": so["name"],
            "inv_id": inv["id"], "inv_name": inv["name"], "state": inv["state"],
            "amount_total": inv["amount_total"], "so_amount": so["amount_total"],
            "amount_match": amount_match, "invoice_date": inv["invoice_date"],
            "status": "created", "marker": marker,
        })

    print()
    print(
        f"[summary] created={created} posted={posted} backfilled={backfilled} "
        f"skipped={skipped} total={len(flows)}"
    )

    log_path = args.log_path or (Path(__file__).resolve().parent.parent / "docs" / "invoice-log.md")
    try:
        append_log(log_path, log_rows, created, posted, backfilled, skipped)
        print(f"[log] appended to {log_path}")
    except Exception as e:
        print(f"[log] WARN: {e}", file=sys.stderr)

    return 0


def _opportunity_id(so_row: dict):
    v = so_row.get("opportunity_id")
    if isinstance(v, list) and v:
        return v[0]
    return v or None


def append_log(
    path: Path, rows: list[dict],
    created: int, posted: int, backfilled: int, skipped: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header_needed = not path.exists()
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []
    if header_needed:
        lines.append("# Invoice Log (US-008)\n")
        lines.append("US-008 `create_invoices.py` 실행 이력. 각 섹션은 1회 실행.\n")
    lines.append(
        f"\n## {now} — created={created} posted={posted} "
        f"backfilled={backfilled} skipped={skipped} total={len(rows)}\n"
    )
    lines.append(
        "| inv id | inv name | so id | so name | partner_id | partner | invoice_date | state | amount_total | so_amount | match | status |\n"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    for r in rows:
        lines.append(
            "| {iid} | {iname} | {sid} | {sname} | {pid} | {pname} | {idate} | {st} | {at} | {sa} | {mm} | {stat} |\n".format(
                iid=r.get("inv_id", "-"),
                iname=r.get("inv_name", "-"),
                sid=r.get("so_id", "-"),
                sname=r.get("so_name", "-"),
                pid=r["partner_id"],
                pname=r["partner_name"],
                idate=r.get("invoice_date", "-"),
                st=r.get("state", "-"),
                at=f"{r.get('amount_total', 0):,.0f}",
                sa=f"{r.get('so_amount', 0):,.0f}" if r.get("so_amount") is not None else "-",
                mm="✓" if r.get("amount_match") else ("-" if r.get("status") in ("backfilled", "skipped") else "✗"),
                stat=r["status"],
            )
        )
    with path.open("a", encoding="utf-8") as f:
        f.writelines(lines)


if __name__ == "__main__":
    sys.exit(main())
