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

## 4. 스테이지 규약 (Stage Convention)

5개 스테이지 스크립트(`send_inquiries.py`, `create_leads.py`, `create_sale_orders.py`,
`create_invoices.py`, `create_purchase_orders.py`)는 오케스트레이터
(`sse/scripts/generate-full-flow.py`)가 일관된 방식으로 소비할 수 있도록 아래 규약을 따른다.
신규 스테이지 스크립트를 추가하거나 기존 스크립트를 수정할 때 반드시 본 규약을 지켜야 한다.

### 4.1 `[summary]` 출력 의무

live 모드(`--dry-run` 미지정)에서는 종료 직전 반드시 아래 형식의 한 줄을 stdout 에 출력한다.

```
[summary] created=<n> [confirmed=<n> | posted=<n> | backfilled=<n>] skipped=<n> total=<n>
```

- 각 flow 는 반드시 어느 한 버킷에 카운트되어야 한다 — `created + (confirmed|posted|backfilled
  에 포함되지 않은) skipped` 합산이 `total` 과 맞아야 한다. 조용히 `continue` 하는 분기가
  있다면 해당 flow 를 `skipped` 로 카운트한다 ("silent continue" 금지).
- dry-run 모드는 의도적으로 `[summary]` 를 생략한다(plan 출력만). 오케스트레이터는 이
  부재를 무시한다(US-004 가드).
- live 모드에서 `[summary]` 가 누락되면 오케스트레이터가 stderr 에
  `WARN: stage <name> completed rc=0 but no [summary] line emitted` 를 출력하며,
  `--strict-summary` 결합 시 해당 스테이지를 실패로 취급한다.

### 4.2 rc 기준표

| rc | 의미 | 예시 |
|----|------|------|
| 0 | 성공(작업량 0건·빈 풀 케이스 포함) | 정상 종료, 빈 vendor pool, limit=0 |
| 1 | 복구 불가 실패 | RPC 인증 실패, 위저드 create 실패, SQL 백필 실패 |
| 2 | 입력 오류 | argparse 검증 실패(`container_name_arg`), 필수 json 파일 부재 |

`argparse.ArgumentTypeError` / `SystemExit(2)` 는 argparse 가 자동 처리하므로 별도 분기 불요.
복구 불가 실패는 stderr 에 `[ERR] ...` 로 사유 기록 후 rc=1 로 종료.

### 4.3 빈 풀(empty pool) 처리

"빈 풀" = 대상 목록이 0건(예: vendor pool 0건, partner pool 0건, flows 0건). 이 경우:

1. stderr 에 `[WARN] <pool> empty — 0 work` 형식으로 경고 출력.
2. stdout 에 `[summary] created=0 ... skipped=<total> total=<total>` 출력(total=0 포함 가능).
3. rc=0 으로 종료.

**rc=2 를 던지지 말 것** — rc=2 는 "입력 오류" 이며 빈 풀은 정상적으로 발생 가능한 런타임
상태다. 오케스트레이터의 `--stop-on-error` 와 `--strict-summary` 둘 다 이 케이스를 실패로
간주하지 않아야 한다.

---

## 5. 실행 순서 (전체 재구성)

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

## 5a. Website `/contactus` 폼 자동화 스모크 테스트 (US-006)

`greenpr_form_automation` 모듈이 설치된 상태에서 **실제 `/contactus` 폼 POST →
`crm.lead` 생성 → `base.automation` 트리거 → `mail.template` 렌더 → `mail.mail`
대기열 적재** 의 전체 체인을 한 번에 검증하는 E2E 스모크 테스트.

```bash
cd /home/yc/projects/sse

# 기본 실행 (호스트 게이트웨이 경유, 자동 cleanup)
ODOO_URL=http://localhost:30033 \
    python3 customers/greenpr/scripts/smoke_test_form_automation.py

# 생성한 레코드를 남겨두고 수동 확인하고 싶을 때
ODOO_URL=http://localhost:30033 \
    python3 customers/greenpr/scripts/smoke_test_form_automation.py --no-cleanup
```

동작:

1. `SMOKE-<epoch_ms>` 마커를 생성.
2. `POST /website/form/crm.lead` 를 stdlib `urllib` 로 호출. payload 의
   `name`/`description` 에 마커를 심는다.
3. 최대 `--wait-seconds` (기본 10s) 동안 폴링하여:
   - `crm.lead` 생성 및 `medium_id.name == 'Website'` 여부
   - 해당 lead 에 연결된 `mail.mail` 중 `body_html` 에 "견적 문의" 리터럴을
     포함하는 레코드의 `state ∈ {'sent','outgoing'}` 여부
   확인.
4. 생성한 `mail.mail` + `crm.lead` 를 마커로 재검색 후 자동 삭제
   (`mail.message` 는 Odoo 보안 룰로 admin 도 지울 수 없어 WARN 후 skip —
   해당 메시지는 삭제된 lead 의 고아 row 로 남지만 UI 에서는 보이지 않음).

exit code: `0` = 전 체인 통과, `1` = 어떤 단계든 실패.

스모크 테스트는 idempotent 하며 실행 시작 시 `SMOKE-*` 마커가 붙은 과거 잔재물을
자동 purge 한다 (`--no-purge-stale` 로 해제 가능).

---

## 6. 다른 테넌트 적용 가이드

본 자동화를 `mediapolytech / visualoft / jnj_i / freeworks` 등 다른 테넌트에 적용할 때
**반드시 재확인** 해야 할 항목.

### 6.1 환경 (US-001)
- DB/Web 컨테이너 이름: `ycerp-{db|web}-<tenant>`
- 게이트웨이 포트: greenpr=30033, mediapolytech=30043, visualoft=30053, jnj_i=30063, freeworks=30073
- `customers/<tenant>/full_db_backup.sql` 존재 여부 확인. 없으면 먼저 생성
- Odoo 버전/모듈 동일 가정 검증 — 특히 `sale, purchase, account, crm, mail, website` 설치 확인

### 6.2 파트너 풀 (US-002)
- `sale.order.date_order >= today - 30d` 쿼리는 그대로 재사용 가능
- 윈도우(다음 거래까지 가용 일수) 가 0 이하인 파트너 fallback 로직(7일 역산) 그대로 유효
- `target-partners.json` 만 재생성하면 후속 스크립트는 자동 재사용

### 6.3 제품 풀 (US-003)
- `product.product` 의 `sale_ok` ≠ `purchase_ok` 가능성 — 다른 테넌트에선 별도 풀 필요할 수 있음 (greenpr 은 172=172)
- `default_code` 가 비어있으면 id 기반 식별로 표준화
- `recent_top_products` 가 9개 미만이면 sample fallback (이미 `load_products` 에 분기 존재)

### 6.4 제3자 패치 (US-007 Studio 버그)
- greenpr 한정: `stock.move.x_studio_monetary_field_9fa_1jkcl88h2` (ir.model.fields id=27312) compute KeyError 패치 필요
- 다른 테넌트는 다음 쿼리로 선제 점검:
  ```sql
  SELECT id, name, model, compute FROM ir_model_fields
   WHERE compute IS NOT NULL AND state='manual';
  ```
- 같은 증상 발견 시 동일 self-assign 패턴으로 패치

### 6.5 메일 / 발신 정책 (US-005)
- 외부 SMTP 실제 발송 회피를 위해 `state='sent'` 수동 마킹 — 모든 테넌트 공통 OK
- internal 수신 주소(`mail_server.smtp_user`) 가 다름 — 테넌트별 적용 시 `INTERNAL_TO` 상수 변경

### 6.6 벤더 풀 (US-009)
- 잡음 이름 필터(`is_company=True + parent_id=False + supplier_rank>0`) 후 풀 크기 확인
- 풀 크기 0 이면 §4.3 "빈 풀 처리 규약" 에 따라 WARN + rc=0 + `[summary] ... skipped=<total>`
  — 오케스트레이터는 스테이지 실패로 간주하지 않음
- VENDOR_POOL_FALLBACK 상수를 테넌트별 ID 로 교체

### 6.7 부가세 setup (US-010 §8)
- greenpr 의 sale/purchase 10% TI 가 price_include 정책이 다름 → untax_ratio 가 ~5% 낮아짐
- 다른 테넌트는 `account_tax.price_include_override` 양쪽 통일하면 untax 비율도 일치
- 정합성 1차 기준은 line-level **price_unit 비율** — 항상 통과해야 함

### 6.8 회계 저널 (US-008)
- greenpr 은 sales 저널 1개라 위저드가 자동 선택 → 다른 테넌트는 multi-journal 가능
- 필요 시 `create_invoices.py` 에 `--journal-id` 옵션 추가

---

## 7. 데모 데이터 정리

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

## 8. CI/게이트 활용

`scripts/verify_flow.py` 는 exit code 로 게이트 가능:

```bash
ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/verify_flow.py
echo "exit=$?"   # 0=PASS, 1=FAIL
```

JSON 사이드카(`docs/99-verification.json`) 에 `summary.failed_checks` 가 있어 별도 파서가
필요 없다.
