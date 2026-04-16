# 05 — Purchase Order (US-009)

매입 발주(`purchase.order` + `purchase.order.line`) 22건 생성 + `button_confirm` → state='purchase'.
US-007 `sale.order` 와 1:1 (조달 흐름 관점에서 별도 매핑 — 같은 product_id/qty 사용, vendor 는 supplier_rank>0 파트너 풀에서 결정적 선택, price_unit 은 SO 단가 × 0.60~0.70).

## 1. 모델 / 핵심 필드

### purchase.order
| 필드 | 타입 | 비고 |
|---|---|---|
| `name` | char | 자동 채번 (`P00033`, `P00034`, …) |
| `partner_id` | M2O res.partner | **vendor**. supplier_rank>0 파트너 |
| `currency_id` | M2O res.currency | greenpr 기본 KRW(id=32). vals 생략 시 vendor.property_purchase_currency_id 또는 company.currency 자동 |
| `company_id` | M2O res.company | 1 (greenPR) |
| `date_order` | datetime | 우리가 지정. **`button_confirm` 이 덮지 않음**(검증 완료 — 기존 PO 31 / 신규 smoke test PO 34 모두 보존). `date_approve` 가 별도 필드 |
| `date_approve` | datetime | `button_confirm` 시 now()로 set. 우리가 직접 안 씀 |
| `picking_type_id` | M2O stock.picking.type | greenpr 5개 (id=1 GPR Receipts 기본). 명시 안 하면 default warehouse 의 incoming type 사용 |
| `user_id` | M2O res.users | 2 (admin/green PR) |
| `state` | selection | `draft → sent → purchase → done → cancel`. `button_confirm` 으로 `purchase` |
| `order_line` | O2M purchase.order.line | one2many. `[(0, 0, {…})]` 시그니처 |
| `origin` | char | 자유 텍스트. SO 이름(`S00105`) 기록 권장 |
| `partner_ref` | char | vendor 측 reference. demo 에선 비움 |
| `note` | html | "Terms and Conditions". **idempotency marker 위치** |
| `amount_total/untaxed` | monetary | computed. tax 자동 적용 (line.tax_ids = product.supplier_taxes_id) |

### purchase.order.line
| 필드 | 타입 | 비고 |
|---|---|---|
| `product_id` | M2O product.product | 필수는 아니나 demo 에선 SO line 과 동일 |
| `product_qty` | float | required. SO line.product_uom_qty 와 동일 |
| `product_uom_id` | M2O uom.uom | 생략 시 product.uom_id 자동 |
| `price_unit` | float | required. **SO 단가 × random(0.6~0.7)** |
| `name` | text | required. product 이름 |
| `tax_ids` | M2M account.tax | create 시 `product.supplier_taxes_id` 자동 복사 (수동 명시 불필요) |
| `date_planned` | datetime | 생략 시 PO.date_order 기반 자동 |

## 2. 벤더 풀 (curated)

`supplier_rank>0 + active=true + is_company=true + parent_id=False` 필터 → 49→13 명. `[…]` 으로 시작하거나 잡음 이름(`3`, `19`, `1907`, `3D`, `PL`, `사업자 테스트`) 제외:

```
358 '플러스'      476 '플러스'      477 '네이처'      478 'PD무역'
479 '씨엔엔'      480 'DS기획'      481 '더블에스'    482 'PWK'
483 '페이퍼에스'  484 '유케이미디어'  485 '인쇄나라K'   486 '에볼루션'   601 'GN'
```

벤더가 0명이면 PRD AC "건너뛰고 기록" — 본 테넌트는 13명 확보.

## 3. 매핑 / 결정성

각 flow 의 vendor 와 price_unit 은 **`(partner_id, planned_date, flow_idx)` 결정적 함수**:

- vendor: `vendor_pool[(partner_id + flow_idx) % len(pool)]`
- price multiplier: `random.Random(SEED + flow_idx).uniform(0.60, 0.70)` — `SEED=20260416`
- date_order: `SO.date_order + (flow_idx % 3)` 일 (0/1/2일 후, 09:30:00 그대로 유지)

마커: `<!-- ralph-demo-flow id=greenpr:po:<partner_id>:<planned_date> -->` → `purchase.order.note`

검증 search:
```python
cli.search("purchase.order",
    [["note", "like", f"ralph-demo-flow id=greenpr:po:{partner_id}:{planned_date}"]])
```

## 4. 실행 절차

```bash
# 호스트 (게이트웨이 경유)
ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/create_purchase_orders.py [--dry-run] [--limit N]

# 컨테이너 내부
docker cp customers/greenpr/scripts/ ycerp-web-greenpr:/tmp/
docker exec ycerp-web-greenpr python3 /tmp/scripts/create_purchase_orders.py [--dry-run] [--limit N]
```

옵션:
- `--dry-run` — 계획만 출력, INSERT/confirm 없음
- `--limit N` — 앞 N 건만
- `--skip-confirm` — button_confirm 생략 (state='draft' 로 둠)
- `--no-vendor-required` — 벤더 풀이 비어 있어도 진행 (None partner_id 로 create 시도 — 보통 실패)

## 5. Idempotency 분기

1) **marker 검색**: `purchase.order.note like '...po:<partner>:<date>'` → 존재 시 skip
2) marker 없어도 SO.origin 으로 매칭하는 분기는 두지 않음 (US-008 invoice 와 달리 PO 는 SO 와 직접 FK 없음). 동일 partner/date 에 다른 절차로 만든 PO 가 있어도 본 스크립트는 새 PO 생성

## 6. 정합성 검증 쿼리

```sql
-- partner당 PO 2건씩
SELECT so.partner_id, COUNT(*) AS po_cnt
FROM purchase_order po
JOIN sale_order so ON po.origin = so.name
WHERE po.note LIKE '%ralph-demo-flow id=greenpr:po:%'
GROUP BY so.partner_id
ORDER BY so.partner_id;

-- price ratio 0.6~0.7
SELECT po.id, po.name, sol.price_unit AS so_price, pol.price_unit AS po_price,
       ROUND((pol.price_unit / sol.price_unit)::numeric, 4) AS ratio
FROM purchase_order po
JOIN purchase_order_line pol ON pol.order_id = po.id
JOIN sale_order so ON po.origin = so.name
JOIN sale_order_line sol ON sol.order_id = so.id AND sol.product_id = pol.product_id
WHERE po.note LIKE '%ralph-demo-flow id=greenpr:po:%'
ORDER BY po.id;

-- date_order >= sale_order.date_order
SELECT po.id, po.name, po.date_order, so.date_order AS so_date,
       (po.date_order >= so.date_order) AS chronology_ok
FROM purchase_order po
JOIN sale_order so ON po.origin = so.name
WHERE po.note LIKE '%ralph-demo-flow id=greenpr:po:%'
ORDER BY po.id;
```

## 7. 위험 / 주의

- **purchase.order.note 는 html field** — marker 를 HTML 주석으로 박아도 표시 안 됨, 하지만 `LIKE` 검색은 평문이므로 정상 동작
- **button_confirm 후 unlink 어렵다** — 매입 발주가 stock.picking 을 자동 생성. 정리 시 `button_cancel` 후 unlink 필요. 본 스크립트는 정리 도구 없음
- **product type=consu** (greenpr 전 제품) → button_confirm 이 stock.picking 만들지만 receive 단계 의미 없음. PRD 노트 그대로
- **벤더 가 0명인 다른 테넌트** → `--no-vendor-required` 도 사실상 실패. partner_id 가 required. 적용 시엔 사전에 supplier_rank 부여 필요
- **price_unit 의 random** — `SEED=20260416 + flow_idx` 로 재실행 시 같은 단가 (idempotent). seed 변경 시 새 값
