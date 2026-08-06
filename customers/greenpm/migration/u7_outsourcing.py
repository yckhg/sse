# U7 — 외주정산 적재 (odoo shell)
# 계약: docs/spec/greenpm-data-migration/u7-outsourcing.md
import json

with open('/tmp/normalized.json', encoding='utf-8') as f:
    D = json.load(f)

P = env['res.partner']
PT = env['product.template']
Move = env['account.move']

svc_outsource = PT.search([('name', '=', '외주 가공비')], limit=1).product_variant_id
svc_tax = PT.search([('name', '=', '세무 관리비')], limit=1).product_variant_id
assert svc_outsource and svc_tax, "서비스 품목 조회 실패"

tax = env['account.tax'].search(
    [('type_tax_use', '=', 'purchase'), ('amount', '=', 10.0), ('company_id', '=', env.company.id)], limit=1)
tax.price_include_override = 'tax_included'

bank_journal = env['account.journal'].search([('type', '=', 'bank')], limit=1)

created = skipped = 0
for r in D['외주']:
    if r['금액'] is None:
        # 청구액이 확정되지 않은 예정 건 — 확정되지 않은 금액을 장부에 올리지 않는다.
        skipped += 1
        continue

    partner = P.search([('name', '=', r['매입처']), ('is_company', '=', True)], limit=1)
    assert partner, f"공급업체 없음: {r['매입처']}"
    product = svc_tax if r['매입처'] == '세무법인' else svc_outsource

    desc = r['구분'] + (f" · {r['비고']}" if r['비고'] else '')
    bill = Move.create({
        'move_type': 'in_invoice',
        'partner_id': partner.id,
        'invoice_date': r['시기'],
        'date': r['시기'],
        'ref': f"외주정산 {r['매입처']} · {r['구분']}"
               + (f" · 정산 {r['정산시기']}" if r['정산시기'] else ''),
        'invoice_line_ids': [(0, 0, {
            'product_id': product.id,
            'name': desc,
            'quantity': 1,
            'price_unit': r['금액'],
            'tax_ids': [(6, 0, tax.ids)],
        })],
    })
    bill.action_post()
    assert round(bill.amount_total) == r['금액'], f"총액 불일치 {bill.amount_total} != {r['금액']}"

    if r['결제완료']:
        w = env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids).create(
                {'payment_date': r['시기'], 'journal_id': bank_journal.id})
        w._create_payments()
    created += 1

env.cr.commit()

bills = Move.search([('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                     ('ref', 'like', '외주정산%')])
bills.invalidate_recordset(['amount_residual'])
print(f"\n생성 {created}건 · 금액 미확정으로 제외 {skipped}건")
print(f"외주 매입 청구서 {len(bills)}건 합계 {sum(bills.mapped('amount_total')):,.0f}")
print(f"미지급 {sum(bills.mapped('amount_residual')):,.0f}")

from collections import Counter
c = Counter()
for b in bills:
    c[b.partner_id.name] += b.amount_total
for k in sorted(c):
    n = len(bills.filtered(lambda x: x.partner_id.name == k))
    print(f"  {k:8} {n:>3}건 {c[k]:>12,.0f}")
