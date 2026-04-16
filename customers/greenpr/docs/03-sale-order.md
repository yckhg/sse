# US-007 — 견적서(Sale Order) 생성

전체 플로우 3단계: 문의(US-005 `mail.mail`) → CRM 영업건(US-006 `crm.lead`) → **견적서(US-007 `sale.order`)**.
각 `crm.lead` (22건, 파트너 11 × 2) 에 대해 `sale.order` 1건 + `sale.order.line` 1건을 생성하고
`action_confirm` 으로 `state='sale'` 전환. 이후 `crm.lead.expected_revenue` 를 SO `amount_total` 로 재-write 해 정합을 맞춘다.

## 1. greenpr 환경 조사

XML-RPC `sale.order.fields_get` + 기존 sale.order 샘플 read 결과 (2026-04-16 기준).

### 1-1. 사용 필드 (sale.order create)

| 필드 | type | 필수 | 사용 값/소스 |
|---|---|---|---|
| `partner_id` | many2one→res.partner | ✓ | `lead.partner_id` |
| `opportunity_id` | many2one→crm.lead | – | **본 스토리의 핵심 연결**. US-006 lead id |
| `date_order` | datetime | ✓ | `lead.date_open + {0,1,2}일` (flow_idx 로 결정적 선택) |
| `user_id` | many2one→res.users | – | **2 = admin (green PR)**. lead.user_id 상속 |
| `team_id` | many2one→crm.team | – | **1 = Sales** |
| `company_id` | many2one→res.company | ✓ | **1 = greenPR** (유일) |
| `warehouse_id` | many2one→stock.warehouse | – | **1 = GPR** (greenPR 기본) |
| `pricelist_id` | many2one→product.pricelist | – | **1 = 기본 (KRW)** |
| `note` | html | – | idempotent marker + 연결 정보 주석 |
| `origin` | char | – | `"CRM Lead #<id>"` (추적 편의) |
| `client_order_ref` | char | – | `"문의 #<mail.mail id>"` (연결 표시) |
| `order_line` | one2many→sale.order.line | – | `[(0, 0, line_vals)]` |

### 1-2. 사용 필드 (sale.order.line create)

| 필드 | type | 필수 | 사용 값/소스 |
|---|---|---|---|
| `product_id` | many2one→product.product | – | flow `product_id` (US-005/006 과 동일) |
| `product_uom_qty` | float | ✓ | flow `qty` (US-005/006 과 동일 — 체인 정합성) |
| `price_unit` | float | ✓ | `product.list_price` (US-006 expected_revenue 계산 근거) |
| `name` | text | ✓ | `product.name` |
| `tax_ids` | many2many | – | **설정 안 함** — Odoo 가 product 의 기본 `taxes_id` 를 자동 적용 (확인: 10% TI, id=6) |
| `discount` | float | – | 0.0 |

### 1-3. 읽기/계산 필드

- `name` (sale.order): 시퀀스 자동 채번 (`S00xxx`).
- `state`: create 직후 `'draft'`. `action_confirm` 후 `'sale'`.
- `amount_untaxed`, `amount_tax`, `amount_total`: 라인에서 자동 계산.
- `currency_id`: company.currency_id(KRW, id=32) 파생.
- `date_order`: **XML-RPC vals 에서 받아 저장됨** — `create_date` 와 달리 magic column 이 아니므로 write 가능. 단 `create_date` 자체는 US-006 패턴처럼 SQL UPDATE 필요할 수 있음 (본 스토리는 `date_order` 만 활용).

### 1-4. 기존 데이터 스냅샷 (greenpr, 2026-04-16)

```text
sale.order (0~99 건 36개, 100~102 = 2026-04-16 수동 draft)  — 전부 state='draft' (행사 마지막 confirm 이력 없음 — §4 Studio 이슈 참고)
res.company: 1 greenPR / currency KRW (id=32)
stock.warehouse: 1 GPR / 2 GPR-PM / 3 GPR-SD / 4 GPR-PL / 5 GPR-GN
product.pricelist: 1 기본 (KRW)
account.tax id=6 '10% TI' — type_tax_use='sale', amount=10, price_include=False
```

## 2. 생성 계획

- **22건** = 11 파트너 × 2 flow. US-005 `send_inquiries.plan_flows()` 를 import 해서 완전히 동일한 (partner, date, product, qty) 사용 → `mail.mail` ↔ `crm.lead` ↔ `sale.order` 가 1:1 자동 정렬.
- `order_line` 은 플로우당 **1 line** (PRD AC "1~3개" 범위의 최소 — 데모 단순화).
- `product_uom_qty`: **US-005/006 에서 결정된 qty 를 재사용** (QUANTITY_POOL=(2,3,5,10,20,50)).
  - PRD US-007 AC 의 "수량 패턴 1,2,3,5,10,20 가중치 랜덤" 과 풀이 약간 다름. 체인 정합성(`lead.expected_revenue == qty × list_price == SO.amount_untaxed`) 우선 → PRD AC "CRM lead.expected_revenue를 amount_total로 업데이트" 로 최종 일관성 확보. US-011 통합 스크립트에서 pool 단일화 여부 재논의.
- `date_order`: `lead.date_open` (planned_date + 09:00:00) 에 `(flow_idx % 3)` 일 추가 → 같은 날(0) / +1일 / +2일 자연 분포.
- `price_unit`: product.list_price 그대로.
- `origin = "CRM Lead #<lead_id>"`, `client_order_ref = "문의 #<mail.mail id>"` 로 역추적 문서.

### 2-1. Idempotency

- 마커: `<!-- ralph-demo-flow id=greenpr:so:<partner_id>:<planned_date> -->` (US-005 `:`, US-006 `:lead:` 과 대응하는 `:so:` 네임스페이스).
- 저장 필드: `sale.order.note`.
- 검증: `sale.order.search([['note','like', marker]])` → 존재하면 skip, 없으면 create.
- lead marker 로도 역 lookup 가능: `crm.lead.search([['description','like', lead_marker]])` → lead_id → `sale.order.search([['opportunity_id','=',lead_id]])` 보조 fallback.

### 2-2. 확정 후 정합 맞추기 (PRD US-007 AC — "CRM lead.expected_revenue를 amount_total로 업데이트")

- `action_confirm` 호출 → `sale.order.state='sale'`.
- 이후 `read(['amount_total'])` → `crm.lead.write({'expected_revenue': amount_total})`.
- `amount_total = amount_untaxed × 1.1` (10% 세금 있는 제품) 또는 `amount_untaxed × 1.0` (세금 없는 제품: POP id=92, 생분해현수 id=241/256). lead.expected_revenue 는 기존에 `qty × list_price = amount_untaxed` 였으므로, 업데이트 후엔 세금 포함 금액으로 바뀐다.

## 3. `action_confirm` 호출 프리컨디션 — Studio 필드 패치

### 증상

Odoo Studio 로 추가된 `stock.move.x_studio_monetary_field_9fa_1jkcl88h2` ("합계", ir.model.fields id=27312) 의 compute 코드가
존재하지 않는 `x_studio_subtotal` 필드에 write 시도 → 모든 `env.flush_all()` 에서 `KeyError: 'x_studio_subtotal'` 발생.
`sale.order.action_confirm` 이 stock.move 를 만들 때 compute 가 돌아 실패.

기존 sale.order 100, 101, 102 가 전부 `state='draft'` 인 것도 이 Studio 버그 때문 (어떤 confirm 도 성공한 적 없음).

### 조치

`customers/greenpr/scripts/patch_studio_field_stock_move.py` 실행 시 한 번만 하는 패치:
compute 를 "자기 자신에 결과 대입" 으로 교체. 원래 사용자 의도에도 부합.

```python
# 원본 (깨진):
record.update({'x_studio_subtotal': price * qty})
# 교체 (동작):
record['x_studio_monetary_field_9fa_1jkcl88h2'] = price * qty
```

`ir.model.fields` id=27312 에 대한 1회성 `write` — 기존 값 백업은 §5 에 원문 보존. 복원 필요 시 XML-RPC 로 원본 문자열 restore.

### 검증

패치 후 즉시 `sale.order` 생성 → `action_confirm` → state='sale', 정상 확정 확인 (2026-04-16 테스트 SO id=104, amount_total=7,920 / amount_untaxed=7,200).

## 4. 실행

```bash
# 호스트 (게이트웨이 경유)
ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/create_sale_orders.py --dry-run
ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/create_sale_orders.py

# 또는 컨테이너 내부
docker cp customers/greenpr/scripts/ ycerp-web-greenpr:/tmp/
docker exec ycerp-web-greenpr python3 /tmp/scripts/create_sale_orders.py
```

인자:

- `--dry-run`: 계획만 출력, 생성 없음.
- `--limit N`: 앞 N 건만 처리.
- `--skip-confirm`: `action_confirm` 생략 (디버그).
- `--skip-lead-write`: `crm.lead.expected_revenue` 업데이트 생략.

## 5. 검증 쿼리

```sql
-- 본 PRD 의 sale.order 만 조회
SELECT id, name, partner_id, state, amount_total, opportunity_id, date_order
FROM sale_order
WHERE note LIKE '%ralph-demo-flow id=greenpr:so:%'
ORDER BY date_order;

-- 파트너별 카운트 (각 2건 기대)
SELECT partner_id, COUNT(*)
FROM sale_order
WHERE note LIKE '%ralph-demo-flow id=greenpr:so:%'
GROUP BY partner_id ORDER BY partner_id;

-- lead ↔ SO 1:1 매칭 검증
SELECT l.id AS lead_id, l.partner_id, l.expected_revenue AS lead_rev,
       so.id AS so_id, so.amount_total AS so_total, so.state
FROM crm_lead l
LEFT JOIN sale_order so ON so.opportunity_id = l.id
WHERE l.description LIKE '%ralph-demo-flow id=greenpr:lead:%'
ORDER BY l.id;
```

## 6. 원본 Studio compute 코드 (복원용)

```
for record in self:
    # 1. 사용자가 입력한 '단가' 가져오기 (알려주신 필드명 적용)
    price = record.x_studio_integer_field_522_1jkclbjbc or 0

    # 2. Odoo 기본 '수량(수요)' 필드 가져오기
    qty = record.product_uom_qty or 0.0

    # 3. 합계 계산 (현재 클릭한 '합계' 필드에 결과값 넣기)
    # 만약 '합계' 필드명이 x_studio_subtotal 이라면 아래처럼 작동합니다.
    # self._fields.get()을 사용해 안전하게 필드명을 찾아 값을 넣습니다.
    record.update({
        'x_studio_subtotal': price * qty
    })
```

## 7. 후속 단계 연계 메모

- **US-008 invoice**: `sale.order._create_invoices()` 호출 → `account.move`. SO state='sale' 필수 (본 스토리에서 충족).
- **US-009 purchase**: 본 스토리와 독립. 단, 같은 (partner, product, qty) 쌍을 `supplier_rank>0` 파트너에 대해 다시 사용. SO 가 `amount_untaxed` 기준 견적 단가의 60~70% 로 발주 단가 계산 — US-009 에서 SO id lookup 필요.
- **US-010 검증**: `amount_total(SO) == amount_total(Invoice)`, `qty(SO line) == qty(PO line)`, `amount_untaxed(PO) ≈ amount_untaxed(SO) × (0.6~0.7)`.
