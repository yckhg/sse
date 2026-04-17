#!/bin/bash
set -euo pipefail

# greenpr_form_automation 모듈을 greenpr 테넌트에 설치/업그레이드한다.
# - 실행 중 web 컨테이너를 멈추고 ephemeral odoo 프로세스로 -i/-u --stop-after-init 수행
# - 완료 후 web 컨테이너 재기동 + central nginx reload
# - 최종적으로 ir_module_module.state='installed' 확인

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TENANT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MODULE="greenpr_form_automation"
DB_CONTAINER="ycerp-db-greenpr"
WEB_CONTAINER="ycerp-web-greenpr"
NGINX_CONTAINER="cetral-nginx"
DB_NAME="odoo"

cd "$TENANT_DIR"

echo "=== greenpr_form_automation install/upgrade ==="
echo "Tenant dir: $TENANT_DIR"

# 1) DB에서 현재 모듈 상태 조회 (row가 없으면 빈 문자열)
STATE="$(docker exec "$DB_CONTAINER" psql -U odoo -d "$DB_NAME" -tA \
  -v module="$MODULE" \
  -c "SELECT state FROM ir_module_module WHERE name=:'module'" 2>/dev/null | tr -d '[:space:]' || true)"

if [ "$STATE" = "installed" ]; then
  ACTION="-u"
  echo "→ 현재 상태: installed → upgrade (-u) 수행"
else
  ACTION="-i"
  echo "→ 현재 상태: '${STATE:-<not found>}' → install (-i) 수행"
fi

# 2) 실행 중 web 컨테이너 중단 (registry/세션 충돌 방지)
echo ""
echo "[1/4] web 컨테이너 중단"
docker compose stop web

# 3) Ephemeral odoo로 install/upgrade --stop-after-init
echo ""
echo "[2/4] Ephemeral odoo 실행: odoo $ACTION $MODULE --stop-after-init"
docker compose run --rm --no-deps \
  --entrypoint "" \
  web odoo "$ACTION" "$MODULE" \
    -d "$DB_NAME" \
    --stop-after-init \
    --without-demo=all \
    --no-http

# 4) web 컨테이너 기동
echo ""
echo "[3/4] web 컨테이너 기동"
docker compose up -d web

# 5) Central nginx reload (upstream DNS 캐시 무효화)
echo ""
echo "[4/4] central nginx reload"
if docker ps --filter "name=^${NGINX_CONTAINER}$" --format '{{.Names}}' | grep -q "$NGINX_CONTAINER"; then
  docker exec "$NGINX_CONTAINER" nginx -s reload
else
  echo "  (!) ${NGINX_CONTAINER} 컨테이너 없음 — reload 생략"
fi

# 6) 최종 상태 확인
echo ""
echo "=== 설치 결과 검증 ==="
# web 컨테이너 healthcheck 대기 (최대 60초)
for i in $(seq 1 30); do
  HC="$(docker inspect --format '{{.State.Health.Status}}' "$WEB_CONTAINER" 2>/dev/null || echo 'unknown')"
  if [ "$HC" = "healthy" ]; then
    break
  fi
  sleep 2
done

FINAL_STATE="$(docker exec "$DB_CONTAINER" psql -U odoo -d "$DB_NAME" -tA \
  -v module="$MODULE" \
  -c "SELECT state FROM ir_module_module WHERE name=:'module'" 2>/dev/null | tr -d '[:space:]' || true)"

echo "ir_module_module.state='$FINAL_STATE'"
if [ "$FINAL_STATE" = "installed" ]; then
  echo "✓ $MODULE 설치 성공"
  exit 0
else
  echo "✗ $MODULE 설치 실패 (state='$FINAL_STATE')"
  exit 1
fi
