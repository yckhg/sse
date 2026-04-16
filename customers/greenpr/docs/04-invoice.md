# US-008 — 청구서(Invoice) 생성

전체 플로우 4단계: 문의(US-005) → CRM(US-006) → 견적(US-007) → **청구(US-008 `account.move`)**.
US-007 에서 만든 22 sale.order 각각에 대해 `account.move` (move_type='out_invoice') 1건을 자동 생성하고
`action_post` 로 `state='posted'` 까지 진행한다. 금액은 `sale.order.amount_total == account.move.amount_total` 로 정합 검증.

## 1. greenpr 환경 조사

XML-RPC `account.move.fields_get` + 기존 invoice 샘플 조회 결과 (2026-04-16 기준).

### 1-1. 사용 필드 (account.move)

| 필드 | type | 필수 | 사용 값/소스 |
|---|---|---|---|
| `move_type` | selection | ✓ | `'out_invoice'` (고객 청구서) |
| `partner_id` | many2one→res.partner | – | **wizard 가 자동 채움** (= SO `partner_invoice_id`) |
| `journal_id` | many2one→account.journal | ✓ | **9 = Sales** (greenpr 유일한 sale 저널). wizard 자동 |
| `invoice_origin` | char | – | **wizard 자동** = SO name (예: `S00105`) |
| `invoice_user_id` | many2one→res.users | – | wizard 자동 = SO `user_id` (= 2 admin) |
| `team_id` | many2one→crm.team | – | wizard 자동 = SO `team_id` (= 1 Sales) |
| `currency_id` | many2one→res.currency | ✓ | wizard 자동 = company KRW (id=32) |
| `invoice_date` | date | – | **본 스크립트가 write** = SO `date_order` + `{1,2,3}` 일 |
| `date` | date | ✓ | 회계 인식 날짜. invoice_date 와 동일 값 |
| `ref` | char | – | `"SO #<so_id>"` (역추적) |
| `narration` | html | – | idempotent marker + 연결 정보 주석 |
| `invoice_line_ids` | one2many→account.move.line | – | **wizard 자동 생성** (SO 라인 1:1 복사, sale_line_ids 연결) |
| `state` | selection | – | create 직후 `'draft'`, `action_post` 후 `'posted'` |
| `amount_total` | monetary | – | 라인 자동 계산 = `SO.amount_total` |

### 1-2. 기존 데이터 스냅샷 (greenpr, 2026-04-16)

```text
account.journal id=9  Sales      type=sale       code=INV
account.journal id=10 Purchases  type=purchase   code=BILL
account.move    move_type='out_invoice' = 44 건 (US-008 시작 전).
                state 분포: posted 다수, cancel 일부, draft 0
account.move 시퀀스: name = INV/<YYYY>/<NNNNN> (예: INV/2026/00044)
```

### 1-3. partner_id 의 자동 변환

SO `partner_id` 와 invoice `partner_id` 가 다를 수 있다.

- 예: `sale.order 116 (WJ바이오)`
  - `partner_id = 594` (회사, type='contact')
  - `partner_invoice_id = 664` (자식 contact, type='invoice')
- `_create_invoices()` 가 자동으로 `invoice.partner_id = SO.partner_invoice_id` 로 설정.
  → invoice partner = 664. 정상 동작.

다른 테넌트에서도 invoice/shipping contact 가 분리돼 있을 수 있으니 **invoice.partner_id 비교 시
`SO.partner_invoice_id` 와만 비교**할 것 (SO.partner_id 와 비교하면 mismatch 가짜 신호).

## 2. 생성 계획

### 2-1. 호출 방식

PRD US-008 AC 는 **`sale.order._create_invoices()` 메서드 호출 (수동 create 금지)**. 그러나 Odoo 19 에서
`_create_invoices` 는 **private** (XML-RPC remote call 차단: `Fault 4: Private methods cannot be called remotely`).
공식적으로 외부에서 호출 가능한 진입점은 **`sale.advance.payment.inv` 위저드의 `create_invoices()`** (이 위저드가
내부적으로 `_create_invoices()` 호출).

따라서 본 스크립트는 위저드 경유:

```python
wiz_id = create('sale.advance.payment.inv', {
    'advance_payment_method': 'delivered',  # SO 라인 전체를 1회 청구
    'sale_order_ids': [(6, 0, [so_id])],
}, context={'active_model': 'sale.order', 'active_ids': [so_id], 'active_id': so_id})
call_method('sale.advance.payment.inv', 'create_invoices', [wiz_id],
            context={'active_model': 'sale.order', 'active_ids': [so_id], 'active_id': so_id})
# ↑ 위저드는 act_window action dict 를 반환하는데, 그 dict 안에 None 값이 있어
#   서버 측 OdooMarshaller(allow_none=False) 가 'cannot marshal None unless allow_none is enabled'
#   Fault 1 을 던짐. 그러나 invoice 생성 side effect 는 이미 완료됨 → 이 Fault 는 swallow.
```

### 2-2. 새 invoice id 회수

위저드 return value 가 못 돌아오므로, **호출 직전에 SO.invoice_ids 를 스냅샷** → 호출 직후 다시 read →
**diff 가 새 invoice id**. 이 패턴이 안전 (호출 도중 다른 invoice 가 생기지 않는다는 가정 — 데모는 단일 사용자라 OK).

### 2-3. 청구일/회계일 (invoice_date / date)

- PRD AC: "invoice_date 는 date_order 와 같거나 1~3일 후"
- 위저드는 invoice_date 를 비워두고 만듦 (post 시 자동 채움 = today). 데모 chronology 를 맞추려면
  **post 전에 직접 write** 해야 함.
- 식: `invoice_date = SO.date_order.date() + ((flow_idx % 3) + 1) days`. flow_idx 별로 +1/+2/+3 일 균등 분포.
- `date` (회계 인식 날짜) 도 동일하게 set — 둘 다 한 번의 `write` 로 처리.

### 2-4. action_post

- 모든 필드 set 후 `account.move.action_post([id])` 호출 → `state='posted'`, `name='INV/YYYY/NNNNN'` 자동 채번.
- post 후엔 `invoice_date`/`date` 가 immutable. 그래서 set 순서가 중요 (write → post).

### 2-5. Idempotency

- 마커: `<!-- ralph-demo-flow id=greenpr:inv:<partner_id>:<planned_date> -->`
  - `partner_id` 는 **SO.partner_id (= flow.partner_id)** 사용 — flow 식별 키 일관성. invoice.partner_id (=invoice contact) 와 다를 수 있음에 주의.
- 저장 필드: `account.move.narration` (html, write 가능).
- 검증: `account.move.search([['narration','like', marker]])` → 존재하면 skip.
- **부가 idempotency**: SO.invoice_ids 가 이미 비-cancel invoice 를 보유한 경우도 skip (위저드가 두 번 호출되면
  `_create_invoices` 가 'No invoiceable lines' 로 에러). 이때 narration 에 marker 가 없으면 marker 만 backfill.

### 2-6. 금액 정합성 검증

- `account.move.amount_total == sale.order.amount_total` — 위저드가 SO 라인 1:1 복사하므로 자동 일치.
- post 후 `read(['amount_total'])` 로 다시 읽어서 SO 와 비교. 22/22 일치 기대.

## 3. 실행

```bash
# 호스트 (게이트웨이 경유)
ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/create_invoices.py --dry-run
ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/create_invoices.py

# 또는 컨테이너 내부
docker cp customers/greenpr/scripts/ ycerp-web-greenpr:/tmp/
docker exec ycerp-web-greenpr python3 /tmp/scripts/create_invoices.py
```

인자:

- `--dry-run`: 계획만 출력, 생성/post 없음.
- `--limit N`: 앞 N 건만 처리.
- `--skip-post`: `action_post` 생략 (디버그). draft 상태로만 생성.
- `--skip-narration`: marker write 생략 (디버그용 — idempotency 깨짐).

## 4. 검증 쿼리

```sql
-- 본 PRD 의 invoice 만 조회
SELECT id, name, partner_id, state, amount_total, invoice_origin, invoice_date, date
FROM account_move
WHERE narration LIKE '%ralph-demo-flow id=greenpr:inv:%'
ORDER BY date, id;

-- SO ↔ invoice 1:1 매칭 + 금액 정합 검증
SELECT so.id AS so_id, so.name AS so_name, so.amount_total AS so_total,
       am.id AS inv_id, am.name AS inv_name, am.amount_total AS inv_total,
       am.state AS inv_state, am.invoice_date,
       (am.amount_total - so.amount_total) AS diff
FROM sale_order so
LEFT JOIN account_move am ON am.invoice_origin = so.name AND am.move_type='out_invoice' AND am.state != 'cancel'
WHERE so.note LIKE '%ralph-demo-flow id=greenpr:so:%'
ORDER BY so.id;

-- 파트너별 카운트 (각 2건 기대 — invoice.partner_id 가 contact 로 분리될 수 있어 SO.partner_id 기준)
SELECT so.partner_id, COUNT(am.id)
FROM sale_order so
LEFT JOIN account_move am ON am.invoice_origin = so.name AND am.move_type='out_invoice' AND am.state='posted'
WHERE so.note LIKE '%ralph-demo-flow id=greenpr:so:%'
GROUP BY so.partner_id ORDER BY so.partner_id;

-- 날짜 순서 검증: lead.date_open ≤ SO.date_order ≤ invoice.invoice_date
SELECT l.id AS lead_id, l.date_open::date AS lead_date,
       so.id AS so_id, so.date_order::date AS so_date,
       am.id AS inv_id, am.invoice_date AS inv_date
FROM crm_lead l
JOIN sale_order so ON so.opportunity_id = l.id
JOIN account_move am ON am.invoice_origin = so.name AND am.state='posted'
WHERE l.description LIKE '%ralph-demo-flow id=greenpr:lead:%'
ORDER BY l.id;
```

## 5. 후속 단계 연계 메모

- **US-009 purchase**: invoice 와 독립. 단 같은 (partner, product, qty) 를 supplier_rank>0 파트너로 PO 생성.
- **US-010 검증**: amount_total(SO)==amount_total(Invoice) ✓ 본 스토리 자동 검증; PO 정합은 US-009/010 에서.
- **invoice 회수(payment) 단계는 본 PRD 범위 밖** — US-008 은 청구서 발행(post)까지만.
- **payment_state**: post 직후 'not_paid'. 본 스토리는 not_paid 그대로 둠. 결제 시뮬레이션이 필요하면 별도 스토리.
