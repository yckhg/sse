# 02. 대상 파트너 리스트

**집계 기준:** `sale.order.date_order >= 2026-03-17` (기준일 2026-04-16부터 역 30일)
**대상 테넌트:** greenpr
**집계 방법:** XML-RPC `sale.order.search_read` → `partner_id` DISTINCT + `max(date_order)`
**조회 시각:** 2026-04-16 (KST)

## 요약

- **Distinct 파트너 수:** 11
- **최근 1개월 주문 건수 합계:** 28
- **파트너당 목표 신규 플로우:** 2
- **생성 대상 총 플로우 수:** 22

> 파트너 이름 "모나용평"은 id 493 과 652 가 별도 레코드로 존재한다(동명 다른 파트너). 각각 2건씩 별도로 생성한다.
> "일곡문화재단"과 "일곡문화재단 PLA 현수막"도 서로 다른 `res.partner` 레코드(576 vs 649).

## 파트너 목록

| partner_id | partner_name | email | last_order_date | recent_orders | target_new_orders |
|---:|---|---|---|---:|---:|
| 594 | WJ바이오 | HYJ@ycgroup.co.kr | 2026-04-16 | 9 | 2 |
| 492 | 피알원 | zcbm0991@naver.com | 2026-03-23 | 1 | 2 |
| 493 | 모나용평 | zcbm0991@naver.com | 2026-03-20 | 3 | 2 |
| 647 | 무브멘토 | movement_orr@naver.com | 2026-03-20 | 4 | 2 |
| 567 | 아리기획 | (없음) | 2026-03-20 | 1 | 2 |
| 576 | 일곡문화재단 | (없음) | 2026-03-20 | 2 | 2 |
| 650 | 동물자유연대 | (없음) | 2026-03-20 | 2 | 2 |
| 575 | 사직나눔재단 | (없음) | 2026-03-20 | 3 | 2 |
| 652 | 모나용평 | (없음) | 2026-03-19 | 1 | 2 |
| 651 | 경기환경에너지진흥원 | (없음) | 2026-03-19 | 1 | 2 |
| 649 | 일곡문화재단 PLA 현수막 | (없음) | 2026-03-19 | 1 | 2 |

## 원본 구조화 데이터

`target-partners.json`으로 내보낸 JSON에 파트너별 `planned_dates`, `email`, `phone`, `is_company` 가 포함되어 있어 후속 스토리(US-005 ~ US-011)에서 그대로 읽어 쓸 수 있다. 경로: `customers/greenpr/docs/target-partners.json`

## 재현 쿼리 (XML-RPC)

```python
import xmlrpc.client
common = xmlrpc.client.ServerProxy('http://localhost:8069/xmlrpc/2/common')
uid = common.authenticate('odoo', 'admin', 'admin', {})
models = xmlrpc.client.ServerProxy('http://localhost:8069/xmlrpc/2/object')

orders = models.execute_kw('odoo', uid, 'admin', 'sale.order', 'search_read',
    [[('date_order', '>=', '2026-03-17')],
     ['partner_id','date_order','amount_total']])
```

- 컨테이너 내부(예: `docker exec ycerp-web-greenpr python3 ...`)에서 실행하면 포트/방화벽 이슈 없음
- 호스트에서 실행하려면 `http://localhost:30033/xmlrpc/2/...` 로 경로만 치환
