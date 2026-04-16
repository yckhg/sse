# Products — greenpr Odoo 테넌트

견적서·발주에 사용할 제품 샘플. US-007(견적서)·US-009(매입 발주) 스크립트에서 이 목록을 참조한다.

## 카운트 요약

| 구분 | 수 |
|---|---|
| `sale_ok=true, active=true` | **172** |
| `purchase_ok=true` (sale 가능 집합 내) | **172** |
| 겹치는 제품(판매+매입 모두 가능) | **172** |

> greenpr은 **sale_ok 제품이 전부 purchase_ok**. 별도 "판매 전용 제품"은 없다. 견적서·매입 발주 모두 같은 제품 풀을 공유.

## 샘플 20건 (기본 20건 = id asc)

| id | name | list_price (원) | standard_price (원) | sale_ok | purchase_ok | default_code | uom | type |
|---:|---|---:|---:|:---:|:---:|:---:|---|---|
| 3   | 친환경 현수막A             | 120,000 | 52,000 | ✓ | ✓ | — | Units | consu |
| 5   | 종이                       |   3,600 |  1,200 | ✓ | ✓ | — | Units | consu |
| 6   | 종이 명찰                  |   2,500 |  1,000 | ✓ | ✓ | — | Units | consu |
| 7   | 원단                       | 200,000 |      0 | ✓ | ✓ | — | Units | consu |
| 10  | 생분해성 현수막            |   2,000 |      0 | ✓ | ✓ | — | Units | consu |
| 92  | POP                        |       1 |      0 | ✓ | ✓ | — | Units | consu |
| 167 | PLA 현수막 (500\*90)cm     |  10,000 |  7,500 | ✓ | ✓ | — | Units | consu |
| 168 | PLA 현수막 (400\*70)cm     |   8,000 |  6,000 | ✓ | ✓ | — | Units | consu |
| 169 | PLA 현수막 (180\*60)cm     |   3,600 |  2,700 | ✓ | ✓ | — | Units | consu |
| 170 | PLA 현수막 (120\*120)cm    |   3,000 |  3,000 | ✓ | ✓ | — | m²    | consu |
| 171 | PLA 현수막 (90\*90)cm      |   1,800 |  1,350 | ✓ | ✓ | — | Units | consu |
| 172 | PLA 현수막 (120\*80)cm     |   2,400 |  1,800 | ✓ | ✓ | — | Units | consu |
| 173 | PLA 현수막 (80\*120)cm     |   1,600 |  1,200 | ✓ | ✓ | — | Units | consu |
| 174 | PLA 현수막 (60\*180)cm     |   1,200 |    900 | ✓ | ✓ | — | Units | consu |
| 175 | PLA 현수막 (90\*500)cm     |   1,800 |  1,350 | ✓ | ✓ | — | Units | consu |
| 176 | 재생 현수막 (500\*90)cm    |  10,000 |  7,500 | ✓ | ✓ | — | Units | consu |
| 177 | 재생 현수막 (400\*70)cm    |   8,000 |  6,000 | ✓ | ✓ | — | Units | consu |
| 178 | 재생 현수막 (180\*60)cm    |   3,600 |  2,700 | ✓ | ✓ | — | Units | consu |
| 179 | 재생 현수막 (120\*120)cm   |   2,400 |  1,800 | ✓ | ✓ | — | Units | consu |
| 180 | 재생 현수막 (90\*90)cm     |   1,800 |  1,350 | ✓ | ✓ | — | Units | consu |

## 최근 1개월 실사용 Top 9 (`date_order >= 2026-03-17` sale.order.line 집계)

US-007에서 실사용 패턴에 가깝게 픽하려면 이 리스트에서 가중 랜덤 추출 권장.

| product_id | name | 사용된 라인 수 |
|---:|---|---:|
| **188** | 생분해 현수막 (120\*120)cm | 10 |
|  92 | POP                        |  5 |
| 206 | PLA 배너 (120\*120)cm      |  2 |
| 233 | 종이 배너 (120\*120)cm     |  2 |
| 172 | PLA 현수막 (120\*80)cm     |  1 |
| 241 | 생분해현수 (PLA, 60\*180)  |  1 |
| 256 | 생분해현수 (재생, 400\*70) |  1 |
| 197 | 종이 현수막 (120\*120)cm   |  1 |
| 170 | PLA 현수막 (120\*120)cm    |  1 |

총 24개 sale.order.line, 9개 distinct 제품.

## 재현 쿼리 (XML-RPC)

컨테이너 내부 (`ycerp-web-greenpr`) 에서 실행:

```python
import xmlrpc.client
URL, DB, USER, PWD = "http://localhost:8069", "odoo", "admin", "admin"
common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
uid = common.authenticate(DB, USER, PWD, {})
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

# 판매 가능 + 활성
sale_ids = models.execute_kw(DB, uid, PWD, "product.product", "search",
    [[("sale_ok", "=", True), ("active", "=", True)]], {"order": "id asc"})

products = models.execute_kw(DB, uid, PWD, "product.product", "read",
    [sale_ids[:20]],
    {"fields": ["id", "name", "default_code", "list_price",
                 "standard_price", "sale_ok", "purchase_ok", "uom_id", "type"]})
```

## 특이사항 / 주의

- 대부분 제품의 `default_code`가 `false`. 식별자는 **id** 로만 사용.
- `type=consu` (소모품) — 재고 추적(stock) 하지 않음. 발주 후 receive 단계 의미 낮음.
- `uom_id`는 대체로 `Units`(id=1), 하지만 id **170**만 `m²`(id=10). 발주 수량 단위 주의.
- `standard_price=0` 인 품목(7, 10, 92 등)은 매입 단가 계산 시 `list_price × 0.6~0.7` 로직이 의미 있음. `standard_price>0` 인 경우는 그 값을 참조하는 fallback 고려.
- `categ_id`가 전부 `false`로 나오는데, 이는 Category가 "All"(id=1, 기본) 이라 `read` 시 표시 생략된 것 — 필터링에는 영향 없음.

## 관련 JSON

- `products.json` — 재사용 가능한 구조화 데이터 (후속 스토리 · 통합 스크립트에서 직접 로드)

## 출처

- 데이터: greenpr 테넌트 `product.product` + `sale.order.line` (2026-03-17 ~ 2026-04-16)
- 수집 시각: 2026-04-16
- 수집 스크립트: 컨테이너 안 `/tmp/query_products.py`, `/tmp/query_top_products.py` (임시, 커밋 안 함)
