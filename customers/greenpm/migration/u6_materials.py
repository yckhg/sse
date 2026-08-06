# U6 — 원부자재 적재 (odoo shell)
# 계약: docs/spec/greenpm-data-migration/u6-materials.md
import json
from collections import defaultdict

with open('/tmp/normalized.json', encoding='utf-8') as f:
    D = json.load(f)

P = env['res.partner']
PT = env['product.template']
Move = env['account.move']
WH = env['stock.warehouse']

# 원장 '구분' → S1 품목명
PRODUCT_BY_KIND = {
    '생분해성 / 700폭': '생분해성 원단 700폭',
    '생분해성 / 600폭': '생분해성 원단 600폭',
    '생분해성 / 1600폭*': '생분해성 원단 1600폭',
    '점착 원단롤': '점착 원단롤',
    '종이명찰 양면': '종이명찰 양면',
    '종이명찰 단면 인쇄': '종이명찰 단면 인쇄',
    '종이명찰 단면': '종이명찰 단면',
    '박스 / 1200폭': '박스 1200폭',
    '박스 / 900폭': '박스 900폭',
    '박스 / 700폭': '박스 700폭',
    '박스 / 600폭': '박스 600폭',
    '종이테이프': '종이테이프',
    '띠지': '띠지',
    '잉크': '잉크',
}
# 스토리지 미기재 3건은 같은 품목군(종이명찰)이 기재된 보관처를 따른다.
DEFAULT_STORAGE = '백석'

warehouses = {w.name: w for w in WH.search([])}
products = {}
for kind, name in PRODUCT_BY_KIND.items():
    v = PT.search([('name', '=', name)], limit=1).product_variant_id
    assert v, f"품목 없음: {name}"
    products[kind] = v

tax = env['account.tax'].search(
    [('type_tax_use', '=', 'purchase'), ('amount', '=', 10.0), ('company_id', '=', env.company.id)], limit=1)
assert tax, "매입 부가세 10% 세금을 찾을 수 없다"
tax.price_include_override = 'tax_included'

bank_journal = env['account.journal'].search([('type', '=', 'bank')], limit=1)

# --- 1) 매입처·매입일이 같은 행은 하나의 청구서 -------------------------------------
groups = defaultdict(list)
for r in D['원부자재']:
    groups[(r['매입처'], r['매입일'])].append(r)

bills = []
for (vendor, day), rows in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
    partner = P.search([('name', '=', vendor), ('is_company', '=', True)], limit=1)
    assert partner, f"공급업체 없음: {vendor}"

    amounts = [r['매입가'] for r in rows if r['매입가'] is not None]
    total = sum(amounts)
    # 청구서 총액이 첫 행에만 적힌 경우(같은 세금계산서에 묶인 매입)는 행끼리 균등 분할한다.
    per_row = {id(r): (r['매입가'] if r['매입가'] is not None else None) for r in rows}
    if total and any(v is None for v in per_row.values()):
        share = total / len(rows)
        per_row = {id(r): share for r in rows}

    lines = []
    for r in rows:
        amt = per_row[id(r)]
        qty = r['매입량']
        lines.append((0, 0, {
            'product_id': products[r['구분']].id,
            'name': f"{r['구분']} ({r['자재구분']})",
            'quantity': qty,
            'price_unit': (amt or 0) / qty,
            'tax_ids': [(6, 0, tax.ids)],
        }))

    bill = Move.create({
        'move_type': 'in_invoice',
        'partner_id': partner.id,
        'invoice_date': day,
        'date': day,
        'ref': f"원부자재 매입 {vendor} {day}",
        'invoice_line_ids': lines,
    })
    if total:
        bill.action_post()
        assert round(bill.amount_total) == total, f"매입 총액 불일치 {bill.amount_total} != {total}"
        if all(r['결제완료'] for r in rows):
            w = env['account.payment.register'].with_context(
                active_model='account.move', active_ids=bill.ids).create(
                    {'payment_date': day, 'journal_id': bank_journal.id})
            w._create_payments()
    bills.append((bill, rows, total))
    print(f"  {'게시' if total else '초안'} {vendor:8} {day} 라인 {len(rows)} 합계 {total:>10,.0f}")

# --- 2) 입고 — 매입량을 보관처로 (창고·매입일·공급업체 단위의 입고 문서) --------------
vendor_loc = env.ref('stock.stock_location_suppliers')
Picking = env['stock.picking']

receipts = defaultdict(list)
for _, rows, _ in bills:
    for r in rows:
        receipts[(r['매입처'], r['매입일'], r['스토리지'] or DEFAULT_STORAGE)].append(r)

for (vendor, day, storage), rows in sorted(receipts.items(), key=lambda kv: kv[0][1]):
    wh = warehouses[storage]
    partner = P.search([('name', '=', vendor), ('is_company', '=', True)], limit=1)
    pick = Picking.create({
        'picking_type_id': wh.in_type_id.id,
        'partner_id': partner.id,
        'location_id': vendor_loc.id,
        'location_dest_id': wh.lot_stock_id.id,
        'scheduled_date': day + ' 00:00:00',
        'origin': f"원부자재 매입 {vendor} {day}",
        'move_ids': [(0, 0, {
            'product_id': products[r['구분']].id,
            'product_uom_qty': r['매입량'],
            'location_id': vendor_loc.id,
            'location_dest_id': wh.lot_stock_id.id,
        }) for r in rows],
    })
    pick.action_confirm()
    pick.action_assign()
    for mv in pick.move_ids:
        mv.quantity = mv.product_uom_qty
        mv.picked = True
    pick.button_validate()
    pick.write({'date_done': day + ' 00:00:00'})
    print(f"  입고 {vendor:8} {day} → {storage} 라인 {len(rows)}")

env.cr.commit()
print("\n입고 완료")

# --- 3) 재고 실사 — 잔여량이 기재된 품목을 점검일 기준으로 맞춘다 --------------------
Quant = env['stock.quant']
adjusted = 0
for r in D['원부자재']:
    if r['잔여량'] is None:
        continue
    wh = warehouses[r['스토리지'] or DEFAULT_STORAGE]
    q = Quant.with_context(inventory_mode=True).search([
        ('product_id', '=', products[r['구분']].id),
        ('location_id', '=', wh.lot_stock_id.id)], limit=1)
    if not q:
        q = Quant.with_context(inventory_mode=True).create({
            'product_id': products[r['구분']].id,
            'location_id': wh.lot_stock_id.id})
    q.with_context(inventory_mode=True).write({'inventory_quantity': r['잔여량']})
    q.with_context(inventory_mode=True).action_apply_inventory()
    adjusted += 1

env.cr.commit()

print(f"재고 실사 적용 {adjusted}건\n")
for name in sorted(set(PRODUCT_BY_KIND.values())):
    v = PT.search([('name', '=', name)], limit=1).product_variant_id
    for wh in warehouses.values():
        qty = sum(Quant.search([('product_id', '=', v.id),
                                ('location_id', 'child_of', wh.lot_stock_id.id)]).mapped('quantity'))
        if qty:
            print(f"  {name:20} {wh.name} {qty:>8,.0f}")
