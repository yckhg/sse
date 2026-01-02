#!/bin/bash

# Odoo 자동 초기화 및 모듈 활성화 스크립트
set -e

echo "=== Odoo 초기화 시작 ==="

# DB 대기
until PGPASSWORD=$DB_PASSWORD psql -h "$DB_HOST" -U "$DB_USER" -d postgres -c "SELECT 1" 2>/dev/null; do
    echo "DB 연결 대기 중..."
    sleep 2
done

echo "✓ DB 연결 성공"

# DB 이름 확인 및 설정
export DB_NAME=${DB_NAME:-odoo}

# DB 초기화 (최초 실행 시에만)
DB_EXISTS=$(PGPASSWORD=$DB_PASSWORD psql -h "$DB_HOST" -U "$DB_USER" -lqt 2>/dev/null | cut -d \| -f 1 | grep -w "$DB_NAME" || echo "")

if [ -z "$DB_EXISTS" ]; then
    echo "=== 데이터베이스 '${DB_NAME}' 초기화 중 ==="
    
    # DB 생성
    PGPASSWORD=$DB_PASSWORD createdb -h "$DB_HOST" -U "$DB_USER" "$DB_NAME" 2>/dev/null || true
    
    echo "✓ 데이터베이스 초기화 완료"
    echo "⏳ Odoo가 자동으로 테이블을 생성합니다..."
else
    echo "✓ 데이터베이스 '${DB_NAME}' 이미 존재함"
fi

echo ""
echo "=== Odoo 초기화 완료 ==="
echo "데이터베이스: ${DB_NAME}"
echo "호스트: ${DB_HOST}:${DB_PORT}"

