#!/bin/bash

# Odoo 프로덕션 이미지 생성 스크립트
# 현재 설정 완료된 상태의 Odoo를 이미지로 저장
# 사용법: ./make-production-image.sh

set -e

IMAGE_NAME="sse-odoo"
IMAGE_TAG="production-$(date +%Y%m%d-%H%M%S)"

echo "=== Odoo 프로덕션 이미지 생성 ==="
echo ""

# 현재 컨테이너 상태 확인
if ! docker ps | grep -q sse-web; then
    echo "❌ 에러: sse-web 컨테이너가 실행 중이 아닙니다"
    echo "먼저 docker-compose up -d로 시작하세요"
    exit 1
fi

echo "✓ sse-web 컨테이너 확인됨"
echo ""

# 프로덕션 이미지 생성
echo "📦 프로덕션 이미지 생성 중: $IMAGE_NAME:$IMAGE_TAG"
docker commit sse-web "$IMAGE_NAME:$IMAGE_TAG"

echo ""
echo "✅ 프로덕션 이미지 생성 완료!"
echo ""
echo "생성된 이미지:"
docker images | grep "$IMAGE_NAME" | head -3

echo ""
echo "📝 다음 단계:"
echo "1. 새로운 고객 인스턴스 생성 시 이 이미지 사용"
echo "2. docker-compose.yml의 web 서비스에서:"
echo "   image: $IMAGE_NAME:$IMAGE_TAG"
echo "   로 변경하여 사용"
echo ""
