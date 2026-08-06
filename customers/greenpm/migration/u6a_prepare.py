# U6(준비) — 단가 정밀도 상향 + 부분 실행분 되돌리기
# 원장 매입가는 총액이고 단가는 그것을 수량으로 나눈 값이다. KRW에서 총액이 수량으로
# 나누어떨어지지 않는 경우(예: 1,144,000 / 6,000) 소수 2자리 단가로는 총액을 재현할 수 없다.
# 단가 정밀도를 올려 총액 보존을 가능하게 한다. 이미 게시된 전표는 영향받지 않는다.

dp = env.ref('product.decimal_price')
print(f"단가 정밀도: {dp.digits} → 6")
dp.digits = 6

# 부분 실행된 원부자재 매입 전표와 그 결제를 되돌린다.
bills = env['account.move'].search([('move_type', '=', 'in_invoice'),
                                    ('ref', 'like', '원부자재 매입%')])
print(f"되돌릴 매입 전표 {len(bills)}건")
pays = bills.matched_payment_ids
if pays:
    print(f"  연결 결제 {len(pays)}건 제거")
    pays.action_draft()
    pays.unlink()
bills.button_draft()
bills.unlink()

env.cr.commit()
print("완료 — 새 프로세스에서 U6을 다시 실행하면 정밀도가 반영된다")
