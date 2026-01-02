# Odoo 엔터프라이즈 다중 테넌트 환경 - 빠른 시작 가이드

## ✅ 현재 상태

### 메인 환경 (테스트용)
- **URL**: http://localhost:8069
- **상태**: ✅ 실행 중
- **기능**: 자동 초기화, 주요 모듈 사전 설치

### 자동 활성화된 모듈
- **기본**: Base, Web, CRM
- **영업**: Sale, Sales Management, E-Commerce
- **구매**: Purchase, Purchase Management  
- **회계**: Account, Accounting, 3-way matching
- **인사**: HR, Payroll, Recruitment
- **재고**: Inventory, Stock, Purchase
- **커뮤니케이션**: Mail, Calendar, Discuss
- **웹**: Website, Portal

---

## 🚀 새로운 고객 추가 (1줄!)

```bash
cd /home/hg/projects/sse
./create-customer.sh <고객명> <포트> [비밀번호]
```

### 예시
```bash
# Customer1 추가 (포트 8070)
./create-customer.sh customer1 8070 pass123

# Customer2 추가 (포트 8071)
./create-customer.sh customer2 8071 pass456

# Customer3 추가 (포트 8072)
./create-customer.sh customer3 8072 pass789
```

---

## 📁 디렉토리 구조

```
/home/hg/projects/sse/
├── docker-compose.yml              ← 메인 Odoo (8069)
├── Dockerfile                       ← 엔터프라이즈 빌드
├── init-odoo.sh                    ← 자동 초기화 스크립트
├── create-customer.sh              ← 고객 생성 도구
├── config/
│   └── odoo.conf                   ← Odoo 설정
├── customers/
│   ├── customer1/
│   │   ├── docker-compose.yml      ← Customer1 환경 (8070)
│   │   ├── config/odoo.conf
│   │   └── .env
│   ├── customer2/
│   │   ├── docker-compose.yml      ← Customer2 환경 (8071)
│   │   ├── config/odoo.conf
│   │   └── .env
│   └── customer3/
│       ├── docker-compose.yml      ← Customer3 환경 (8072)
│       ├── config/odoo.conf
│       └── .env
└── odoo-19.0+e.20260101/           ← 엔터프라이즈 소스
```

---

## ⚙️ 각 환경 관리

### 메인 Odoo 제어
```bash
cd /home/hg/projects/sse

# 실행
docker-compose up -d

# 중지
docker-compose down

# 로그 확인
docker-compose logs -f web

# 재시작
docker-compose restart web
```

### 고객별 Odoo 제어
```bash
cd /home/hg/projects/sse/customers/customer1

# 실행
docker-compose up -d

# 중지
docker-compose down

# 로그 확인
docker-compose logs -f web

# 재시작
docker-compose restart web
```

---

## 🔐 데이터베이스 정보

### 메인 환경
- **Host**: localhost
- **Port**: 5432 (내부)
- **User**: odoo
- **Password**: odoo
- **DB**: odoo

### Customer별 DB
- Customer1: `customer1_odoo` / `customer1_pass`
- Customer2: `customer2_odoo` / `customer2_pass`
- 기타: `{고객명}_odoo` / `{설정한_비밀번호}`

---

## 📊 포트 할당

| 환경 | HTTP 포트 | 설명 |
|------|----------|------|
| 메인 | 8069 | 테스트용 메인 Odoo |
| Customer1 | 8070 | 첫 번째 고객 |
| Customer2 | 8071 | 두 번째 고객 |
| Customer3 | 8072 | 세 번째 고객 |
| ... | 807X | 추가 고객 |

---

## 🔍 상태 확인

### 모든 컨테이너 상태
```bash
docker ps
```

### 메인 Odoo 상태
```bash
cd /home/hg/projects/sse && docker-compose ps
```

### 특정 고객 상태
```bash
cd /home/hg/projects/sse/customers/customer1 && docker-compose ps
```

---

## 🛠️ 문제 해결

### 포트 이미 사용 중인 경우
```bash
# 기존 컨테이너 확인
docker ps -a

# 불필요한 컨테이너 제거
docker-compose down

# 또는 포트번호 변경해서 새로운 고객 생성
./create-customer.sh customer_new 8080 pass
```

### 데이터베이스 연결 오류
```bash
# DB 헬스체크 확인
docker-compose ps

# DB 로그 확인
docker-compose logs db

# DB 재시작
docker-compose restart db
```

### 모듈 수동 활성화 필요시
```bash
# Odoo 컨테이너 접근
docker exec -it sse-web bash

# Odoo 셸에서 모듈 설치
odoo shell
env['ir.module.module'].search([('name', '=', 'module_name')]).button_install()
```

---

## 📝 다음 단계

- [ ] 백업 스크립트 작성
- [ ] 모니터링 및 알림 설정
- [ ] SSL/TLS 설정
- [ ] 로드 밸런싱 구성
- [ ] CI/CD 파이프라인 연동
- [ ] 커스텀 모듈 개발 및 통합

---

## 📞 문의

**생성일**: 2026-01-02
**Odoo 버전**: 19.0 Enterprise
**상태**: 프로덕션 테스트 준비 완료
