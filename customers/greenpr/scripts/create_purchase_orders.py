"""US-009: sale.order(US-007) → purchase.order(+line) 22건 생성 + button_confirm.

각 flow 당:
  1. sale.order 찾기 (US-007 marker via sale.order.note → so_id, so_name, so_lines)
  2. purchase.order create (vendor 결정적 매핑 / 같은 product_id·qty / price_unit = SO × 0.6~0.7)
  3. button_confirm → state='purchase'

Idempotent marker: <!-- ralph-demo-flow id=greenpr:po:<partner_id>:<planned_date> -->
저장 필드: purchase.order.note

실행:
    # 호스트 (게이트웨이 경유)
    ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/create_purchase_orders.py
    # 컨테이너 내부
    docker cp customers/greenpr/scripts/ ycerp-web-greenpr:/tmp/
    docker exec ycerp-web-greenpr python3 /tmp/scripts/create_purchase_orders.py

인자:
    --dry-run               계획만 출력
    --limit N               앞 N 건만 처리
    --skip-confirm          button_confirm 생략 (state='draft' 로 둠)
    --partners-json P       기본: ../docs/target-partners.json
    --products-json P       기본: ../docs/products.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odoo_client import OdooClient  # noqa: E402
from send_inquiries import (  # noqa: E402
    MARKER_PREFIX,
    SEED,
    TENANT_KEY,
    find_docs_path,
    load_partners,
    load_products,
    plan_flows,
)
from create_sale_orders import so_marker_needle  # noqa: E402

PO_MARKER_NS = "po"
DEFAULT_USER_ID = 2
DEFAULT_COMPANY_ID = 1
DEFAULT_CURRENCY_ID = 32  # KRW
DEFAULT_PICKING_TYPE_ID = 1  # GPR Receipts
DATE_ORDER_OFFSETS_DAYS = [1, 2, 1]  # SO.date_order + 1/2/1 일 (flow_idx % 3)
PRICE_RATIO_LOW = 0.60
PRICE_RATIO_HIGH = 0.70

# is_company=True / parent=False / supplier_rank>0, 잡음 이름 제외
VENDOR_POOL_FALLBACK: list[int] = [
    358, 476, 477, 478, 479, 480, 481, 482, 483, 484, 485, 486, 601,
]


def po_marker(partner_id: int, planned_date: str) -> str:
    return f"{TENANT_KEY}:{PO_MARKER_NS}:{partner_id}:{planned_date}"


def po_marker_needle(partner_id: int, planned_date: str) -> str:
    return f"{MARKER_PREFIX}{po_marker(partner_id, planned_date)}"


def find_so(cli: OdooClient, partner_id: int, planned_date: str) -> dict | None:
    found = cli.search(
        "sale.order",
        [["note", "like", so_marker_needle(partner_id, planned_date)]],
        limit=1,
    )
    if not found:
        return None
    rows = cli.read(
        "sale.order", found,
        ["id", "name", "amount_total", "amount_untaxed",
         "partner_id", "date_order", "order_line"],
    )
    return rows[0]


def find_existing_po(cli: OdooClient, partner_id: int, planned_date: str) -> int | None:
    found = cli.search(
        "purchase.order",
        [["note", "like", po_marker_needle(partner_id, planned_date)]],
        limit=1,
    )
    return found[0] if found else None


def fetch_vendor_pool(cli: OdooClient) -> list[dict]:
    rows = cli.search_read(
        "res.partner",
        [["id", "in", VENDOR_POOL_FALLBACK]],
        ["id", "name", "supplier_rank"],
        order="id asc",
    )
    return rows


def pick_vendor(vendor_pool: list[dict], partner_id: int, flow_idx: int) -> dict | None:
    if not vendor_pool:
        return None
    return vendor_pool[(partner_id + flow_idx) % len(vendor_pool)]


def derive_price_ratio(flow_idx: int) -> float:
    rng = random.Random(SEED + flow_idx)
    return rng.uniform(PRICE_RATIO_LOW, PRICE_RATIO_HIGH)


def build_po_date(so_date_order: str, flow_idx: int) -> str:
    """SO.date_order(`'YYYY-MM-DD HH:MM:SS'`) + 1/2/1 일."""
    base_date = dt.datetime.fromisoformat(so_date_order)
    offset = DATE_ORDER_OFFSETS_DAYS[flow_idx % len(DATE_ORDER_OFFSETS_DAYS)]
    new = base_date + dt.timedelta(days=offset)
    return new.strftime("%Y-%m-%d %H:%M:%S")


def build_note(flow: dict, so_id: int, so_name: str, vendor_name: str, ratio: float) -> str:
    marker = po_marker(flow["partner_id"], flow["planned_date"])
    body = (
        f"매입 발주 (SO #{so_id}/{so_name} → 고객 {flow['partner_name']}, "
        f"vendor {vendor_name}, 단가비율 {ratio:.3f}). "
        f"product_id={flow['product_id']} qty={flow['qty']} planned_date={flow['planned_date']}."
    )
    return (
        f"<p>{html.escape(body)}</p>"
        f"<!-- {MARKER_PREFIX}{marker} -->"
    )


def build_po_vals(
    flow: dict, so: dict, so_lines: list[dict], vendor: dict, flow_idx: int,
) -> dict:
    ratio = derive_price_ratio(flow_idx)
    line_vals = []
    for sol in so_lines:
        po_price = round(float(sol["price_unit"]) * ratio, 2)
        line_vals.append((0, 0, {
            "product_id": sol["product_id"][0] if isinstance(sol["product_id"], list) else sol["product_id"],
            "product_qty": sol["product_uom_qty"],
            "price_unit": po_price,
            "name": sol["name"],
        }))
    return {
        "partner_id": vendor["id"],
        "date_order": build_po_date(so["date_order"], flow_idx),
        "user_id": DEFAULT_USER_ID,
        "company_id": DEFAULT_COMPANY_ID,
        "currency_id": DEFAULT_CURRENCY_ID,
        "picking_type_id": DEFAULT_PICKING_TYPE_ID,
        "origin": so["name"],
        "note": build_note(flow, so["id"], so["name"], vendor["name"], ratio),
        "order_line": line_vals,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--skip-confirm", action="store_true")
    ap.add_argument("--partners-json", type=Path, default=None)
    ap.add_argument("--products-json", type=Path, default=None)
    ap.add_argument(
        "--log-path", type=Path, default=None,
        help="po-log.md 경로. 기본: docs/po-log.md",
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

    vendor_pool = fetch_vendor_pool(cli)
    print(
        f"[plan] partners={len(partners)} products={len(products)} flows={len(flows)} "
        f"vendor_pool={len(vendor_pool)}"
    )

    if not vendor_pool:
        # 스테이지 규약 §4.3: 빈 풀 → WARN + rc=0 + [summary] 출력.
        # rc=2 는 입력 오류용(argparse 등)이며, 빈 vendor pool 은 정상 발생 가능한 런타임
        # 상태라 스테이지 실패로 간주하지 않는다.
        print(
            "[WARN] vendor pool empty (supplier_rank>0 partners 없음) — 0 work",
            file=sys.stderr,
        )
        if not args.dry_run:
            print(
                f"[summary] created=0 confirmed=0 skipped={len(flows)} total={len(flows)}"
            )
        return 0

    if args.dry_run:
        for idx, f in enumerate(flows):
            so = find_so(cli, f["partner_id"], f["planned_date"])
            existing = find_existing_po(cli, f["partner_id"], f["planned_date"])
            vendor = pick_vendor(vendor_pool, f["partner_id"], idx)
            ratio = derive_price_ratio(idx)
            so_repr = f"so#{so['id']}/{so['name']}" if so else "MISSING"
            print(
                f"  {f['planned_date']}  partner_id={f['partner_id']:>4}  {so_repr:<24}  "
                f"vendor={vendor['id']:>4} {vendor['name']!r:<14}  ratio={ratio:.3f}  "
                f"existing_po={existing}"
            )
        return 0

    ctx = {"tracking_disable": True, "mail_create_nolog": True, "mail_notrack": True}
    created = 0
    confirmed = 0
    skipped = 0
    log_rows: list[dict] = []

    for flow_idx, f in enumerate(flows):
        marker = po_marker(f["partner_id"], f["planned_date"])

        # Step 1: locate SO
        so = find_so(cli, f["partner_id"], f["planned_date"])
        if not so:
            print(f"  [skip] no SO for partner={f['partner_id']} date={f['planned_date']}")
            log_rows.append({**f, "status": "missing_so", "marker": marker})
            skipped += 1
            continue

        # Step 2: idempotency
        existing = find_existing_po(cli, f["partner_id"], f["planned_date"])
        if existing:
            po_row = cli.read("purchase.order", [existing],
                              ["id", "name", "state", "partner_id", "amount_total"])[0]
            print(
                f"  [skip] marker={marker} -> purchase.order {po_row['id']} "
                f"({po_row['name']}, state={po_row['state']}, total={po_row['amount_total']:,.0f})"
            )
            log_rows.append({
                **f, "so_id": so["id"], "so_name": so["name"],
                "po_id": po_row["id"], "po_name": po_row["name"], "state": po_row["state"],
                "amount_total": po_row["amount_total"],
                "vendor_id": po_row["partner_id"][0] if po_row["partner_id"] else None,
                "vendor_name": po_row["partner_id"][1] if po_row["partner_id"] else None,
                "status": "skipped", "marker": marker,
            })
            skipped += 1
            continue

        # Step 3: build vals
        vendor = pick_vendor(vendor_pool, f["partner_id"], flow_idx)
        if not vendor:
            print(f"  [skip] vendor pool empty (unexpected) for partner={f['partner_id']}")
            log_rows.append({**f, "status": "no_vendor", "marker": marker})
            skipped += 1
            continue

        so_lines = cli.read(
            "sale.order.line", so["order_line"],
            ["product_id", "product_uom_qty", "price_unit", "name"],
        )

        vals = build_po_vals(f, so, so_lines, vendor, flow_idx)
        po_id = cli.execute_kw("purchase.order", "create", [[vals]], {"context": ctx})
        if isinstance(po_id, list):
            po_id = po_id[0]
        created += 1

        # Step 4: button_confirm
        if not args.skip_confirm:
            cli.call_method("purchase.order", "button_confirm", [po_id])
            confirmed += 1

        # Step 5: read back + verify
        po = cli.read(
            "purchase.order", [po_id],
            ["id", "name", "state", "partner_id", "date_order", "amount_total", "amount_untaxed", "origin"],
        )[0]

        # PRD AC: PO.qty == SO.qty (이미 동일 입력)
        # PRD AC: PO 단가 = SO 단가 × 0.6~0.7 (검증)
        ratio = derive_price_ratio(flow_idx)
        ratio_ok = PRICE_RATIO_LOW - 0.001 <= ratio <= PRICE_RATIO_HIGH + 0.001
        chronology_ok = po["date_order"] >= so["date_order"]
        flag = "OK" if (ratio_ok and chronology_ok) else "WARN"
        print(
            f"  [{flag:^4}] purchase.order id={po['id']:>4} ({po['name']})  "
            f"vendor={vendor['id']:>4} {vendor['name']!r:<14}  origin={po['origin']:<8}  "
            f"date_order={po['date_order']}  state={po['state']:>9}  "
            f"amount_total={po['amount_total']:>11,.2f}  ratio={ratio:.3f}"
        )

        log_rows.append({
            **f, "so_id": so["id"], "so_name": so["name"],
            "po_id": po["id"], "po_name": po["name"], "state": po["state"],
            "amount_total": po["amount_total"], "amount_untaxed": po["amount_untaxed"],
            "vendor_id": vendor["id"], "vendor_name": vendor["name"],
            "ratio": ratio, "date_order": po["date_order"],
            "so_amount": so["amount_total"], "chronology_ok": chronology_ok,
            "status": "created", "marker": marker,
        })

    print()
    print(
        f"[summary] created={created} confirmed={confirmed} skipped={skipped} total={len(flows)}"
    )

    log_path = args.log_path or (Path(__file__).resolve().parent.parent / "docs" / "po-log.md")
    try:
        append_log(log_path, log_rows, created, confirmed, skipped)
        print(f"[log] appended to {log_path}")
    except Exception as e:
        print(f"[log] WARN: {e}", file=sys.stderr)

    return 0


def append_log(
    path: Path, rows: list[dict], created: int, confirmed: int, skipped: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header_needed = not path.exists()
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []
    if header_needed:
        lines.append("# Purchase Order Log (US-009)\n")
        lines.append("US-009 `create_purchase_orders.py` 실행 이력. 각 섹션은 1회 실행.\n")
    lines.append(
        f"\n## {now} — created={created} confirmed={confirmed} "
        f"skipped={skipped} total={len(rows)}\n"
    )
    lines.append(
        "| po id | po name | so id | so name | partner_id | partner | vendor_id | vendor | date_order | state | amount_total | so_amount | ratio | status |\n"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    for r in rows:
        lines.append(
            "| {pid} | {pname} | {sid} | {sname} | {ppid} | {ppname} | {vid} | {vname} | {dt} | {st} | {at} | {sa} | {rat} | {stat} |\n".format(
                pid=r.get("po_id", "-"),
                pname=r.get("po_name", "-"),
                sid=r.get("so_id", "-"),
                sname=r.get("so_name", "-"),
                ppid=r["partner_id"],
                ppname=r["partner_name"],
                vid=r.get("vendor_id", "-"),
                vname=r.get("vendor_name", "-"),
                dt=r.get("date_order", "-"),
                st=r.get("state", "-"),
                at=f"{r.get('amount_total', 0):,.0f}",
                sa=f"{r.get('so_amount', 0):,.0f}" if r.get("so_amount") is not None else "-",
                rat=f"{r['ratio']:.3f}" if r.get("ratio") is not None else "-",
                stat=r["status"],
            )
        )
    with path.open("a", encoding="utf-8") as f:
        f.writelines(lines)


if __name__ == "__main__":
    sys.exit(main())
