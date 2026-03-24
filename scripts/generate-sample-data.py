#!/usr/bin/env python3
"""범용 샘플 판매 데이터 생성 — 테넌트/기간/주문수를 지정하면 기존 DB의 고객/제품 기반으로 현실적인 판매 데이터를 자동 생성."""

import argparse
import random
import sys
import time
import xmlrpc.client
from datetime import datetime, timedelta

# Tenant → port mapping
TENANT_PORTS = {
    "greenpr": 30033,
    "mediapolytech": 30043,
    "visualoft": 30053,
    "jnj_i": 30063,
    "freeworks": 30073,
}

# Quantity patterns
QTY_CHOICES = [1, 2, 3, 5, 10, 20, 50, 100]
QTY_WEIGHTS = [15, 15, 10, 25, 20, 10, 3, 2]
QTY_CHOICES_EXPENSIVE = [1, 2, 3, 5, 10, 20]
QTY_WEIGHTS_EXPENSIVE = [15, 15, 10, 25, 20, 10]

# Order line count weights
LINE_COUNT_CHOICES = [1, 2, 3, 4]
LINE_COUNT_WEIGHTS = [30, 40, 20, 10]

EXPENSIVE_THRESHOLD = 100000


def parse_args():
    parser = argparse.ArgumentParser(
        description="Odoo 테넌트에 샘플 판매 데이터를 생성합니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""예시:
  %(prog)s --tenant greenpr --period 2026-03 --orders 15
  %(prog)s --tenant visualoft --period 2026-02 --orders 30 --dry-run
""",
    )
    parser.add_argument("--tenant", required=True, choices=TENANT_PORTS.keys(),
                        help="대상 테넌트")
    parser.add_argument("--period", required=True,
                        help="생성 기간 (YYYY-MM)")
    parser.add_argument("--orders", type=int, default=15,
                        help="생성할 주문 수 (기본: 15)")
    parser.add_argument("--user", default="admin",
                        help="Odoo 사용자 (기본: admin)")
    parser.add_argument("--password", default="admin",
                        help="Odoo 비밀번호 (기본: admin)")
    parser.add_argument("--dry-run", action="store_true",
                        help="DB 변경 없이 미리보기만 수행")
    return parser.parse_args()


def validate_period(period_str):
    """Validate and parse YYYY-MM period string."""
    try:
        dt = datetime.strptime(period_str, "%Y-%m")
        return dt.year, dt.month
    except ValueError:
        print(f"오류: 잘못된 기간 형식 '{period_str}'. YYYY-MM 형식을 사용하세요.")
        sys.exit(1)


def connect(tenant, user, password):
    """Connect to tenant via XML-RPC and return (uid, call_fn)."""
    port = TENANT_PORTS[tenant]
    url = f"http://localhost:{port}"
    db = "odoo"

    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", allow_none=True)

    try:
        uid = common.authenticate(db, user, password, {})
    except Exception as e:
        print(f"오류: {tenant} 테넌트({url})에 연결할 수 없습니다: {e}")
        sys.exit(1)

    if not uid:
        print(f"오류: 인증 실패 — 사용자({user}) 또는 비밀번호를 확인하세요.")
        sys.exit(1)

    print(f"인증 성공: {tenant} 테넌트 (uid={uid}, {url})")

    def call(model, method, *args, **kwargs):
        return models.execute_kw(db, uid, password, model, method, *args, **kwargs)

    return uid, call


def fetch_customers(call):
    """Fetch active customers from res.partner."""
    customers = call("res.partner", "search_read",
                     [[("customer_rank", ">", 0), ("active", "=", True)]],
                     {"fields": ["id", "name"]})
    if not customers:
        print("오류: 활성 고객이 없습니다.")
        sys.exit(1)
    return customers


def fetch_products(call):
    """Fetch saleable active products from product.product."""
    products = call("product.product", "search_read",
                    [[("sale_ok", "=", True), ("active", "=", True)]],
                    {"fields": ["id", "name", "list_price"]})
    if not products:
        print("오류: 판매 가능 제품이 없습니다.")
        sys.exit(1)
    return products


def get_business_days(year, month):
    """Return list of business days (Mon-Fri) in the given month."""
    days = []
    dt = datetime(year, month, 1)
    if month == 12:
        next_month = datetime(year + 1, 1, 1)
    else:
        next_month = datetime(year, month + 1, 1)
    while dt < next_month:
        if dt.weekday() < 5:  # Mon-Fri
            days.append(dt)
        dt += timedelta(days=1)
    return days


def random_datetime(business_days):
    """Pick a random business day with random time 08:00-17:00."""
    day = random.choice(business_days)
    hour = random.randint(8, 17)
    minute = random.randint(0, 59)
    second = random.randint(0, 59)
    return day.replace(hour=hour, minute=minute, second=second)


def pick_qty(product):
    """Pick a quantity with weighted random, restricting expensive products."""
    if product["list_price"] >= EXPENSIVE_THRESHOLD:
        return random.choices(QTY_CHOICES_EXPENSIVE, weights=QTY_WEIGHTS_EXPENSIVE, k=1)[0]
    return random.choices(QTY_CHOICES, weights=QTY_WEIGHTS, k=1)[0]


def generate_order_spec(customers, products, business_days):
    """Generate a single order specification (no DB writes)."""
    partner = random.choice(customers)
    date = random_datetime(business_days)
    num_lines = random.choices(LINE_COUNT_CHOICES, weights=LINE_COUNT_WEIGHTS, k=1)[0]
    selected_products = random.sample(products, min(num_lines, len(products)))
    lines = []
    for p in selected_products:
        qty = pick_qty(p)
        lines.append({"product": p, "qty": qty})
    return {
        "partner": partner,
        "date": date,
        "lines": lines,
    }


def create_order(call, spec):
    """Create and confirm a sale.order from spec."""
    order_lines = []
    for line in spec["lines"]:
        order_lines.append((0, 0, {
            "product_id": line["product"]["id"],
            "product_uom_qty": line["qty"],
        }))

    order_id = call("sale.order", "create", [{
        "partner_id": spec["partner"]["id"],
        "date_order": spec["date"].strftime("%Y-%m-%d %H:%M:%S"),
        "order_line": order_lines,
    }])

    call("sale.order", "action_confirm", [[order_id]])

    # Get SO name
    order_data = call("sale.order", "read", [[order_id], ["name"]])
    so_name = order_data[0]["name"] if order_data else f"SO#{order_id}"

    total = sum(l["product"]["list_price"] * l["qty"] for l in spec["lines"])
    return order_id, so_name, total


def deliver_order(call, order_id):
    """Find and validate the delivery for a confirmed order."""
    pickings = call("stock.picking", "search", [[
        ("sale_id", "=", order_id),
        ("state", "in", ["assigned", "confirmed", "waiting"]),
    ]])

    delivered = 0
    for pick_id in pickings:
        try:
            moves = call("stock.move", "search_read",
                         [[("picking_id", "=", pick_id)]],
                         {"fields": ["id", "product_uom_qty"]})
            for move in moves:
                call("stock.move", "write", [[move["id"]], {
                    "quantity": move["product_uom_qty"],
                }])
            call("stock.picking", "button_validate", [[pick_id]])
            delivered += 1
        except Exception as e:
            print(f"    배송 오류 pick={pick_id}: {e}")
    return delivered > 0


def create_invoice(call, order_id):
    """Create and post invoice for a delivered order."""
    try:
        ctx = {"active_ids": [order_id], "active_model": "sale.order"}
        wizard_id = call(
            "sale.advance.payment.inv", "create",
            [{"advance_payment_method": "delivered"}],
            {"context": ctx},
        )
        call(
            "sale.advance.payment.inv", "create_invoices",
            [[wizard_id]],
            {"context": ctx},
        )
        # Find and post draft invoices
        order_data = call("sale.order", "read", [[order_id], ["invoice_ids"]])
        if order_data and order_data[0].get("invoice_ids"):
            for inv_id in order_data[0]["invoice_ids"]:
                try:
                    inv_state = call("account.move", "read", [[inv_id], ["state"]])
                    if inv_state and inv_state[0]["state"] == "draft":
                        call("account.move", "action_post", [[inv_id]])
                except Exception as e:
                    print(f"    인보이스 확정 오류 inv={inv_id}: {e}")
        return True
    except Exception as e:
        print(f"    인보이스 생성 오류 order={order_id}: {e}")
        return False


def main():
    args = parse_args()
    year, month = validate_period(args.period)
    start_time = time.time()

    # Connect
    uid, call = connect(args.tenant, args.user, args.password)

    # Fetch existing data
    customers = fetch_customers(call)
    products = fetch_products(call)
    print(f"DB 분석: 고객 {len(customers)}명, 제품 {len(products)}개 발견")

    business_days = get_business_days(year, month)
    if not business_days:
        print(f"오류: {args.period}에 업무일이 없습니다.")
        sys.exit(1)

    # Generate order specs
    order_specs = [generate_order_spec(customers, products, business_days)
                   for _ in range(args.orders)]

    # Dry-run mode
    if args.dry_run:
        print(f"\n=== DRY-RUN 모드 ({args.tenant} / {args.period}) ===\n")
        print("--- 고객 목록 ---")
        for c in customers:
            print(f"  [{c['id']}] {c['name']}")
        print(f"\n--- 제품 목록 ---")
        for p in products:
            print(f"  [{p['id']}] {p['name']} (₩{p['list_price']:,.0f})")
        print(f"\n예상 주문 수: {args.orders}건")
        print(f"배송 예상: ~{int(args.orders * 0.7)}건 (70%)")
        print(f"인보이스 예상: ~{int(args.orders * 0.7 * 0.6)}건 (배송의 60%)")
        sys.exit(0)

    # Confirmation prompt
    resp = input(f"\n'{args.tenant}' 테넌트에 {args.orders}건의 주문을 생성합니다. 계속? [y/N] ")
    if resp.lower() != "y":
        print("취소되었습니다.")
        sys.exit(0)

    # === Create orders ===
    print(f"\n=== 주문 생성 ({args.period}) ===\n")
    created_orders = []
    for i, spec in enumerate(order_specs, 1):
        order_id, so_name, total = create_order(call, spec)
        created_orders.append(order_id)
        print(f"  [{i}/{args.orders}] {so_name} | {spec['partner']['name']} | "
              f"제품 {len(spec['lines'])}개 | ₩{total:,.0f} → 확정")

    # === Deliver ~70% ===
    print(f"\n=== 배송 처리 ===\n")
    deliver_count = int(len(created_orders) * 0.7)
    orders_to_deliver = random.sample(created_orders, k=deliver_count)
    delivered = 0
    for order_id in orders_to_deliver:
        if deliver_order(call, order_id):
            delivered += 1
    print(f"  배송 처리: {delivered}/{deliver_count} 완료")

    # === Invoice ~60% of delivered ===
    print(f"\n=== 인보이스 발행 ===\n")
    invoice_count = int(len(orders_to_deliver) * 0.6)
    orders_to_invoice = random.sample(orders_to_deliver, k=invoice_count)
    invoiced = 0
    for order_id in orders_to_invoice:
        if create_invoice(call, order_id):
            invoiced += 1
    print(f"  인보이스: {invoiced}/{invoice_count} 발행")

    # === Summary ===
    elapsed = time.time() - start_time
    print(f"\n=== 완료 ===")
    print(f"완료: 주문 {len(created_orders)}건, 배송 {delivered}건, 인보이스 {invoiced}건")
    print(f"처리 시간: {elapsed:.1f}초")


if __name__ == "__main__":
    main()
