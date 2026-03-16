# ERP 다중 테넌트 환경 설정 가이드

## 1. 현재 구조
```
/home/hg/projects/sse/
├── docker-compose.yml          # 메인 서비스 정의
├── Dockerfile                  # erp 이미지 빌드
├── init-ycerp.sh               # 초기화 스크립트
├── config/
│   └── erp.conf                # erp 설정
├── customers/                  # 고객별 설정 (추가될 예정)
│   ├── customer1/
│   │   ├── docker-compose.yml
│   │   └── config.conf
│   └── customer2/
│       ├── docker-compose.yml
│       └── config.conf
├── ycerp-19.0+e.20260101/
```

## 2. 각 업체별 독립 실행 방법

### 업체1 YC ERP 인스턴스 추가
```bash
# customers/customer1/docker-compose.yml 생성
version: '3.8'
services:
  db-c1:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: customer1_ycerp
      POSTGRES_PASSWORD: ${CUSTOMER1_DB_PASSWORD:-pass123}
      POSTGRES_USER: ycerp
    volumes:
      - customer1-db:/var/lib/postgresql/data
    networks:
      - customer1-network

  web-c1:
    build:
      context: ../../
      dockerfile: Dockerfile
    depends_on:
      - db-c1
    ports:
      - "8069:8069"
    environment:
      DB_HOST: db-c1
      DB_USER: ycerp
      DB_PASSWORD: ${CUSTOMER1_DB_PASSWORD:-pass123}
      DB_NAME: customer1_ycerp
    networks:
      - customer1-network
    volumes:
      - customer1-web:/var/lib/ycerp
```

### 실행
```bash
cd /home/hg/projects/sse
docker-compose up -d  # 메인 YC ERP (포트 8069)

cd customers/customer1
docker-compose up -d  # Customer1 YC ERP (포트 8070 or 별도 포트)
```

## 3. 자동 모듈 활성화 현황
다음 모듈이 자동으로 활성화됩니다:
- base, web (기본)
- sale, purchase, crm (영업)
- account, account_accountant (회계)
- hr, payroll (인사)
- inventory, stock (재고)
- mail, calendar (커뮤니케이션)
- website (웹사이트)

## 4. 확장 시 주의사항
- 각 고객별 DB명, 포트, 암호 분리
- 환경변수 관리 (.env 파일 사용 권장)
- 네트워크 독립성 유지
- 백업 전략 수립

## 5. 다음 단계
[ ] 초기화 스크립트 테스트
[ ] 고객별 디렉토리 구조 생성
[ ] .env 파일 기반 설정 자동화
[ ] 백업/복구 스크립트 작성
