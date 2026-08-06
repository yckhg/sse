# 전체 검증 — U2~U7 + S1 + 통합 단언 T1~T4 (odoo shell)
# 계약: docs/spec/greenpm-data-migration/
import json
from collections import Counter

with open('/tmp/normalized.json', encoding='utf-8') as f:
    D = json.load(f)

R = []


def check(tag, cond, detail):
    R.append((tag, bool(cond), detail))


P, PT, WH = env['res.partner'], env['product.template'], env['stock.warehouse']
Move, SO, Quant = env['account.move'], env['sale.order'], env['stock.quant']
Loc = env['stock.location'].with_context(active_test=False)

# ---------------- U2 창고 ----------------
whs = WH.search([])
check('U2-A', len(whs) == 2, f"창고 총수 {len(whs)} == 2")
check('U2-B', set(whs.mapped('name')) == {'고양', '백석'}, f"창고 이름 {sorted(whs.mapped('name'))}")
check('U2-C', all(w.lot_stock_id and w.lot_stock_id.location_id == w.view_location_id for w in whs),
      "각 창고의 보관위치가 자기 뷰 위치 아래에 있다: "
      + ", ".join(f"{w.name}={w.lot_stock_id.complete_name}" for w in whs))
company_locs = env.company.subcontracting_location_id | env.company.internal_transit_location_id
stray = Loc.search([('usage', 'in', ('internal', 'view')), ('warehouse_id', '=', False)]) - company_locs
check('U2-D', not stray, f"제거된 창고의 잔재 위치 {len(stray)}건 == 0 {[l.complete_name for l in stray]}")

# ---------------- S1 기준정보 키 ----------------
CUSTOMERS = ['(사)에코나우', '감동프로젝트', '경기도 일자리재단', '경기환경에너지', '그린PR', '덱스터스튜디오',
             '디자인812', '디자인크레파스', '맥가이버팩토리', '세이브더칠드런 서부', '엠엔피', '원예도',
             '지방재정공제회', '파루커뮤니케이션', '프린트라인', '프린트라인 울산점', '호롱불스튜디오']
VENDORS = ['엔위브', 'KIC', 'TZET', '박스팩', '대경', 'HW', '이스트애드',
           'DZ원', '세무법인'] + [f'외주{n}' for n in range(1, 10)]
PRODUCTS = ['생분해 현수막', '생분해 배너', '생분해 어깨띠', '기타 홍보물',
            '생분해성 원단 700폭', '생분해성 원단 600폭', '생분해성 원단 1600폭', '점착 원단롤',
            '종이명찰 양면', '종이명찰 단면 인쇄', '종이명찰 단면',
            '박스 1200폭', '박스 900폭', '박스 700폭', '박스 600폭', '종이테이프', '띠지', '잉크',
            '외주 가공비', '세무 관리비']

bad = [n for n in CUSTOMERS if P.search_count([('name', '=', n), ('is_company', '=', True)]) != 1]
check('S1-B', not bad, f"고객 회사명 {len(CUSTOMERS)}개 각 1건 · 불일치 {bad}")
bad = [n for n in VENDORS if P.search_count([('name', '=', n), ('is_company', '=', True)]) != 1]
check('S1-C', not bad, f"공급업체명 {len(VENDORS)}개 각 1건 · 불일치 {bad}")
bad = [n for n in PRODUCTS if PT.search_count([('name', '=', n)]) != 1]
check('S1-D', not bad, f"품목명 {len(PRODUCTS)}개 각 1건 · 불일치 {bad}")
check('S1-E', PT.search_count([('name', 'in', ['일반 재활용', '생분해 가로등'])]) == 0,
      "수량 0인 카테고리 품목 미생성")

# ---------------- U3 거래처 ----------------
n_cust = P.search_count([('customer_rank', '>', 0), ('is_company', '=', True)])
n_vend = P.search_count([('supplier_rank', '>', 0), ('is_company', '=', True)])
check('U3-A', n_cust == 17, f"고객 회사 {n_cust} == 17")
check('U3-B', n_vend == 18, f"공급업체 {n_vend} == 18")
cust_ids = P.search([('name', 'in', CUSTOMERS), ('is_company', '=', True)]).ids
n_contact = P.search_count([('is_company', '=', False), ('parent_id', 'in', cust_ids)])
check('U3-C', n_contact == 16, f"고객 담당자 {n_contact} == 16")
check('U3-D', P.search_count([('parent_id.name', '=', '원예도')]) == 0, "원예도 하위 연락처 0건")
d812 = P.search([('parent_id.name', '=', '디자인812'), ('is_company', '=', False)])
check('U3-E', len(d812) == 1 and d812.name == '박병준', f"디자인812 담당자 {d812.mapped('name')} == ['박병준']")
br = P.search([('name', '=', '프린트라인 울산점')], limit=1)
check('U3-F', br.parent_id.name == '프린트라인', f"프린트라인 울산점 상위 = {br.parent_id.name}")
check('U3-G', br.customer_rank > 0 and P.search([('name', '=', '프린트라인')], limit=1).customer_rank > 0,
      "본사·지점 모두 고객으로 식별")
selfish = P.search([('name', 'in', ['green PM', 'greenPM']), '|',
                    ('customer_rank', '>', 0), ('supplier_rank', '>', 0)])
check('U3-H', not selfish, f"자기회사 거래처가 고객/공급업체로 식별 {len(selfish)}건 == 0")

# ---------------- U4 품목 ----------------
storable = PT.search([('name', 'in', PRODUCTS), ('is_storable', '=', True)])
check('U4-C', len(storable) == 14, f"재고관리 품목 {len(storable)} == 14")
nonstorable = PT.search([('name', 'in', PRODUCTS), ('is_storable', '=', False)])
check('U4-D', len(nonstorable) == 6, f"재고 미관리 품목 {len(nonstorable)} == 6 (판매품4+서비스2)")
fee = PT.search([('name', '=', '세무 관리비')], limit=1).categ_id.property_account_expense_categ_id
cogs = PT.search([('name', '=', '외주 가공비')], limit=1).categ_id.property_account_expense_categ_id
check('U4-계정', fee.code != cogs.code,
      f"세무 관리비 비용계정 {fee.code}({fee.name}) ≠ 외주 가공비 {cogs.code}({cogs.name})")

# ---------------- U5 매출 ----------------
orders = SO.search([('state', '=', 'sale')])
inv = Move.search([('move_type', '=', 'out_invoice'), ('state', '=', 'posted')])
inv.invalidate_recordset(['amount_residual'])
check('U5-A', len(orders) == 23, f"확정 판매주문 {len(orders)} == 23")
check('U5-B', sum(len(o.order_line) for o in orders) == 26,
      f"주문라인 {sum(len(o.order_line) for o in orders)} == 26")
check('U5-C', len(inv) == 23 and round(sum(inv.mapped('amount_total'))) == 5_350_600,
      f"고객청구서 {len(inv)}건 합계 {sum(inv.mapped('amount_total')):,.0f} == 23건 5,350,600")
check('U5-D', round(sum(inv.mapped('amount_untaxed'))) == 4_864_178
      and round(sum(inv.mapped('amount_tax'))) == 486_422,
      f"공급가 {sum(inv.mapped('amount_untaxed')):,.0f} + 세액 {sum(inv.mapped('amount_tax')):,.0f}")
resid = inv.filtered(lambda m: m.amount_residual)
check('U5-E', round(sum(inv.mapped('amount_residual'))) == 1_430_000
      and set(resid.mapped('commercial_partner_id.name')) == {'그린PR'},
      f"미수금 {sum(inv.mapped('amount_residual')):,.0f} == 1,430,000 · 대상 {set(resid.mapped('commercial_partner_id.name'))}")
check('U5-F', len(inv) - len(resid) == 21, f"잔액 0인 청구서 {len(inv) - len(resid)} == 21")
mismatch = []
for r in D['매출']:
    m = inv.filtered(lambda x: (x.ref or '').split(' · ')[0] == r['작업명']
                     and round(x.amount_total) == r['총액'])
    if not m:
        mismatch.append((r['거래처'], r['작업명'], r['총액']))
check('U5-G', not mismatch, f"건별 청구총액이 원장과 일치 · 불일치 {mismatch}")
line_bad = [o.name for o in orders
            if round(sum(o.order_line.mapped('price_subtotal'))) != round(o.amount_untaxed)]
check('U5-H', not line_bad, f"라인합계 = 주문 공급가 · 불일치 {line_bad}")
done_pick = env['stock.picking'].search([('state', '=', 'done'),
                                         ('picking_type_id.code', '=', 'outgoing')])
check('U5-I', len(done_pick) == 23, f"완료된 출고 {len(done_pick)} == 23")
qty = Counter()
for o in orders:
    for l in o.order_line:
        qty[l.product_id.name] += l.product_uom_qty
check('U5-L', qty['생분해 현수막'] == 39 and qty['생분해 배너'] == 10
      and qty['생분해 어깨띠'] == 100 and qty['기타 홍보물'] == 5 + 1,
      f"품목별 수량 {dict(qty)} (기타 홍보물은 수량없음 예외 1건 포함해 6)")
check('U5-M', Move.search_count([('move_type', '=', 'out_invoice'), ('state', '=', 'draft')]) == 0,
      "초안 고객청구서 0건")

# ---------------- U6 원부자재 ----------------
mbills = Move.search([('move_type', '=', 'in_invoice'), ('ref', 'like', '원부자재 매입%')])
posted = mbills.filtered(lambda m: m.state == 'posted')
draft = mbills.filtered(lambda m: m.state == 'draft')
posted.invalidate_recordset(['amount_residual'])
check('U6-A', len(posted) == 10 and round(sum(posted.mapped('amount_total'))) == 3_737_440,
      f"게시 매입전표 {len(posted)}건 합계 {sum(posted.mapped('amount_total')):,.0f} == 10건 3,737,440")
check('U6-B', len(draft) == 1 and draft.partner_id.name == 'KIC'
      and str(draft.invoice_date) == '2026-07-03',
      f"초안 매입전표 {len(draft)}건 {draft.partner_id.name} {draft.invoice_date}")
check('U6-C', sum(len(b.invoice_line_ids) for b in mbills) == 15,
      f"매입전표 라인 {sum(len(b.invoice_line_ids) for b in mbills)} == 15")
enw = posted.filtered(lambda m: m.partner_id.name == '엔위브' and str(m.invoice_date) == '2024-10-22')
check('U6-E', len(enw) == 1 and len(enw.invoice_line_ids) == 2 and round(enw.amount_total) == 488_400,
      f"엔위브 2024-10-22: 라인 {len(enw.invoice_line_ids)} 총액 {enw.amount_total:,.0f}")
box = posted.filtered(lambda m: m.partner_id.name == '박스팩')
check('U6-F', len(box) == 1 and len(box.invoice_line_ids) == 4 and round(box.amount_total) == 185_000,
      f"박스팩 2024-08-20: 라인 {len(box.invoice_line_ids)} 총액 {box.amount_total:,.0f}")
EXPECT_STOCK = {
    ('생분해성 원단 700폭', '고양'): 0, ('생분해성 원단 600폭', '고양'): 0,
    ('생분해성 원단 1600폭', '고양'): 45, ('점착 원단롤', '백석'): 48,
    ('종이명찰 양면', '백석'): 500, ('종이명찰 단면 인쇄', '백석'): 2000,
    ('종이명찰 단면', '백석'): 2000, ('박스 1200폭', '고양'): 10, ('박스 900폭', '고양'): 15,
    ('박스 700폭', '고양'): 10, ('박스 600폭', '고양'): 10, ('종이테이프', '고양'): 3,
    ('띠지', '백석'): 1000, ('잉크', '백석'): 2,
}
whmap = {w.name: w for w in whs}
stock_bad = []
for (pname, whname), want in EXPECT_STOCK.items():
    v = PT.search([('name', '=', pname)], limit=1).product_variant_id
    got = sum(Quant.search([('product_id', '=', v.id),
                            ('location_id', 'child_of', whmap[whname].lot_stock_id.id)]).mapped('quantity'))
    if round(got) != want:
        stock_bad.append((pname, whname, got, want))
check('U6-G', not stock_bad, f"실사 후 현재고 14품목 일치 · 불일치 {stock_bad}")
cross = []
for (pname, whname) in EXPECT_STOCK:
    v = PT.search([('name', '=', pname)], limit=1).product_variant_id
    other = [w for w in whmap if w != whname]
    for o in other:
        got = sum(Quant.search([('product_id', '=', v.id),
                                ('location_id', 'child_of', whmap[o].lot_stock_id.id)]).mapped('quantity'))
        if round(got):
            cross.append((pname, o, got))
check('U6-H', not cross, f"보관처 교차 없음 · 교차 {cross}")
check('U6-J', round(sum(posted.mapped('amount_residual'))) == 0,
      f"원부자재 미지급 {sum(posted.mapped('amount_residual')):,.0f} == 0")

# ---------------- U7 외주정산 ----------------
obills = Move.search([('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                      ('ref', 'like', '외주정산%')])
obills.invalidate_recordset(['amount_residual'])
tot_o = round(sum(obills.mapped('amount_total')))
check('U7-A', len(obills) == 36 and tot_o == 4_662_129,
      f"외주 청구서 {len(obills)}건 합계 {tot_o:,} == 36건 4,662,129")
check('U7-B', tot_o != 9_324_258, f"소계 혼입 검출: 합계 {tot_o:,} != 9,324,258")
byv = Counter()
for b in obills:
    byv[b.partner_id.name] += b.amount_total
oj = round(sum(v for k, v in byv.items() if k.startswith('외주')))
check('U7-C', round(byv['DZ원']) == 2_570_129 and round(byv['세무법인']) == 1_815_000 and oj == 277_000,
      f"DZ원 {byv['DZ원']:,.0f} · 세무법인 {byv['세무법인']:,.0f} · 외주1~9 {oj:,}")
check('U7-D', not obills.filtered(lambda b: 'sh공사 행사' in (b.ref or '') or '인플릿' in (b.ref or '')),
      "금액 미확정 2건 미생성")
taxlines = obills.invoice_line_ids.filtered(lambda l: l.product_id.name == '세무 관리비')
check('U7-E', len(taxlines) == 11 and all(round(l.price_unit) == 165_000 for l in taxlines)
      and set(taxlines.mapped('move_id.partner_id.name')) == {'세무법인'},
      f"세무 관리비 라인 {len(taxlines)}건 == 11 · 전부 165,000")
outlines = obills.invoice_line_ids.filtered(lambda l: l.product_id.name == '외주 가공비')
check('U7-F', len(outlines) == 25 and '세무법인' not in outlines.mapped('move_id.partner_id.name'),
      f"외주 가공비 라인 {len(outlines)}건 == 25")
future = obills.filtered(lambda b: str(b.invoice_date) > '2026-06-01')
check('U7-G', not future, f"원장 최종일 이후 청구일 {len(future)}건 == 0")
check('U7-I', round(sum(obills.mapped('amount_residual'))) == 0,
      f"외주 미지급 {sum(obills.mapped('amount_residual')):,.0f} == 0")
check('U7-J', not obills.filtered(lambda b: b.invoice_line_ids.filtered(lambda l: l.product_id.is_storable)),
      "외주 청구서에 재고 품목 없음")

# ---------------- 통합 T1~T4 ----------------
all_bills = Move.search([('move_type', '=', 'in_invoice'), ('state', '=', 'posted')])
check('T2', round(sum(all_bills.mapped('amount_total'))) == 8_399_569,
      f"공급업체청구서 게시분 합계 {sum(all_bills.mapped('amount_total')):,.0f} == 8,399,569")
all_bills.invalidate_recordset(['amount_residual'])
check('T3', round(sum(inv.mapped('amount_residual'))) == 1_430_000
      and round(sum(all_bills.mapped('amount_residual'))) == 0,
      f"미수금 {sum(inv.mapped('amount_residual')):,.0f} · 미지급 {sum(all_bills.mapped('amount_residual')):,.0f}")

w = max(len(t) for t, _, _ in R)
ok = sum(1 for _, p, _ in R if p)
for tag, passed, detail in R:
    print("  %s  %-*s  %s" % ('OK ' if passed else 'NOK', w, tag, detail))
print("\n%d/%d 통과" % (ok, len(R)))
