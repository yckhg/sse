# U5 — 매출 적재 (odoo shell)
# 계약: docs/spec/greenpm-data-migration/u5-sales.md
import json
from datetime import datetime

with open('/tmp/normalized.json', encoding='utf-8') as f:
    D = json.load(f)

P = env['res.partner']
SO = env['sale.order']
PT = env['product.template']
Move = env['account.move']

# 원장 카테고리 → 판매 품목
CATEGORY_PRODUCT = {
    '현수막': '생분해 현수막',
    '배너': '생분해 배너',
    '어깨띠': '생분해 어깨띠',
    '기타': '기타 홍보물',
    '일반 재활용': None,   # 원장에 수량 발생 없음
    '가로등': None,
}
products = {n: PT.search([('name', '=', n)], limit=1).product_variant_id
            for n in set(CATEGORY_PRODUCT.values()) if n}
assert all(products.values()), "판매 품목 조회 실패"

tax = env['account.tax'].search(
    [('type_tax_use', '=', 'sale'), ('amount', '=', 10.0), ('company_id', '=', env.company.id)], limit=1)
assert tax, "매출 부가세 10% 세금을 찾을 수 없다"
# 원장 총액이 VAT 포함가이므로 세금 포함 방식으로 계산해야 합계가 일치한다.
tax.price_include_override = 'tax_included'

bank_journal = env['account.journal'].search([('type', '=', 'bank')], limit=1)
# 결제수단에 미결제(outstanding) 계정이 비어 있으면 입금이 전표를 만들지 못해 청구서가
# 대사되지 않는다. 표준 미결제 계정을 먼저 지정한다.
for ml, code in ((bank_journal.inbound_payment_method_line_ids, '111105'),
                 (bank_journal.outbound_payment_method_line_ids, '111106')):
    acct = env['account.account'].search([('code', '=', code)], limit=1)
    for line in ml:
        if not line.payment_account_id:
            line.payment_account_id = acct.id
warehouse = env['stock.warehouse'].search([('name', '=', '고양')], limit=1)


def allocate(net, lines):
    """공급가를 수량 비율로 균등 안분하고, 반올림 잔차는 마지막 라인이 흡수한다."""
    qty_total = sum(q for _, q in lines)
    out, acc = [], 0
    for idx, (name, qty) in enumerate(lines):
        if idx < len(lines) - 1:
            amt = round(net * qty / qty_total)
            acc += amt
        else:
            amt = net - acc
        out.append((name, qty, amt))
    return out


created = []
for r in D['매출']:
    partner = P.search([('name', '=', r['거래처']), ('is_company', '=', True)], limit=1)
    assert partner, f"거래처 없음: {r['거래처']}"
    contact = P.search([('name', '=', r['담당자']), ('parent_id', '=', partner.id)], limit=1)

    total = r['총액']
    net = round(total / 1.1)

    lines = [(CATEGORY_PRODUCT[c], q) for c, q in r['수량'].items() if CATEGORY_PRODUCT[c]]
    if lines:
        alloc = allocate(net, lines)
        order_lines = [(0, 0, {
            'product_id': products[name].id,
            'product_uom_qty': qty,
            'price_unit': (amt * 1.1) / qty,     # 세금 포함 단가
            'tax_ids': [(6, 0, tax.ids)],
        }) for name, qty, amt in alloc]
    else:
        # 카테고리 수량이 없는 거래 — 작업명을 설명으로 하는 라인 1개
        order_lines = [(0, 0, {
            'product_id': products['기타 홍보물'].id,
            'name': r['작업명'],
            'product_uom_qty': 1,
            'price_unit': total,
            'tax_ids': [(6, 0, tax.ids)],
        })]

    order = SO.create({
        'partner_id': partner.id,
        'partner_invoice_id': (contact or partner).id,
        'partner_shipping_id': (contact or partner).id,
        'date_order': r['일자'] + ' 00:00:00',
        'client_order_ref': r['작업명'],
        'warehouse_id': warehouse.id,
        'order_line': order_lines,
        'note': f"발송방식 {r['발송방식']} · 받는 곳 {r['받는곳']} · 결제방식 {r['결제방식']} "
                f"· 계산서 {r['계산서상태']}",
    })
    order.action_confirm()
    # 원장 주문일을 확정 절차가 덮어쓰므로 되돌린다.
    order.write({'date_order': r['일자'] + ' 00:00:00'})

    # 배송 — 발송일에 완료
    for pick in order.picking_ids:
        for ml in pick.move_ids:
            ml.quantity = ml.product_uom_qty
        pick.write({'note': f"{r['발송방식']} / {r['받는곳']}"})
        pick.button_validate()
        pick.write({'date_done': r['발송일'] + ' 00:00:00'})

    # 청구서 — 발송일에 게시
    inv = order._create_invoices()
    inv.write({'invoice_date': r['발송일'], 'date': r['발송일'],
               'ref': f"{r['작업명']} · 계산서 {r['계산서상태']}"})
    inv.action_post()

    assert inv.amount_total == total, f"청구 총액 불일치 {inv.amount_total} != {total} ({r['거래처']})"

    # 입금 — 결제완료 건만
    if r['결제완료']:
        pay = env['account.payment.register'].with_context(
            active_model='account.move', active_ids=inv.ids).create({
                'payment_date': r['발송일'],
                'journal_id': bank_journal.id,
                'communication': f"{r['작업명']} · {r['결제방식']}",
            })
        pay._create_payments()

    created.append((order, inv))

env.cr.commit()

orders = SO.search([('state', '=', 'sale')])
invs = Move.search([('move_type', '=', 'out_invoice'), ('state', '=', 'posted')])
print(f"\n판매주문 {len(orders)} · 주문라인 {sum(len(o.order_line) for o in orders)}")
print(f"청구서 {len(invs)} · 합계 {sum(invs.mapped('amount_total')):,.0f} "
      f"(공급가 {sum(invs.mapped('amount_untaxed')):,.0f} + 세액 {sum(invs.mapped('amount_tax')):,.0f})")
print(f"미수금 {sum(invs.mapped('amount_residual')):,.0f}")
print(f"배송 완료 {env['stock.picking'].search_count([('state', '=', 'done')])}")
