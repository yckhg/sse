# 00. greenpr 테넌트 환경 정보

> 본 문서는 greenpr 테넌트의 데이터 생성 자동화 작업의 기준 환경을 기록한다.
> 모든 후속 스토리(US-002 ~ US-011)는 이 문서를 전제로 동작한다.

---

## 1. Odoo 버전 / 에디션

| 항목 | 값 |
|------|----|
| Server version | `19.0+e-20251208` |
| Series | `19.0` |
| Edition | Enterprise (`server_serie` 끝 `e`) |
| 설치된 Enterprise 모듈 | `web_enterprise`, `account_accountant`, `crm_enterprise`, `sale_enterprise`, `stock_enterprise`, `mrp_account_enterprise`, `mail_enterprise`, `event_enterprise`, `digest_enterprise`, `analytic_enterprise`, `contacts_enterprise`, `website_enterprise`, `mrp_subcontracting_enterprise`, `mrp_subcontracting_account_enterprise` |
| 설치된 모듈 총 수 | 266 |

조회 방법:
```bash
docker exec ycerp-db-greenpr psql -U odoo -d odoo \
  -c "SELECT name, latest_version FROM ir_module_module WHERE state='installed' ORDER BY name;"
```

---

## 2. 핵심 모듈(필수, 본 PRD 영역)

| 모듈 | 버전 | 용도 |
|------|------|------|
| `base` | 19.0.1.3 | Odoo 코어 |
| `mail` | 19.0.1.19 | 메일 발송, mail.template, mail.mail |
| `contacts` | 19.0.1.0 | 파트너(`res.partner`) UI |
| `crm` | 19.0.1.9 | 영업기회(`crm.lead`) |
| `sale` / `sale_management` | 19.0.1.2 / 19.0.1.0 | 견적·판매주문(`sale.order`) |
| `purchase` / `purchase_stock` | 19.0.1.2 / 19.0.1.2 | 발주(`purchase.order`) |
| `account` / `account_accountant` | 19.0.1.4 / 19.0.1.1 | 회계, 청구서(`account.move`) |
| `stock` | 19.0.1.1 | 재고 (sale↔purchase 연결 시 필요) |
| `website` / `website_crm` / `website_sale` | 19.0.1.0 / 19.0.2.1 / 19.0.1.1 | 웹사이트, 문의 폼 → CRM lead 연동 |
| `sale_purchase` / `sale_purchase_stock` | (설치됨) | 판매↔발주 자동연계 |

조회 쿼리:
```sql
SELECT name, latest_version FROM ir_module_module
 WHERE state='installed'
   AND name IN ('base','sale','purchase','account','crm','mail','website',
                'contacts','sale_management','purchase_stock','account_accountant',
                'website_crm','website_sale','stock','sale_purchase')
 ORDER BY name;
```

---

## 3. DB 접속 정보

| 항목 | 값 |
|------|----|
| Host (컨테이너 내부) | `ycerp-db-greenpr` |
| Port | `5432` |
| User | `odoo` |
| Password | `odoo` |
| DB name | `odoo` |
| Web 컨테이너 → DB 호스트 | docker network `yc-network` 경유 컨테이너명 |

호스트(WSL)에서 직접 접속 (서비스 컨테이너로 진입):
```bash
docker exec -it ycerp-db-greenpr psql -U odoo -d odoo
```

호스트에서 단발성 쿼리:
```bash
docker exec ycerp-db-greenpr psql -U odoo -d odoo -c "<SQL>"
```

> 외부 노출 포트 없음. PostgreSQL은 내부 네트워크에서만 접근 가능.

---

## 4. Odoo Web / RPC 엔드포인트

### 4.1 외부(호스트/게이트웨이) 노출

| 항목 | 값 |
|------|----|
| 컨테이너 내부 포트 | `8069` (HTTP), `8071-8072` (longpolling) |
| 호스트 노출 포트 | `30033` (게이트웨이 nginx → web 컨테이너) |
| 도메인 | `https://greenpr.online` (게이트웨이 nginx HTTPS) |

검증:
```bash
curl -sf -o /dev/null -w "%{http_code}\n" http://localhost:30033
# 200 / 303
```

### 4.2 RPC 엔드포인트 (XML-RPC, JSON-RPC 모두 지원)

| 종류 | URL (외부) | URL (web 컨테이너 내부) |
|------|-----------|------------------------|
| XML-RPC common (auth, version) | `http://localhost:30033/xmlrpc/2/common` | `http://localhost:8069/xmlrpc/2/common` |
| XML-RPC object (CRUD, execute_kw) | `http://localhost:30033/xmlrpc/2/object` | `http://localhost:8069/xmlrpc/2/object` |
| JSON-RPC | `http://localhost:30033/jsonrpc` | `http://localhost:8069/jsonrpc` |

> **PRD 규칙**: 본 작업의 모든 데이터 입력은 XML-RPC 경유. DB 직접 INSERT 금지.

---

## 5. 인증 정보 (admin)

| 항목 | 값 |
|------|----|
| DB 이름 | `odoo` |
| Login | `admin` |
| Password | `admin` |
| User ID (uid) | `2` |
| 비고 | 내부 데모 환경. 외부 노출 시 즉시 변경 필요 |

XML-RPC 인증 테스트 (재현 가능):
```bash
docker exec ycerp-web-greenpr python3 - <<'PY'
import xmlrpc.client
url, db, login, pwd = 'http://localhost:8069', 'odoo', 'admin', 'admin'
common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
print('version:', common.version())
uid = common.authenticate(db, login, pwd, {})
print('uid:', uid)
assert uid == 2, 'admin uid must be 2'
PY
```

확인된 출력:
```
version: {'server_version': '19.0+e-20251208', 'server_version_info': [19, 0, 0, 'final', 0, 'e'], 'server_serie': '19.0', 'protocol_version': 1}
uid: 2
```

---

## 6. DB 백업 위치

| 항목 | 경로 / 값 |
|------|----------|
| SQL 덤프 | `customers/greenpr/full_db_backup.sql` (115 MB, 2026-01-22 기준) |
| Filestore 백업 | `customers/greenpr/odoo_filestore_backup/` |
| 신규 백업 명령 | `docker exec ycerp-db-greenpr pg_dump -U odoo odoo > customers/greenpr/full_db_backup_$(date +%Y%m%d).sql` |

> 본 PRD 작업은 기존 마스터 데이터(제품, 파트너, 회계 설정)를 보존한다.
> 작업 전 위 백업의 최신성을 확인할 것 — 1개월 이상 경과했으면 신규 백업 권장.

---

## 7. 주요 파일/디렉터리

```
customers/greenpr/
├── docker-compose.yml          # web/db 컨테이너 정의
├── config/odoo.conf            # Odoo 설정 (db 접속, addons_path)
├── full_db_backup.sql          # 마지막 풀 DB 백업
├── odoo_filestore_backup/      # 첨부/이미지 등 filestore 백업
└── docs/                       # 본 문서 시리즈 (PRD US-001~US-011 산출물)
```

컨테이너:
- `ycerp-web-greenpr` — Odoo 웹 (포트 8069/내부)
- `ycerp-db-greenpr` — PostgreSQL 15 (포트 5432/내부)

네트워크: `yc-network` (외부 docker bridge, 게이트웨이 nginx와 공유)

---

## 8. 후속 작업 전제

- 모든 데이터 입력은 `xmlrpc.client` 경유. Python stdlib만 사용 (US-004).
- 모든 record 생성 시 `create_date` 필드는 ORM이 덮어쓸 수 있으므로
  날짜 기반 시나리오에서는 `date_order`, `invoice_date`, `date_open` 등 도메인 필드를 사용.
  `create_date` 강제 변경이 필요할 경우 `mail.thread` 비활성화 + 별도 `write` 필요 (US-006~US-009 단계에서 결정).
- 외부 메일 실수 발송 방지: `outgoing_mail_server` 미설정 또는 sandbox 설정인지 사전 확인 (US-005).
