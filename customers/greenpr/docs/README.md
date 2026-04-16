# greenpr — 데모 플로우 데이터 생성 가이드

greenpr Odoo 19 EE 테넌트에 **문의 → CRM 영업건 → 견적 → 청구 → 매입 발주** 5단계 전체 플로우의
재현 가능한 데모 데이터를 생성하기 위한 문서/스크립트 모음.

`최근 1개월(2026-03-17~2026-04-16) 거래 파트너 11명 × 2건 = 22 flow` 를 결정적·idempotent
방식으로 생성한다. **모든 데이터 입력은 Odoo XML-RPC API 경유** (DB 직접 INSERT 금지). 단,
chronology backfill (`create_date`/`date_order`) 은 magic column 특성상 SQL UPDATE 1회 사용
— 항상 방금 만든 id 화이트리스트만 대상.

---

## 1. 문서 인덱스

| # | 파일 | 내용 | 산출 시점 |
|---|------|------|-----------|
| 0 | [00-environment.md](00-environment.md) | Odoo 버전 · 모듈 · DB · RPC · 백업 | US-001 |
| 0a | [target-partners.md](target-partners.md) / [.json](target-partners.json) | 대상 파트너 11명 + 2건 분포 | US-002 |
| 0b | [generation-plan.md](generation-plan.md) | 14영업일 × 파트너 매트릭스 | US-002 |
| 0c | [products.md](products.md) / [.json](products.json) | 제품 풀 (172건 중 샘플 + 최근 1개월 Top9) | US-003 |
| 1 | [01-inquiry.md](01-inquiry.md) | mail.mail 생성 (방식 C 채택 이유) | US-005 |
| 2 | [02-crm-lead.md](02-crm-lead.md) | crm.lead 생성 + create_date backfill | US-006 |
| 3 | [03-sale-order.md](03-sale-order.md) | sale.order + line + Studio 패치 | US-007 |
| 4 | [04-invoice.md](04-invoice.md) | account.move + 위저드 우회 + Fault 1 swallow | US-008 |
| 5 | [05-purchase-order.md](05-purchase-order.md) | purchase.order + 벤더 풀 + 단가 비율 | US-009 |
| 9 | [99-verification.md](99-verification.md) / [.json](99-verification.json) | **자동 정합성 검증 (이 파일이 게이트)** | US-010 |
| log | inquiry-log.md / lead-log.md / so-log.md / invoice-log.md / po-log.md | 단계별 실행 이력 (append-only) | US-005~009 |

---

## 2. 스크립트 인덱스

개별 스테이지 스크립트는 `customers/greenpr/scripts/` 안. **stdlib 만** 사용 (pip 금지). 각
스크립트는 단일 스토리에 1:1 대응.

| 스크립트 | 역할 | 주요 옵션 |
|----------|------|-----------|
| `odoo_client.py` | XML-RPC OdooClient 헬퍼 | (라이브러리) |
| `test_connection.py` | 연결 스모크 테스트 | - |
| `send_inquiries.py` | US-005 mail.mail 22건 | `--dry-run --limit N` |
| `create_leads.py` | US-006 crm.lead 22건 | `--dry-run --limit N --skip-backfill` |
| `create_sale_orders.py` | US-007 sale.order 22건 + confirm | `--dry-run --skip-confirm --skip-lead-write --skip-backfill` |
| `create_invoices.py` | US-008 account.move 22건 + post | `--dry-run --skip-post --skip-narration` |
| `create_purchase_orders.py` | US-009 purchase.order 22건 + confirm | `--dry-run --skip-confirm` |
| `verify_flow.py` | **US-010 정합성 검증 (264 체크)** | `--no-write --tolerance T` |

통합 오케스트레이터는 repo 루트 `sse/scripts/` 에 있음 — 테넌트만 바꿔 위 5개를 subprocess 로
순차 호출:

| 스크립트 | 역할 | 주요 옵션 |
|----------|------|-----------|
| `sse/scripts/generate-full-flow.py` | **US-011** 5단계 오케스트레이션 + execution-log | `--tenant --dry-run --days-back --flows-per-partner --only --start-from --stop-on-error` |

```bash
# greenpr 전체 플로우 dry-run
python3 scripts/generate-full-flow.py --tenant greenpr --dry-run
# live (idempotent; 이미 생성된 레코드는 전부 skip)
python3 scripts/generate-full-flow.py --tenant greenpr
# 특정 스테이지만 (예: 청구서만 재시도)
python3 scripts/generate-full-flow.py --tenant greenpr --only invoice
```

실행 (호스트 게이트웨이 경유):
```bash
ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/<script>.py
```

또는 web 컨테이너 내부:
```bash
docker cp customers/greenpr/scripts/ ycerp-web-greenpr:/tmp/
docker exec ycerp-web-greenpr python3 /tmp/scripts/<script>.py
```

---

## 3. 5단계 체인 + idempotency marker

각 레코드의 free-text 필드에 `<!-- ralph-demo-flow id=greenpr:<step>:<partner_id>:<planned_date> -->`
HTML 주석을 박는다. 재실행 시 `search([[field, like, marker]])` 로 idempotent 처리.

| 단계 | 모델 | marker namespace | marker 저장 필드 |
|------|------|------------------|------------------|
| 문의 | `mail.mail` | `(빈 step)` | `body_html` |
| 영업건 | `crm.lead` | `lead` | `description` |
| 견적 | `sale.order` | `so` | `note` |
| 청구 | `account.move` | `inv` | `narration` |
| 발주 | `purchase.order` | `po` | `note` |

흐름은 결정적: `send_inquiries.plan_flows()` 이 `(partner_id, planned_date)` 순서대로 22 flow 를
생성 → 모든 후속 스크립트가 동일한 함수를 import 해 같은 product_id/qty 사용. 그래서:

```
mail.mail 384..405  ↔  crm.lead 87..108  ↔  sale.order 105..126
                                          ↔  account.move 98..119  (out_invoice)
                                          ↔  purchase.order 35..56
```

---

## 4. 실행 순서 (전체 재구성)

```bash
cd /home/yc/projects/sse

# 1. 환경 확인 (US-001)
docker ps --filter "name=ycerp-.*-greenpr"
ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/test_connection.py

# 2. 데이터 입력 (US-005 ~ US-009, 순서 중요)
ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/send_inquiries.py
ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/create_leads.py
ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/create_sale_orders.py
ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/create_invoices.py
ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/create_purchase_orders.py

# 3. 정합성 검증 (US-010)
ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/verify_flow.py
# → docs/99-verification.md, .json 자동 갱신
# → exit code 0 = 전부 통과, 1 = 실패 1개 이상
```

각 스크립트는 idempotent 라 여러 번 돌려도 안전 (skip 카운트가 늘어남).

---

## 5. 다른 테넌트 적용 가이드

본 자동화를 `mediapolytech / visualoft / jnj_i / freeworks` 등 다른 테넌트에 적용할 때
**반드시 재확인** 해야 할 항목.

### 5.1 환경 (US-001)
- DB/Web 컨테이너 이름: `ycerp-{db|web}-<tenant>`
- 게이트웨이 포트: greenpr=30033, mediapolytech=30043, visualoft=30053, jnj_i=30063, freeworks=30073
- `customers/<tenant>/full_db_backup.sql` 존재 여부 확인. 없으면 먼저 생성
- Odoo 버전/모듈 동일 가정 검증 — 특히 `sale, purchase, account, crm, mail, website` 설치 확인

### 5.2 파트너 풀 (US-002)
- `sale.order.date_order >= today - 30d` 쿼리는 그대로 재사용 가능
- 윈도우(다음 거래까지 가용 일수) 가 0 이하인 파트너 fallback 로직(7일 역산) 그대로 유효
- `target-partners.json` 만 재생성하면 후속 스크립트는 자동 재사용

### 5.3 제품 풀 (US-003)
- `product.product` 의 `sale_ok` ≠ `purchase_ok` 가능성 — 다른 테넌트에선 별도 풀 필요할 수 있음 (greenpr 은 172=172)
- `default_code` 가 비어있으면 id 기반 식별로 표준화
- `recent_top_products` 가 9개 미만이면 sample fallback (이미 `load_products` 에 분기 존재)

### 5.4 제3자 패치 (US-007 Studio 버그)
- greenpr 한정: `stock.move.x_studio_monetary_field_9fa_1jkcl88h2` (ir.model.fields id=27312) compute KeyError 패치 필요
- 다른 테넌트는 다음 쿼리로 선제 점검:
  ```sql
  SELECT id, name, model, compute FROM ir_model_fields
   WHERE compute IS NOT NULL AND state='manual';
  ```
- 같은 증상 발견 시 동일 self-assign 패턴으로 패치

### 5.5 메일 / 발신 정책 (US-005)
- 외부 SMTP 실제 발송 회피를 위해 `state='sent'` 수동 마킹 — 모든 테넌트 공통 OK
- internal 수신 주소(`mail_server.smtp_user`) 가 다름 — 테넌트별 적용 시 `INTERNAL_TO` 상수 변경

### 5.6 벤더 풀 (US-009)
- 잡음 이름 필터(`is_company=True + parent_id=False + supplier_rank>0`) 후 풀 크기 확인
- 풀 크기 0 이면 스크립트 abort (PRD AC "벤더 없으면 건너뛰고 기록")
- VENDOR_POOL_FALLBACK 상수를 테넌트별 ID 로 교체

### 5.7 부가세 setup (US-010 §8)
- greenpr 의 sale/purchase 10% TI 가 price_include 정책이 다름 → untax_ratio 가 ~5% 낮아짐
- 다른 테넌트는 `account_tax.price_include_override` 양쪽 통일하면 untax 비율도 일치
- 정합성 1차 기준은 line-level **price_unit 비율** — 항상 통과해야 함

### 5.8 회계 저널 (US-008)
- greenpr 은 sales 저널 1개라 위저드가 자동 선택 → 다른 테넌트는 multi-journal 가능
- 필요 시 `create_invoices.py` 에 `--journal-id` 옵션 추가

---

## 6. 데모 데이터 정리

데모 데이터를 모두 지우려면 (운영 데이터는 유지):

```bash
# WARNING: 검증 후 실행. dry-run 모드 없음 — 즉시 commit
docker exec ycerp-db-greenpr psql -U odoo -d odoo <<'SQL'
BEGIN;
-- PO (cancel → unlink). picking 도 cancel 필요할 수 있음
UPDATE purchase_order SET state='cancel' WHERE note LIKE '%ralph-demo-flow id=greenpr:po:%';
DELETE FROM purchase_order_line WHERE order_id IN (SELECT id FROM purchase_order WHERE note LIKE '%ralph-demo-flow id=greenpr:po:%');
DELETE FROM purchase_order WHERE note LIKE '%ralph-demo-flow id=greenpr:po:%';
-- invoice (posted 는 cancel 만 가능 → cancel 후 그대로 둠 / 또는 reverse)
UPDATE account_move SET state='cancel' WHERE narration LIKE '%ralph-demo-flow id=greenpr:inv:%';
-- SO (테스트에서 unlink 가능 확인됨, 단 stock.picking 자동 cancel 필요)
DELETE FROM sale_order_line WHERE order_id IN (SELECT id FROM sale_order WHERE note LIKE '%ralph-demo-flow id=greenpr:so:%');
DELETE FROM sale_order WHERE note LIKE '%ralph-demo-flow id=greenpr:so:%';
-- lead
DELETE FROM crm_lead WHERE description LIKE '%ralph-demo-flow id=greenpr:lead:%';
-- mail.mail (res_id 세팅돼있어 안전)
DELETE FROM mail_mail WHERE body_html LIKE '%ralph-demo-flow id=greenpr:%' AND body_html NOT LIKE '%greenpr:lead:%' AND body_html NOT LIKE '%greenpr:so:%' AND body_html NOT LIKE '%greenpr:inv:%' AND body_html NOT LIKE '%greenpr:po:%';
COMMIT;
SQL
```

`account.move` 는 posted 상태라 unlink 불가 → cancel 만. 깔끔히 지우려면 reverse 후 양쪽 cancel.

---

## 7. CI/게이트 활용

`scripts/verify_flow.py` 는 exit code 로 게이트 가능:

```bash
ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/verify_flow.py
echo "exit=$?"   # 0=PASS, 1=FAIL
```

JSON 사이드카(`docs/99-verification.json`) 에 `summary.failed_checks` 가 있어 별도 파서가
필요 없다.
