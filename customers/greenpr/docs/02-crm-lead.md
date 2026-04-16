# US-006 — CRM 신규 영업건(Lead) 생성

전체 플로우 2단계: 문의(`mail.mail`, US-005) → **CRM 영업건(`crm.lead`, US-006)**.
파트너당 2건씩 총 22건의 `crm.lead`(type='opportunity') 를 생성한다.

## 1. greenpr 환경 조사

XML-RPC `crm.lead.fields_get` + `crm.stage / crm.team / res.users.search_read` 결과 (2026-04-16 기준).

### 1-1. 사용 필드 (생성 시 입력)

| 필드 | type | 필수 | 사용 값/소스 |
|---|---|---|---|
| `name` | char | ✓ | `f"[문의] {product_name} 견적 - {partner_name}"` (US-005 inquiry 와 동일 product/partner) |
| `type` | selection | ✓ | `'opportunity'` (lead 가 아닌 영업기회) |
| `partner_id` | many2one→res.partner | – | `target-partners.json` 의 partner_id |
| `partner_name` | char | – | partner.name (회사명 표시용 보조) |
| `email_from` | char | – | partner.email or `inquiry-noreply@greenpr.local` (US-005 와 동일 fallback) |
| `phone` | char | – | partner.phone or null |
| `contact_name` | char | – | null (대부분 회사 단위 영업) |
| `stage_id` | many2one→crm.stage | – | **1 = "New"** (sequence=0, 초기 단계) |
| `user_id` | many2one→res.users | – | **2 = admin (green PR)** (기존 lead 전부 동일) |
| `team_id` | many2one→crm.team | – | **1 = Sales** (기존 lead 전부 동일) |
| `expected_revenue` | monetary | – | `qty × product.list_price` (US-007 견적 amount_total 과 일치 시킬 예정) |
| `date_open` | datetime | – | `planned_date` 09:00:00 (US-002 계획 분포) |
| `date_deadline` | date | – | `planned_date + 14일` (자연스러운 마감) |
| `description` | html | – | 문의 본문 요약 + idempotent marker(주석) + 연결된 `mail.mail` id |
| `priority` | selection | – | 미설정(기본 `'0'`) |

### 1-2. 읽기/계산 필드 (입력 안 함)

- `probability`: stage 변경/AI 자동 산정. 직접 안 건드림 (테스트에서 stage_id=1 만 줘도 ~99.5% 자동 산정 확인됨 — Odoo 19 EE의 lead scoring AI).
- `create_date`: **XML-RPC `create` 가 vals 의 create_date 를 무시**(Odoo BaseModel.create 가 magic column 자동 set). → 후처리 SQL UPDATE 로 backfill (아래 §3 참고).

### 1-3. 마스터 데이터 스냅샷 (greenpr, 2026-04-16)

```text
crm.stage (5건):
  1 New          (sequence=0, is_won=false, fold=false)   ← 초기 단계
  2 Qualified    (sequence=1)
  3 Proposition  (sequence=2)
  4 Won          (sequence=3, is_won=true)
  5 보류         (sequence=4)

crm.team (2건):
  1 Sales        (user_id=2 green PR)   ← 사용
  2 Website      (user_id=2 green PR)

res.users (active=true, 5건):
  2  admin                       (green PR)   ← user_id 사용
  6  ysmoon@ycgroup.co.kr        (문영식)
  8  differentg021@gmail.com    (김고객)
  10 yc.kimhyunggi@gmail.com    (김홍도)
  11 najy@naver.com             (나주연)

기존 crm.lead: 36건 (opportunity 34, lead 2). 전부 user_id=2/team_id=1.
```

## 2. 생성 계획

- **22건** = 11 파트너 × 2 flow (US-002 `target-partners.json.target_partners`).
- 파트너·날짜·제품·수량은 **US-005 `send_inquiries.py.plan_flows()` 와 동일** 함수를 import 해서 동일 시드(`SEED=20260416`)로 재현 — 문의 ↔ 영업건 매핑이 자동으로 1:1 일관.
- `expected_revenue` = `qty × product.list_price`. product.list_price 는 `product.product.read([id], fields=['list_price'])` 로 런타임 조회 후 메모리 캐시.
- `description` 본문에 연결 정보 명시:
  - 문의 mail.mail id (search 로 lookup, 못 찾으면 빈 값 — fail soft)
  - 제품 id/name/qty
  - 희망 납기일 (US-005 본문과 같은 offset)

### 2-1. Idempotency

- 마커: `<!-- ralph-demo-flow id=greenpr:lead:<partner_id>:<planned_date> -->` (US-005 와 다른 `:lead:` 네임스페이스).
- 검증: `crm.lead.search([['description','like', marker]])` 로 존재 확인 → 있으면 skip, 없으면 create.
- US-005 마커 스킴 재사용 → 다른 단계(US-007 SO `:so:`, US-008 invoice `:inv:`, US-009 PO `:po:`)도 동일 패턴 확장 가능.

### 2-2. 사용자/사업부 정책

- `user_id=2` (admin), `team_id=1` (Sales) 단일 — 다른 활성 사용자(8, 10, 11, 6)에 분산할 수도 있으나 데모 단순화 우선.
- 후속에서 분산 필요해지면 `user_id = (partner_id + flow_idx) % 5` 식으로 분배 (raw seed 함수만 추가하면 됨).

## 3. create_date Backfill 처리

### 왜 SQL UPDATE 가 필요한가

XML-RPC 로 `create_date` 를 vals 에 넣어도 Odoo BaseModel 이 commit 직후 `now()` 로 덮어쓴다 (probe 실측 — `2026-04-01 09:00:00` 입력 → `2026-04-16 10:55:54` 저장). PRD AC "create_date는 US-002 날짜 계획에 맞춤" 요구사항 충족을 위해 **생성 직후 새로 만든 id 만 대상으로 UPDATE 1회** 수행.

### 정책

- 대상: 본 스크립트가 **방금 create 한 id 목록**만. 기존 레코드 절대 안 건드림.
- 컬럼: `create_date` (UTC, "YYYY-MM-DD HH:MM:SS"). `date_open` 도 같은 시각으로 통일.
- 시각: planned_date + 09:00:00 (KST = UTC+9 → DB 에는 UTC 기준 `00:00:00` 로 환산. 단, 다른 Odoo 레코드들과 톤이 맞도록 단순히 `09:00:00` UTC 로 저장 → KST 18:00 표시. 파트너별 문의 분포가 다른 시각으로 보여 자연스럽다).
- 안전망: SQL 은 `id IN (...)` 화이트리스트만 사용. 절대 도메인/조건문 없음.
- 실행 방법: `docker exec ycerp-db-greenpr psql -U odoo -d odoo -c "UPDATE crm_lead SET create_date='...', write_date='...', date_open='...' WHERE id = ANY(ARRAY[...]::int[])"`.

### 실행 후 검증

```sql
SELECT id, create_date, date_open, name FROM crm_lead WHERE id = ANY(ARRAY[...]::int[]) ORDER BY create_date;
```

## 4. 실행

```bash
# 호스트에서 (게이트웨이 경유)
ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/create_leads.py --dry-run
ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/create_leads.py

# 또는 컨테이너 내부
docker cp customers/greenpr/scripts/create_leads.py ycerp-web-greenpr:/tmp/
docker exec ycerp-web-greenpr python3 /tmp/create_leads.py
```

## 5. 검증 쿼리 (참고)

```sql
-- 본 PRD 의 lead 만 조회 (description 마커 기반)
SELECT id, partner_id, name, expected_revenue, date_open, create_date
FROM crm_lead
WHERE description LIKE '%ralph-demo-flow id=greenpr:lead:%'
ORDER BY date_open;

-- 파트너별 카운트 (각 2건 기대)
SELECT partner_id, COUNT(*)
FROM crm_lead
WHERE description LIKE '%ralph-demo-flow id=greenpr:lead:%'
GROUP BY partner_id ORDER BY partner_id;
```

## 6. 후속 단계 연계 메모

- **US-007 sale.order**: `opportunity_id = lead.id`, `partner_id = lead.partner_id`, `order_line.product_id/qty` = 본 스크립트가 사용한 (product_id, qty). lead `expected_revenue` 는 SO 확정 후 `amount_total` 로 재 write.
- **US-008 invoice**: `sale.order._create_invoices()` → account.move.
- **US-009 purchase**: 본 스크립트 정보 사용 안 함 (별도 PO 라인 생성). 단, 같은 (product, qty) 사용.
