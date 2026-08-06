# U7(보정) — 세무 관리비 계정을 지급수수료로 바로잡는다
# 계약: docs/spec/greenpm-data-migration/u7-outsourcing.md (단언 E), u4-products.md
# 코드만 보고 계정을 고르면 이미 다른 뜻으로 쓰이는 계정(감가상각비)에 얹힐 수 있다.
# 이름과 유형까지 확인해 전용 계정을 만들고, 잘못 게시된 전표를 재생성한다.
import json

with open('/tmp/normalized.json', encoding='utf-8') as f:
    D = json.load(f)

A = env['account.account']
PC = env['product.category']
Move = env['account.move']
P = env['res.partner']
PT = env['product.template']

fee = A.search([('name', '=', '지급수수료'), ('account_type', '=', 'expense')], limit=1)
if not fee:
    used = set(A.search([('code', 'like', '6100%')]).mapped('code'))
    code = next(f"6100{n:02d}" for n in range(14, 100) if f"6100{n:02d}" not in used)
    fee = A.create({'code': code, 'name': '지급수수료', 'account_type': 'expense'})
    print(f"계정 신규 생성: {fee.code} {fee.name} ({fee.account_type})")

cat = PC.search([('name', '=', '일반관리')], limit=1)
print(f"카테고리 '일반관리' 비용계정: {cat.property_account_expense_categ_id.code}"
      f"({cat.property_account_expense_categ_id.name}) → {fee.code}({fee.name})")
cat.property_account_expense_categ_id = fee.id

# 잘못된 계정으로 게시된 세무법인 전표를 제거하고 다시 만든다.
bad = Move.search([('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                   ('ref', 'like', '외주정산 세무법인%')])
print(f"재생성 대상 전표 {len(bad)}건")
pays = bad.matched_payment_ids
if pays:
    pays.action_draft()
    pays.unlink()
bad.button_draft()
bad.unlink()

svc_tax = PT.search([('name', '=', '세무 관리비')], limit=1).product_variant_id
tax = env['account.tax'].search(
    [('type_tax_use', '=', 'purchase'), ('amount', '=', 10.0), ('company_id', '=', env.company.id)], limit=1)
bank_journal = env['account.journal'].search([('type', '=', 'bank')], limit=1)
partner = P.search([('name', '=', '세무법인'), ('is_company', '=', True)], limit=1)

n = 0
for r in D['외주']:
    if r['매입처'] != '세무법인' or r['금액'] is None:
        continue
    bill = Move.create({
        'move_type': 'in_invoice',
        'partner_id': partner.id,
        'invoice_date': r['시기'],
        'date': r['시기'],
        'ref': f"외주정산 {r['매입처']} · {r['구분']}"
               + (f" · 정산 {r['정산시기']}" if r['정산시기'] else ''),
        'invoice_line_ids': [(0, 0, {
            'product_id': svc_tax.id,
            'name': r['구분'] + (f" · {r['비고']}" if r['비고'] else ''),
            'quantity': 1,
            'price_unit': r['금액'],
            'tax_ids': [(6, 0, tax.ids)],
        })],
    })
    bill.action_post()
    assert round(bill.amount_total) == r['금액']
    assert bill.invoice_line_ids.account_id == fee, \
        f"비용계정 불일치: {bill.invoice_line_ids.account_id.code}"
    if r['결제완료']:
        w = env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids).create(
                {'payment_date': r['시기'], 'journal_id': bank_journal.id})
        w._create_payments()
    n += 1

env.cr.commit()

print(f"\n재생성 {n}건")
print(f"{fee.code} 전표라인 {env['account.move.line'].search_count([('account_id', '=', fee.id)])}건")
print(f"610006(감가상각비) 전표라인 "
      f"{env['account.move.line'].search_count([('account_id.code', '=', '610006')])}건")
