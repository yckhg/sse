# U4 — 품목 + 계정 매핑 (odoo shell)
# 계약: docs/spec/greenpm-data-migration/u4-products.md
#       docs/spec/_shared/greenpm-master-data-keys.md (품목명)

A = env['account.account']
PC = env['product.category']
PT = env['product.template']

UOM_UNIT = env.ref('uom.product_uom_unit')
UOM_METER = env.ref('uom.product_uom_meter')

income = A.search([('code', '=', '410001')], limit=1)          # Sales Income - Goods
cogs = A.search([('code', '=', '510001')], limit=1)            # Cost of Revenue - Goods
assert income and cogs, "기본 수익/매출원가 계정을 찾을 수 없다"

# 지급수수료(판관비) — 계정과목표에 없으므로 생성한다. 세무 기장료가 매출원가에 섞이면
# 매출총이익이 왜곡되므로 판관비로 분리하기 위한 자리다.
# 코드만 보고 고르면 이미 다른 뜻으로 쓰이는 계정(예: 감가상각비)에 얹히므로, 이름으로 찾고
# 없으면 비어 있는 코드에 새로 만든다.
fee = A.search([('name', '=', '지급수수료'), ('account_type', '=', 'expense')], limit=1)
if not fee:
    used = set(A.search([('code', 'like', '6100%')]).mapped('code'))
    code = next(f"6100{n:02d}" for n in range(14, 100) if f"6100{n:02d}" not in used)
    fee = A.create({'code': code, 'name': '지급수수료', 'account_type': 'expense'})
    print(f"계정 신규 생성: {fee.code} {fee.name} ({fee.account_type})")

CATEGORIES = {
    '생분해 홍보물': (income, cogs),
    '원부자재': (income, cogs),
    '외주': (income, cogs),
    '일반관리': (income, fee),
}
cats = {}
for name, (inc, exp) in CATEGORIES.items():
    c = PC.search([('name', '=', name), ('parent_id', '=', False)], limit=1)
    vals = {'property_account_income_categ_id': inc.id, 'property_account_expense_categ_id': exp.id}
    if c:
        c.write(vals)
    else:
        c = PC.create({'name': name, **vals})
    cats[name] = c
    print(f"카테고리 {name:12} 수익={inc.code} 비용={exp.code}")

# (품목명, 카테고리, 재고추적, 단위, 판매, 구매)
PRODUCTS = [
    # 판매품 — 주문마다 제작하므로 셀 재고가 없다
    ('생분해 현수막',        '생분해 홍보물', False, UOM_UNIT,  True,  False),
    ('생분해 배너',          '생분해 홍보물', False, UOM_UNIT,  True,  False),
    ('생분해 어깨띠',        '생분해 홍보물', False, UOM_UNIT,  True,  False),
    ('기타 홍보물',          '생분해 홍보물', False, UOM_UNIT,  True,  False),
    # 원자재
    ('생분해성 원단 700폭',  '원부자재',     True,  UOM_METER, False, True),
    ('생분해성 원단 600폭',  '원부자재',     True,  UOM_METER, False, True),
    ('생분해성 원단 1600폭', '원부자재',     True,  UOM_METER, False, True),
    ('점착 원단롤',          '원부자재',     True,  UOM_METER, False, True),
    ('종이명찰 양면',        '원부자재',     True,  UOM_UNIT,  False, True),
    ('종이명찰 단면 인쇄',   '원부자재',     True,  UOM_UNIT,  False, True),
    ('종이명찰 단면',        '원부자재',     True,  UOM_UNIT,  False, True),
    # 부자재
    ('박스 1200폭',          '원부자재',     True,  UOM_UNIT,  False, True),
    ('박스 900폭',           '원부자재',     True,  UOM_UNIT,  False, True),
    ('박스 700폭',           '원부자재',     True,  UOM_UNIT,  False, True),
    ('박스 600폭',           '원부자재',     True,  UOM_UNIT,  False, True),
    ('종이테이프',           '원부자재',     True,  UOM_UNIT,  False, True),
    ('띠지',                 '원부자재',     True,  UOM_METER, False, True),
    ('잉크',                 '원부자재',     True,  UOM_UNIT,  False, True),
    # 서비스
    ('외주 가공비',          '외주',         False, UOM_UNIT,  False, True),
    ('세무 관리비',          '일반관리',     False, UOM_UNIT,  False, True),
]

for name, cat, tracked, uom, sale_ok, purchase_ok in PRODUCTS:
    vals = {
        'name': name,
        'categ_id': cats[cat].id,
        'type': 'consu',
        'is_storable': tracked,
        'uom_id': uom.id,
        'sale_ok': sale_ok,
        'purchase_ok': purchase_ok,
        'list_price': 0.0,
    }
    p = PT.search([('name', '=', name)], limit=1)
    if p:
        p.write(vals)
    else:
        PT.create(vals)

# 이관 대상이 아닌 기존 품목(이전 테넌트 잔재)은 판매·구매 목록에서 내린다.
names = [n for n, *_ in PRODUCTS]
stale = PT.search([('name', 'not in', names)])
if stale:
    print(f"\n이관 대상 외 기존 품목 {len(stale)}건: {[s.name for s in stale]}")

env.cr.commit()

print(f"\n품목 총 {PT.search_count([])}건")
for p in PT.search([('name', 'in', names)], order='id'):
    print(f"  {p.name:20} 카테고리={p.categ_id.name:12} 재고추적={p.is_storable} 단위={p.uom_id.name:4} "
          f"수익={p.categ_id.property_account_income_categ_id.code} 비용={p.categ_id.property_account_expense_categ_id.code}")
