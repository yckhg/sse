# U5(보정) — 입금 등록
# 계약: docs/spec/greenpm-data-migration/u5-sales.md (E·F 단언)
# 은행 저널의 결제수단에 미결제(outstanding) 계정이 비어 있으면 결제가 전표를 만들지 못해
# 청구서가 대사되지 않는다. 표준 미결제 계정을 지정한 뒤 입금을 등록한다.
import json

with open('/tmp/normalized.json', encoding='utf-8') as f:
    D = json.load(f)

A = env['account.account']
journal = env['account.journal'].search([('type', '=', 'bank')], limit=1)
recv = A.search([('code', '=', '111105')], limit=1)      # Outstanding Receipts
paym = A.search([('code', '=', '111106')], limit=1)      # Outstanding Payments
assert recv and paym, "미결제 계정을 찾을 수 없다"

for ml in journal.inbound_payment_method_line_ids:
    if not ml.payment_account_id:
        ml.payment_account_id = recv.id
for ml in journal.outbound_payment_method_line_ids:
    if not ml.payment_account_id:
        ml.payment_account_id = paym.id
print(f"저널 {journal.name} 미결제 계정: 수취={recv.code} 지급={paym.code}")

# 전표를 만들지 못한 채 남은 결제를 제거한다.
stale = env['account.payment'].search([('move_id', '=', False)])
if stale:
    print(f"전표 없는 결제 {len(stale)}건 제거")
    stale.action_cancel()
    stale.unlink()

# 원장에서 결제완료인 매출 건에 입금을 등록한다.
paid_refs = {r['작업명'] for r in D['매출'] if r['결제완료']}
invs = env['account.move'].search([('move_type', '=', 'out_invoice'), ('state', '=', 'posted')])

n = 0
for inv in invs:
    ref = (inv.ref or '').split(' · ')[0]
    r = next((x for x in D['매출'] if x['작업명'] == ref and x['총액'] == inv.amount_total), None)
    if not r or not r['결제완료'] or not inv.amount_residual:
        continue
    w = env['account.payment.register'].with_context(
        active_model='account.move', active_ids=inv.ids).create({
            'payment_date': r['발송일'],
            'journal_id': journal.id,
            'communication': f"{r['작업명']} · {r['결제방식']}",
        })
    w._create_payments()
    n += 1

env.cr.commit()

invs.invalidate_recordset(['amount_residual', 'payment_state'])
print(f"\n입금 등록 {n}건")
print(f"청구서 {len(invs)}건 합계 {sum(invs.mapped('amount_total')):,.0f}")
print(f"미수금 {sum(invs.mapped('amount_residual')):,.0f}")
for i in invs.filtered(lambda m: m.amount_residual):
    print(f"  잔액 남음: {i.name} {i.commercial_partner_id.name} {i.amount_residual:,.0f}")
