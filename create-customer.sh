#!/bin/bash
#
# 새로운 테넌트(고객) Odoo 인스턴스 생성 스크립트
#
# 운영 중인 테넌트(greenpr/visualoft/jnj_i/mediapolytech/freeworks)와
# 동일한 패턴으로 customers/<테넌트>/ 를 생성한다.
#   - db  : Dockerfile.db (postgres:15 + pgvector), 컨테이너 ycerp-db-<테넌트>
#   - web : Dockerfile.web (Odoo 19 EE 소스 포함), 컨테이너 ycerp-web-<테넌트>
#   - 네트워크: 외부 yc-network (게이트웨이 nginx가 컨테이너명으로 프록시)
#   - 기본적으로 호스트 포트를 열지 않는다. 외부 공개는 게이트웨이에서 처리.
#
# 사용법:
#   ./create-customer.sh <테넌트ID> [로컬포트] [옵션]
#
#   <테넌트ID>   소문자/숫자/언더스코어. 디렉토리·컨테이너·DB 호스트명에 그대로 쓰인다.
#   [로컬포트]   지정하면 127.0.0.1:<포트>:8069 로만 바인딩 (로컬 점검용, 외부 노출 아님)
#
# 옵션:
#   --force      기존 파일 덮어쓰기
#   --up         생성 후 docker compose up -d 까지 실행
#
# 예:
#   ./create-customer.sh greenpm 30083
#   ./create-customer.sh acme --up
#
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NETWORK="yc-network"
ODOO_SRC="odoo-19.0+e.20260101"

TENANT=""
LOCAL_PORT=""
FORCE=0
DO_UP=0

usage() {
    sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 1
}

for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        --up)    DO_UP=1 ;;
        -h|--help) usage ;;
        *)
            if [ -z "$TENANT" ]; then TENANT="$arg"
            elif [ -z "$LOCAL_PORT" ]; then LOCAL_PORT="$arg"
            else echo "알 수 없는 인자: $arg" >&2; exit 1
            fi ;;
    esac
done

[ -z "$TENANT" ] && usage

# --- 입력 검증 -------------------------------------------------------------
if ! [[ "$TENANT" =~ ^[a-z][a-z0-9_]*$ ]]; then
    echo "✗ 테넌트ID는 소문자로 시작하는 [a-z0-9_] 조합이어야 합니다: '$TENANT'" >&2
    exit 1
fi

if [ -n "$LOCAL_PORT" ] && ! [[ "$LOCAL_PORT" =~ ^[0-9]+$ ]]; then
    echo "✗ 포트는 숫자여야 합니다: '$LOCAL_PORT'" >&2
    exit 1
fi

CUSTOMER_DIR="$BASE_DIR/customers/$TENANT"

# --- 사전 점검 -------------------------------------------------------------
if [ ! -d "$BASE_DIR/$ODOO_SRC" ]; then
    echo "✗ Odoo Enterprise 소스가 없습니다: $BASE_DIR/$ODOO_SRC" >&2
    exit 1
fi

if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
    echo "✗ 외부 네트워크 '$NETWORK' 가 없습니다. customers/create-network.sh 를 먼저 실행하세요." >&2
    exit 1
fi

if docker ps -a --format '{{.Names}}' | grep -qx "ycerp-web-$TENANT"; then
    echo "✗ 컨테이너 ycerp-web-$TENANT 가 이미 존재합니다." >&2
    exit 1
fi

if [ -n "$LOCAL_PORT" ] && ss -ltn 2>/dev/null | grep -q ":$LOCAL_PORT "; then
    echo "✗ 포트 $LOCAL_PORT 는 이미 사용 중입니다." >&2
    exit 1
fi

for f in docker-compose.yml config/odoo.conf; do
    if [ -e "$CUSTOMER_DIR/$f" ] && [ "$FORCE" -ne 1 ]; then
        echo "✗ 이미 존재: customers/$TENANT/$f  (덮어쓰려면 --force)" >&2
        exit 1
    fi
done

echo "=== 테넌트 생성 ==="
echo "  테넌트ID   : $TENANT"
echo "  디렉토리   : $CUSTOMER_DIR"
echo "  DB 컨테이너: ycerp-db-$TENANT"
echo "  웹 컨테이너: ycerp-web-$TENANT"
echo "  로컬포트   : ${LOCAL_PORT:-(없음 — 게이트웨이 경유만)}"
echo ""

mkdir -p "$CUSTOMER_DIR/config" "$CUSTOMER_DIR/addons"

# 로컬 점검용 포트는 루프백에만 바인딩한다. 외부 공개는 게이트웨이 담당.
if [ -n "$LOCAL_PORT" ]; then
    WEB_PORTS=$(printf '    ports:\n      - "127.0.0.1:%s:8069"\n' "$LOCAL_PORT")
else
    WEB_PORTS=$(printf '    # ports:  # 외부 공개는 게이트웨이 nginx 경유\n    #   - "127.0.0.1:XXXXX:8069"\n')
fi

# --- docker-compose.yml ----------------------------------------------------
cat > "$CUSTOMER_DIR/docker-compose.yml" << EOF
services:
  db:
    build:
      context: ../../
      dockerfile: Dockerfile.db
    container_name: ycerp-db-${TENANT}
    environment:
      POSTGRES_DB: postgres
      POSTGRES_PASSWORD: odoo
      POSTGRES_USER: odoo
    volumes:
      - odoo-db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U odoo"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: always
    networks:
      - ${NETWORK}

  web:
    build:
      context: ../../
      dockerfile: Dockerfile.web
    container_name: ycerp-web-${TENANT}
    depends_on:
      db:
        condition: service_healthy
${WEB_PORTS}
    environment:
      # DB 접속 정보는 config/odoo.conf 에서 관리
      ODOO_AUTO_INIT: "true"
      WITHOUT_DEMO: "all"
      LOG_LEVEL: info
    volumes:
      - odoo-web-data:/var/lib/odoo
      - ../../${ODOO_SRC}/odoo/addons:/usr/lib/python3/dist-packages/odoo/addons
      - ./config:/etc/odoo
      - ./addons:/mnt/extra-addons:ro
    restart: always
    networks:
      - ${NETWORK}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8069/odoo"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  odoo-db-data:
  odoo-web-data:

networks:
  ${NETWORK}:
    external: true
EOF

# --- config/odoo.conf ------------------------------------------------------
cat > "$CUSTOMER_DIR/config/odoo.conf" << EOF
[options]
; 데이터베이스 연결
db_host = ycerp-db-${TENANT}
db_port = 5432
db_user = odoo
db_password = odoo
db_name = odoo

; 애드온 경로
addons_path = /usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons

; 로깅
logfile = /var/log/odoo/odoo.log
log_level = info

; 성능
workers = 2
max_cron_threads = 2

; 리버스 프록시(gateway nginx) 뒤에서 동작
proxy_mode = True
EOF

echo "✓ 생성됨:"
echo "    customers/$TENANT/docker-compose.yml"
echo "    customers/$TENANT/config/odoo.conf"
echo "    customers/$TENANT/addons/            (커스텀 모듈 두는 곳)"
echo ""

if [ "$DO_UP" -eq 1 ]; then
    echo "=== 컨테이너 기동 ==="
    (cd "$CUSTOMER_DIR" && docker compose up -d)
    echo ""
fi

if [ -n "$LOCAL_PORT" ]; then
    CHECK_CMD="curl -I http://127.0.0.1:$LOCAL_PORT/odoo"
else
    CHECK_CMD="(로컬포트 미지정 — docker exec ycerp-web-$TENANT curl -I localhost:8069/odoo)"
fi

cat << EOF
다음 단계:
  1) 기동          : cd customers/$TENANT && docker compose up -d
  2) 로그          : docker compose logs -f web
  3) 로컬 확인     : $CHECK_CMD
  4) 엔터프라이즈  : 웹 UI 설정 → 구독 코드 등록 (테넌트마다 별도 코드)
  5) 외부 공개 시  : gateway/nginx.conf 에 server 블록 추가 후
                     docker exec gateway nginx -s reload
                     ※ nginx 는 업스트림 DNS 를 캐시하므로 reload 필수
EOF
