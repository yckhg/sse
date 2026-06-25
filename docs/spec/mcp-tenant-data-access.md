# MCP 테넌트 데이터 접근 (읽기 전용) 스펙 — Spec 1

> 상태: 구현 대상 스펙 (buildable spec) · 독자: 구현자 / 오케스트레이터 / 검증자
> 이 문서 하나만 보고 오해 없이 구현하고 TDD를 작성할 수 있는 것이 목표다.
> 범위: 안전한 데이터 추출. 인사이트 발행(쓰기)·코드 수정은 이 스펙 밖(→ Spec 2 / 별도 트랙).

---

## 1. 비즈니스 맥락 / 목적

SSE는 멀티테넌트 Odoo 19 Enterprise 시스템으로, 현재 5개 테넌트가 가동 중이다
(전부 데모/평가용): `greenpr`, `mediapolytech`, `visualoft`, `jnj_i`, `freeworks`.
각 테넌트는 독립 `ycerp-db-<tenant>` PostgreSQL 컨테이너를 가지며 `yc-network`에 붙어 있다.

**왜 만드나.** 소수의 신뢰된 "인사이트 발굴자"가 자신의 Windows PC의 Claude Desktop으로
이 MCP 서버에 붙어, 테넌트 운영 데이터를 **읽어서** 교차 분석·인사이트를 도출한다.
(도출한 인사이트를 테넌트별 Odoo 사이트에 발행해 구성원이 열람하게 하는 것은 후속 Spec 2이며,
이 스펙은 **읽기**까지만 책임진다.)

**누가 쓰나.** MCP에 직접 붙는 발굴자는 소수이고 신뢰된 사람들이다. 일부는 전 테넌트를,
일부는 특정 테넌트만 보도록 권한을 나눈다.

**핵심 보장 4가지** (하나라도 깨지면 계약 위반):
1. 서버는 공개 인터넷에 노출되지 않는다.
2. 어떤 입력으로도 테넌트 데이터가 변경되지 않는다 (읽기 전용).
3. 호출자는 자신에게 허가된 테넌트만 접근한다.
4. 모든 접근이 감사 기록으로 남는다.

---

## 2. 기술 스택 / 런타임 (확정)

- **언어**: Python 3.11+.
- **MCP 프레임워크**: 공식 MCP Python SDK의 `FastMCP` 서버.
- **트랜스포트**: SSE (원격 Claude Desktop이 붙을 수 있어야 하므로). stdio 아님.
- **DB 드라이버**: `asyncpg` (PostgreSQL 비동기).
- **실행 형태**: Docker 컨테이너, `yc-network`에 연결.
- **호스트 정책**: 호스트에는 아무것도 설치하지 않는다(전부 컨테이너).

---

## 3. 배포 토폴로지 (확정)

```
[Windows Claude Desktop]
        │  (Tailscale tailnet, 100.64.0.0/10)
        ▼
[ tailscale 사이드카 컨테이너 ] ── 네트워크 네임스페이스 공유 ──> [ mcp 서버 컨테이너 ]
                                                                   │ asyncpg (mcp_ro 롤)
                                                                   ▼
                                                        ycerp-db-<tenant> (5개)
        [ docker-socket-proxy 컨테이너 ] <── 컨테이너 목록 조회만 ──┘ (테넌트 발견)
```

규칙:
- MCP 서버는 **Tailscale 사이드카와 네트워크 네임스페이스를 공유**하고, SSE 리스너를
  **Tailscale 인터페이스(100.64.0.0/10) 또는 loopback에만 바인딩**한다. `0.0.0.0` 금지.
- MCP 서버 포트는 **호스트로 publish하지 않으며, 게이트웨이(nginx)가 프록시하지 않는다.**
- 다음은 **반드시 제거**된다(현 상태 대비):
  - 게이트웨이의 20007 → MCP 프록시 블록 및 `20007:20007` 매핑.
  - MCP compose의 `8080:8080` 호스트 publish.
  - MCP 컨테이너의 raw `/var/run/docker.sock` 마운트.
- 테넌트 발견은 **read-only docker-socket-proxy**(컨테이너 목록 조회 엔드포인트만 허용,
  exec/생성/POST 차단)를 경유한다. MCP 서버는 Docker 데몬을 직접 제어할 수단을 갖지 않는다.

---

## 4. 신원 · 권한 모델 (확정)

- **도달 자체가 1차 인증**: Tailscale tailnet에 속한 디바이스만 서버에 닿는다.
- **호출자 신원**: 서버는 들어온 연결의 피어 IP에 대해 Tailscale 신원(이메일/호스트)을
  조회하여 호출자를 식별한다(별도 앱 토큰 없음).
- **권한 맵**: 버전관리되지 않는 설정 파일이 신원 → 허용 테넌트 범위를 정의한다.

  ```yaml
  # scope.yaml (git 비추적 / 시크릿)
  grants:
    - identity: "owner@example.com"
      tenants: ["*"]                       # 전체
    - identity: "analyst-vo@example.com"
      tenants: ["visualoft"]               # 단일
  default: { tenants: [] }                 # 미등록 신원은 0개
  ```
- 모든 도구 호출에서 서버는 (a) 신원이 유효한가, (b) 대상 `tenant`가 그 신원의 허용
  집합에 드는가를 강제한다. 범위 밖이면 거부하고, 열거 결과에서도 숨긴다.

---

## 5. 데이터 접근 · 읽기 전용 강제 (확정)

- **전용 DB 롤** `mcp_ro`: 각 테넌트 `odoo` DB에서 `CONNECT` + 스키마 `USAGE` +
  전 테이블 `SELECT`만 부여(미래 테이블 대상 `DEFAULT PRIVILEGES` 포함). INSERT/UPDATE/
  DELETE/DDL 권한 없음. MCP 서버는 이 롤로만 접속한다. (자격증명은 §7.)
- **추가 방어**: 각 `query`는 `READ ONLY` 트랜잭션에서 실행하고 세션
  `statement_timeout`을 건다. (롤이 1차 강제, 트랜잭션이 2차.)
- **`execute`(임의 쓰기 SQL) 도구는 존재하지 않는다.**
- **상한** (확정):
  - 반환 행수 상한: **5,000행**. 초과 시 잘라서 반환하고 `truncated: true` 표시.
  - 질의 시간 상한: **30,000 ms**. 초과 시 시간초과 오류.

---

## 6. 도구 명세 (입력 / 출력 / 오류) (확정)

모든 출력은 JSON. 모든 호출은 §4의 신원·범위 검사를 통과해야 한다.
공통 오류 형식: `{ "error": "<code>", "message": "<사람용, 자격증명/연결문자열 비노출>" }`.
오류 코드: `unknown_tenant`, `forbidden_tenant`, `write_rejected`, `query_timeout`, `query_error`.

### 6.1 `list_tenants() -> object`
- 입력: 없음.
- 출력: `{ "tenants": [ { "tenant": "<name>", "status": "connected|unreachable" } ] }`
  — **호출자 허용 범위 내** 테넌트만. 범위 밖 테넌트는 포함되지 않는다.

### 6.2 `list_tables(tenant: string) -> object`
- 입력: `tenant`.
- 출력: `{ "tenant": "<name>", "tables": ["<schema>.<table>", ...] }` (정렬됨).
- 오류: 범위 밖 → `forbidden_tenant`; 미존재 → `unknown_tenant`.

### 6.3 `get_schema(tenant: string, table: string) -> object`
- 입력: `tenant`, `table`(`schema.table` 또는 `table`).
- 출력:
  `{ "tenant": "...", "table": "...", "columns": [ { "name": "...", "type": "...", "nullable": true|false } ] }`.
- 오류: `forbidden_tenant` / `unknown_tenant`.

### 6.4 `query(tenant: string, sql: string) -> object`
- 입력: `tenant`, `sql`(단일 SELECT/읽기 질의).
- 출력:
  `{ "tenant": "...", "columns": ["..."], "rows": [[...], ...], "row_count": <int>, "truncated": true|false }`.
- 동작: `READ ONLY` 트랜잭션 + `statement_timeout`로 실행. 행수 상한 적용.
- 오류: 쓰기/DDL 포함 → `write_rejected`(실행 자체가 일어나지 않음); 시간초과 →
  `query_timeout`; 기타 SQL 오류 → `query_error`(원문 메시지는 새니타이즈).

---

## 7. 시크릿 처리 (확정)

- `mcp_ro` 자격증명, scope.yaml, Tailscale auth key 등 모든 비밀은 **git 비추적**
  env/secret 파일로 주입하며 `.gitignore`로 보호한다.
- 추적되는 어떤 파일(코드·compose·문서)에도 DB 비밀번호 평문이 없다.

---

## 8. 감사 로그 (확정)

- 모든 도구 호출은 JSONL 한 줄로 **마운트된 볼륨**에 append 된다:
  `{ "ts": "<ISO8601>", "identity": "...", "tenant": "...", "tool": "...",
     "sql_summary": "<앞 200자, 없으면 null>", "row_count": <int|null>,
     "duration_ms": <int>, "outcome": "ok|<error_code>" }`.
- 로그는 서버 재시작에도 보존된다.

---

## 9. 범위 밖 (명시적 비목표)

- 인사이트/리포트의 **발행(쓰기)** — Odoo `website_page` 생성 등은 **Spec 2**.
- 호스트/저장소 **코드 수정** — 이 MCP의 책임이 아니다(git 기반 별도 트랙).
- 결과 PII 마스킹 — 이 스펙 범위 아님(필요 시 후속).

---

## 10. 검증 단언 (TDD)

이 문서만으로 작성 가능한 OK/NOK 명제. (`spec-tdd` 대상)

- **A. 공개 리스너 부재** — 호스트의 공개/게시 인터페이스에서 MCP 서버 포트로 바인딩된
  리스너가 0이다. (`ss -tlnp`에 `0.0.0.0:<port>`/호스트IP 바인딩 없음; Tailscale
  인터페이스 또는 loopback 바인딩만.)
- **B. 게이트웨이 비노출** — 게이트웨이 설정에 MCP로 향하는 20007(또는 임의) 프록시
  블록이 없고, `20007` 포트 매핑이 없다.
- **C. docker.sock 미마운트** — MCP 서버 컨테이너에 raw `/var/run/docker.sock`가
  마운트되어 있지 않다.
- **D. 쓰기 도구 부재** — 노출된 MCP 도구 목록이 `{list_tenants, list_tables,
  get_schema, query}`와 정확히 일치하며 임의 쓰기/`execute` 도구가 없다.
- **E. 쓰기 거부 + 불변** — `query(tenant, "<INSERT|UPDATE|DELETE|DDL>")`은
  `write_rejected`를 반환하고, 대상 테넌트의 사전·사후 임의 테이블 행수가 동일하다.
- **F. read-only 롤** — MCP가 접속하는 DB 롤은 대상 테이블에 대해 SELECT만 가지며,
  같은 롤로의 직접 INSERT/UPDATE 시도가 권한 오류로 실패한다.
- **G. 테넌트 범위 강제** — 테넌트 X만 허가된 신원이 `query(Y, ...)` 하면
  `forbidden_tenant`를 받고, 같은 신원의 `list_tenants`에 Y가 없다.
- **H. 행수 상한** — 5,000행을 초과하는 결과의 `query`는 `row_count <= 5000`이고
  `truncated == true`.
- **I. 시간 상한** — 30초를 넘기는 질의는 `query_timeout`으로 종료되며 연결을 무한
  점유하지 않는다.
- **J. 감사 존재** — 임의의 도구 호출 직후 감사 로그 끝줄에 해당 호출의
  identity·tenant·tool·ts·outcome가 존재한다.
- **K. 시크릿 미노출** — 저장소 전체 grep에 `mcp_ro`/테넌트 DB 비밀번호 평문이 없다.
- **L. 신규 테넌트 자동 발견** — `yc-network`에 새 `ycerp-db-<t>`가 뜨면(그리고 허가
  범위에 들면) 재배포 없이 `list_tenants`에 나타난다.
