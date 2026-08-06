# U3 — 거래처 (odoo shell)
# 계약: docs/spec/greenpm-data-migration/u3-partners.md
# U1 산출물은 실행 전 컨테이너의 /tmp/normalized.json 으로 넣어둔다.
import json

with open('/tmp/normalized.json', encoding='utf-8') as f:
    D = json.load(f)

P = env['res.partner']
KR = env.ref('base.kr')

# --- 그린피엠 자신을 가리키는 거래처가 고객으로 잡히지 않게 한다 --------------------
# 이 레코드는 관리자 사용자에 연결된 연락처이므로 삭제할 수 없고 삭제해서도 안 된다.
# 자기 자신과 거래가 생기지 않도록 고객/공급업체 표시만 해제한다.
company_partner = env.company.partner_id
selfish = P.search([('name', 'in', ['green PM', 'greenPM']), ('id', '!=', company_partner.id)])
for p in selfish:
    if p.customer_rank or p.supplier_rank:
        print(f"자기회사 거래처 표시 해제: {p.id} {p.name} (고객={p.customer_rank} 공급={p.supplier_rank})")
        p.write({'customer_rank': 0, 'supplier_rank': 0})

# --- 고객 회사 + 담당자 ------------------------------------------------------------
pairs = {}                       # 회사명 → 담당자명(없으면 None)
for r in D['매출']:
    co, person = r['거래처'], r['담당자']
    # 담당자 표기가 회사명과 같으면 담당자 미상 표기이지 사람이 아니다.
    person = None if person == co else person
    if co not in pairs or (pairs[co] is None and person):
        pairs[co] = person

customers = {}
for co, person in sorted(pairs.items()):
    p = P.search([('name', '=', co), ('is_company', '=', True)], limit=1)
    if not p:
        p = P.create({'name': co, 'is_company': True, 'country_id': KR.id, 'customer_rank': 1})
    elif not p.customer_rank:
        p.customer_rank = 1
    customers[co] = p
    if person:
        c = P.search([('name', '=', person), ('parent_id', '=', p.id)], limit=1)
        if not c:
            P.create({'name': person, 'is_company': False, 'parent_id': p.id, 'type': 'contact'})

# 본지점 연결
branch, head = customers.get('프린트라인 울산점'), customers.get('프린트라인')
if branch and head and branch.parent_id != head:
    branch.write({'parent_id': head.id, 'is_company': True})
    print(f"본지점 연결: {branch.name} → {head.name}")

# --- 공급업체 -----------------------------------------------------------------------
vendors = sorted({r['매입처'] for r in D['원부자재']} | {r['매입처'] for r in D['외주']})
for v in vendors:
    p = P.search([('name', '=', v), ('is_company', '=', True)], limit=1)
    if not p:
        P.create({'name': v, 'is_company': True, 'country_id': KR.id, 'supplier_rank': 1})
    elif not p.supplier_rank:
        p.supplier_rank = 1

env.cr.commit()

n_cust = P.search_count([('customer_rank', '>', 0), ('is_company', '=', True)])
n_vend = P.search_count([('supplier_rank', '>', 0), ('is_company', '=', True)])
n_contact = P.search_count([('is_company', '=', False), ('parent_id', 'in', [c.id for c in customers.values()])])
print(f"\n고객 회사 {n_cust} · 공급업체 {n_vend} · 담당자 {n_contact}")
