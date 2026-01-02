#!/bin/bash

# 새로운 고객 Odoo 인스턴스 생성 스크립트
# 사용법: ./create-customer.sh <고객명> <포트번호> <DB_PASSWORD>
# 예: ./create-customer.sh customer1 8070 pass123

set -e

CUSTOMER_NAME=$1
PORT=$2
DB_PASSWORD=${3:-odoo}
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CUSTOMER_DIR="$BASE_DIR/customers/$CUSTOMER_NAME"

if [ -z "$CUSTOMER_NAME" ] || [ -z "$PORT" ]; then
    echo "사용법: $0 <고객명> <포트번호> [DB_PASSWORD]"
    echo "예: $0 customer1 8070 pass123"
    exit 1
fi

echo "=== 고객 Odoo 인스턴스 생성 중 ==="
echo "고객명: $CUSTOMER_NAME"
echo "포트: $PORT"
echo "디렉토리: $CUSTOMER_DIR"

# 디렉토리 생성
mkdir -p "$CUSTOMER_DIR/config"

# docker-compose.yml 생성
cat > "$CUSTOMER_DIR/docker-compose.yml" << EOF
version: '3.8'

services:
  db:
    image: postgres:15-alpine
    container_name: ycerp-db-${CUSTOMER_NAME}
    environment:
      POSTGRES_DB: ${CUSTOMER_NAME}_odoo
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_USER: odoo
    volumes:
      - ${CUSTOMER_NAME}-db:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U odoo"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: always
    networks:
      - ${CUSTOMER_NAME}-network

  web:
    build:
      context: ../../
      dockerfile: Dockerfile.web
    container_name: ycerp-web-${CUSTOMER_NAME}
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "${PORT}:8069"
    environment:
      DB_HOST: db
      DB_USER: odoo
      DB_PASSWORD: ${DB_PASSWORD}
      DB_PORT: 5432
      DB_NAME: ${CUSTOMER_NAME}_odoo
      ODOO_AUTO_INIT: "true"
      WITHOUT_DEMO: "all"
      LOG_LEVEL: info
    volumes:
      - ${CUSTOMER_NAME}-web:/var/lib/odoo
      - ../../odoo-19.0+e.20260101/odoo/addons:/usr/lib/python3/dist-packages/odoo/addons
      - ./config:/etc/odoo
    command: >
      sh -c "odoo 
             --addons-path=/usr/lib/python3/dist-packages/odoo/addons
             --db_host=db
             --db_user=odoo
             --db_password=${DB_PASSWORD}
             --db_name=${CUSTOMER_NAME}_odoo
             -c /etc/odoo/odoo.conf"
    restart: always
    networks:
      - ${CUSTOMER_NAME}-network

volumes:
  ${CUSTOMER_NAME}-db:
  ${CUSTOMER_NAME}-web:

networks:
  ${CUSTOMER_NAME}-network:
    driver: bridge
EOF

# odoo.conf 생성
cat > "$CUSTOMER_DIR/config/odoo.conf" << EOF
[options]
db_host = db
db_port = 5432
db_user = odoo
db_password = ${DB_PASSWORD}
db_name = ${CUSTOMER_NAME}_odoo
addons_path = /usr/lib/python3/dist-packages/odoo/addons
logfile = /var/log/odoo/odoo.log
log_level = info
workers = 2
max_cron_threads = 2
EOF

# .env 파일 생성
cat > "$CUSTOMER_DIR/.env" << EOF
CUSTOMER_NAME=${CUSTOMER_NAME}
CUSTOMER_PORT=${PORT}
CUSTOMER_DB_PASSWORD=${DB_PASSWORD}
EOF

echo ""
echo "✓ 생성 완료!"
echo ""
echo "실행 방법:"
echo "  cd $CUSTOMER_DIR"
echo "  docker-compose up -d"
echo ""
echo "접속 방법:"
echo "  http://localhost:${PORT}"
echo ""
echo "로그 확인:"
echo "  cd $CUSTOMER_DIR && docker-compose logs -f web"
