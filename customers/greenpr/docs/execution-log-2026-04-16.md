# Execution Log — 2026-04-16

`sse/scripts/generate-full-flow.py` 실행 이력. 각 섹션은 1회 실행.

## 2026-04-16 20:37:37 — tenant=greenpr mode=dry-run status=PASS

**Args**: `--tenant greenpr --days-back 30 --flows-per-partner 2 --dry-run`

**Target**: ODOO_URL=http://localhost:30033  web=ycerp-web-greenpr  db=ycerp-db-greenpr

**Duration**: 1.79s (20:37:37 → 20:37:38)

| step | label | rc | dur(s) | created | skipped | total | summary |
|---|---|---:|---:|---:|---:|---:|---|
| inquiry | US-005 문의(mail.mail) | 0 | 0.04 | - | - | - | `` |
| lead | US-006 CRM 영업건(crm.lead) | 0 | 0.29 | - | - | - | `` |
| quote | US-007 견적서(sale.order) | 0 | 0.43 | - | - | - | `` |
| invoice | US-008 청구서(account.move) | 0 | 0.46 | - | - | - | `` |
| po | US-009 매입발주(purchase.order) | 0 | 0.55 | - | - | - | `` |

## 2026-04-16 20:37:50 — tenant=greenpr mode=live status=PASS

**Args**: `--tenant greenpr --days-back 30 --flows-per-partner 2`

**Target**: ODOO_URL=http://localhost:30033  web=ycerp-web-greenpr  db=ycerp-db-greenpr

**Duration**: 2.61s (20:37:50 → 20:37:52)

| step | label | rc | dur(s) | created | skipped | total | summary |
|---|---|---:|---:|---:|---:|---:|---|
| inquiry | US-005 문의(mail.mail) | 0 | 0.39 | 0 | 22 | 22 | `[summary] created=0 skipped=22 total=22` |
| lead | US-006 CRM 영업건(crm.lead) | 0 | 0.38 | 0 | 22 | 22 | `[summary] created=0 skipped=22 total=22` |
| quote | US-007 견적서(sale.order) | 0 | 0.45 | 0 | 22 | 22 | `[summary] created=0 confirmed=0 lead_expected_revenue_updated=0 skipped=22 total=22` |
| invoice | US-008 청구서(account.move) | 0 | 0.74 | 0 | 22 | 22 | `[summary] created=0 posted=0 backfilled=0 skipped=22 total=22` |
| po | US-009 매입발주(purchase.order) | 0 | 0.65 | 0 | 22 | 22 | `[summary] created=0 confirmed=0 skipped=22 total=22` |

