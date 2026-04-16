# 01. Inquiry (문의하기) — 전체 플로우의 시작점

greenpr 테넌트에서 "문의하기 → CRM 영업건 → 견적서 → 청구서 → 매입 발주" 전체 플로우를 생성할 때, 각 플로우의 첫 단계인 **문의 메일 발송**을 어떻게 기록하는지 정리한다.

## 실제 운영 플로우 조사

### 웹사이트 문의 폼

- 페이지: `website.page` id=3 / id=7 (둘 다 `/contactus`) — `website_id` 지정된 쪽(id=7, "GreenPR")이 활성
- 공개 URL: `http://localhost:30033/contactus` (테넌트 도메인 기준 `https://greenpr.online/contactus`)
- 폼 submit 시 호출되는 엔드포인트: `POST /website/form/contactus`
  - Odoo의 `website_crm` 모듈이 `crm.lead` 레코드를 자동 생성
  - 생성된 crm.lead에 mail.template id=58 ("문의하기 제출") 이 연결되어 세일즈 팀에 알림 메일 발송
- 완료 후 리디렉션: `/contactus-thank-you` (id=1) 또는 `/your-task-has-been-submitted` (id=8)

### Mail Template

- **id=58** / name=`문의하기 제출` / model=`crm.lead`
  - subject: `견적문의_{{ object.partner_name or '고객사' }}`
  - 문의 접수 시 영업팀에 발송되는 알림 메일 템플릿
- id=57 / name=`견적문의_${object.contact_name or object.partner_name or '고객명 미상'}` / model=`crm.lead` — 1차 응대 템플릿
- id=53 / name=`견적서1\` / model=`crm.lead` — 견적서 발송 템플릿

### Outgoing Mail Server

| 필드 | 값 |
|------|-----|
| id | 4 |
| name | Gmail SMTP Server |
| smtp_host | smtp.gmail.com |
| smtp_port | 587 |
| smtp_user | greenpr9@gmail.com |
| from_filter | (없음 — 모든 발신자 허용) |
| active | True |

**운영 주체 주소: `greenpr9@gmail.com`** — greenpr 테넌트의 유일한 외부-연결 이메일. 다른 모든 주소(고객 파트너의 @naver.com, @ycgroup.co.kr 등)는 "외부 주소".

## 선택한 방식: `mail.mail` create + state='sent' (실제 송신 없음)

### 선택지 비교

| 방식 | 장점 | 단점 | 채택 여부 |
|------|------|------|-----------|
| **A. `POST /website/form/contactus` 호출** | 가장 실제와 가까움. crm.lead 자동 생성 + 템플릿 메일 자동 발송 | (1) crm.lead가 자동 생성되어 **US-006 범위와 충돌** — US-006이 lead를 직접 제어 생성해야 함. (2) date_open 등 backdate 불가. (3) 게이트웨이 경유 HTTP 스크립팅 비용 | ❌ |
| **B. `mail.mail` create → `.send()` 실제 호출** | 운영 메일 서버를 실제로 거침 | (1) smtp_user=Gmail — 실제 외부 SMTP 발송이 발생. (2) 데모 데이터 22건 × 반복 실행 가능성 → Gmail 계정 발송 한도/스팸 리스크. (3) 수신자(`greenpr9@gmail.com`) 메일함이 데모용 메일로 오염 | ❌ |
| **C. `mail.mail` create + `state='sent'` 수동 세팅 (본 선택)** | 실제 외부 발송 없이 "문의 메일 기록" 아티팩트를 Odoo 안에 남김. 재실행 가능. US-006 이후 단계에 독립. | 실제 전송은 하지 않음 (단, AC "외부 주소로 실제 발송 X" 요구에 부합) | ✅ |

### 채택 이유 요약

1. **AC 명시: "외부 주소로 실제 발송 X, greenpr의 mail_server 설정 내 주소로만"** — greenpr의 mail_server는 Gmail SMTP 하나뿐이며, 그 `smtp_user`(= `greenpr9@gmail.com`)가 유일한 "내부" 주소. 고객 파트너의 이메일(`@naver.com` 등)은 전부 외부. → 실제 `.send()` 호출은 이 정책 안에서도 Gmail 발송을 발생시키므로 배제.
2. **US-006~US-009 스토리 독립성 보존** — 문의가 자동으로 crm.lead를 생성하면 US-006 제어가 불가능.
3. **데모 재실행성** — 스크립트를 여러 번 돌려도 동일한 결과를 보장해야 함 (body 안 stable marker로 idempotent 체크).

### mail.mail 레코드 스키마

| 필드 | 값 |
|------|----|
| `subject` | `[문의] {product_name} 견적 문의 - {partner_name}` |
| `email_from` | partner.email 이 있으면 그 값, 없으면 `inquiry-noreply@greenpr.local` |
| `email_to` | `greenpr9@gmail.com` (greenpr 내부 주소) |
| `reply_to` | partner.email 또는 fallback (US-006 연결 시 사용) |
| `body_html` | 자연스러운 한국어 문의 본문 (파트너명, 제품명, 수량 범위, 납기 희망일, marker 포함) |
| `mail_server_id` | 4 (Gmail SMTP Server) |
| `message_type` | `email` |
| `model` | `res.partner` |
| `res_id` | partner_id |
| `state` | (create 직후 수동으로) `sent` |
| `auto_delete` | `False` (기록 보존) |

### Idempotent Marker

각 `body_html` 끝에 다음 HTML 주석을 삽입한다. 재실행 시 search 로 존재 여부 체크 후 skip.

```html
<!-- ralph-demo-flow id=greenpr:{partner_id}:{planned_date_iso} -->
```

검색 쿼리 예:

```python
cli.search("mail.mail", [["body_html", "like", f"ralph-demo-flow id=greenpr:{partner_id}:{date}"]])
```

## 발송 계획

| | 값 |
|---|---|
| 총 플로우 수 | 22건 (11 파트너 × 2) |
| 날짜 분포 | 2026-03-23 ~ 2026-04-14 영업일 14일에 분산 (US-002 plan) |
| 제품 선정 | `docs/products.json` `recent_top_products` Top 9 에서 순환 선택 (`(partner_id + flow_idx) % 9`) |
| 수량 범위 표기 | 2,3,5,10,20,50 중 가중 선택 (문의 단계라 확정 수량 아님 — "약 N개") |
| 본문 어조 | 정중한 한국어 견적 문의 (3문장 + 제품·수량·납기 희망일) |

## 실행

```bash
# 컨테이너 내부 실행 (권장)
docker cp customers/greenpr/scripts odoo_client.py ycerp-web-greenpr:/tmp/ 2>/dev/null || true
docker cp customers/greenpr/scripts/send_inquiries.py ycerp-web-greenpr:/tmp/
docker cp customers/greenpr/docs/target-partners.json ycerp-web-greenpr:/tmp/
docker cp customers/greenpr/docs/products.json ycerp-web-greenpr:/tmp/
docker exec ycerp-web-greenpr python3 /tmp/send_inquiries.py

# 호스트에서 직접 실행 (게이트웨이 경유)
ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/send_inquiries.py
```

### 스크립트 인자

- `--dry-run` : 생성하지 않고 계획만 stdout 출력
- `--limit N` : 앞 N 건만 처리 (테스트용)

### 로그

실행 로그는 `customers/greenpr/docs/inquiry-log.md` 에 요약 테이블로 누적된다 (append mode, 각 실행마다 타임스탬프 섹션).

## 검증 쿼리

```python
# 생성된 문의 메일 전부 조회
cli.search_read(
    "mail.mail",
    [["body_html", "like", "ralph-demo-flow id=greenpr:"]],
    ["id", "subject", "email_from", "email_to", "state", "create_date"],
    order="create_date desc",
)
```

US-006 이 crm.lead를 만들 때, 동일한 `partner_id + planned_date` 조합의 mail.mail 을 찾아 `description` 에 인용하거나 `message_ids`로 연결한다.
