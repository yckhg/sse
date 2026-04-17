# Execution Log — 2026-04-17

`sse/scripts/generate-full-flow.py` 실행 이력. 각 섹션은 1회 실행.

## 2026-04-17 00:40:58 — tenant=greenpr mode=dry-run status=PASS

**Args**: `--tenant greenpr --days-back 30 --flows-per-partner 2 --dry-run`

**Target**: ODOO_URL=http://localhost:30033  web=ycerp-web-greenpr  db=ycerp-db-greenpr

**Duration**: 1.82s (00:40:58 → 00:41:00)

| step | label | rc | dur(s) | created | skipped | total | summary |
|---|---|---:|---:|---:|---:|---:|---|
| inquiry | US-005 문의(mail.mail) | 0 | 0.04 | - | - | - | `` |
| lead | US-006 CRM 영업건(crm.lead) | 0 | 0.29 | - | - | - | `` |
| quote | US-007 견적서(sale.order) | 0 | 0.44 | - | - | - | `` |
| invoice | US-008 청구서(account.move) | 0 | 0.47 | - | - | - | `` |
| po | US-009 매입발주(purchase.order) | 0 | 0.58 | - | - | - | `` |

## 2026-04-17 00:41:05 — tenant=greenpr mode=live status=PASS

**Args**: `--tenant greenpr --days-back 30 --flows-per-partner 2`

**Target**: ODOO_URL=http://localhost:30033  web=ycerp-web-greenpr  db=ycerp-db-greenpr

**Duration**: 2.69s (00:41:05 → 00:41:07)

| step | label | rc | dur(s) | created | skipped | total | summary |
|---|---|---:|---:|---:|---:|---:|---|
| inquiry | US-005 문의(mail.mail) | 0 | 0.36 | 0 | 22 | 22 | `[summary] created=0 skipped=22 total=22` |
| lead | US-006 CRM 영업건(crm.lead) | 0 | 0.38 | 0 | 22 | 22 | `[summary] created=0 skipped=22 total=22` |
| quote | US-007 견적서(sale.order) | 0 | 0.45 | 0 | 22 | 22 | `[summary] created=0 confirmed=0 lead_expected_revenue_updated=0 skipped=22 total=22` |
| invoice | US-008 청구서(account.move) | 0 | 0.78 | 0 | 22 | 22 | `[summary] created=0 posted=0 backfilled=0 skipped=22 total=22` |
| po | US-009 매입발주(purchase.order) | 0 | 0.72 | 0 | 22 | 22 | `[summary] created=0 confirmed=0 skipped=22 total=22` |

## 2026-04-17 00:45:45 — tenant=greenpr mode=dry-run status=PASS

**Args**: `--tenant greenpr --days-back 30 --flows-per-partner 2 --dry-run`

**Target**: ODOO_URL=http://localhost:30033  web=ycerp-web-greenpr  db=ycerp-db-greenpr

**Duration**: 1.79s (00:45:45 → 00:45:47)

| step | label | rc | dur(s) | created | skipped | total | summary |
|---|---|---:|---:|---:|---:|---:|---|
| inquiry | US-005 문의(mail.mail) | 0 | 0.04 | - | - | - | `` |
| lead | US-006 CRM 영업건(crm.lead) | 0 | 0.29 | - | - | - | `` |
| quote | US-007 견적서(sale.order) | 0 | 0.45 | - | - | - | `` |
| invoice | US-008 청구서(account.move) | 0 | 0.45 | - | - | - | `` |
| po | US-009 매입발주(purchase.order) | 0 | 0.56 | - | - | - | `` |

## 2026-04-17 00:45:52 — tenant=greenpr mode=live status=PASS

**Args**: `--tenant greenpr --days-back 30 --flows-per-partner 2`

**Target**: ODOO_URL=http://localhost:30033  web=ycerp-web-greenpr  db=ycerp-db-greenpr

**Duration**: 2.59s (00:45:52 → 00:45:55)

| step | label | rc | dur(s) | created | skipped | total | summary |
|---|---|---:|---:|---:|---:|---:|---|
| inquiry | US-005 문의(mail.mail) | 0 | 0.36 | 0 | 22 | 22 | `[summary] created=0 skipped=22 total=22` |
| lead | US-006 CRM 영업건(crm.lead) | 0 | 0.38 | 0 | 22 | 22 | `[summary] created=0 skipped=22 total=22` |
| quote | US-007 견적서(sale.order) | 0 | 0.47 | 0 | 22 | 22 | `[summary] created=0 confirmed=0 lead_expected_revenue_updated=0 skipped=22 total=22` |
| invoice | US-008 청구서(account.move) | 0 | 0.74 | 0 | 22 | 22 | `[summary] created=0 posted=0 backfilled=0 skipped=22 total=22` |
| po | US-009 매입발주(purchase.order) | 0 | 0.65 | 0 | 22 | 22 | `[summary] created=0 confirmed=0 skipped=22 total=22` |

## 2026-04-17 00:52:37 — tenant=greenpr mode=live status=PASS

**Args**: `--tenant greenpr --days-back 30 --flows-per-partner 2`

**Target**: ODOO_URL=http://localhost:30033  web=ycerp-web-greenpr  db=ycerp-db-greenpr

**Duration**: 2.59s (00:52:37 → 00:52:39)

| step | label | rc | dur(s) | created | skipped | total | summary |
|---|---|---:|---:|---:|---:|---:|---|
| inquiry | US-005 문의(mail.mail) | 0 | 0.36 | 0 | 22 | 22 | `[summary] created=0 skipped=22 total=22` |
| lead | US-006 CRM 영업건(crm.lead) | 0 | 0.38 | 0 | 22 | 22 | `[summary] created=0 skipped=22 total=22` |
| quote | US-007 견적서(sale.order) | 0 | 0.46 | 0 | 22 | 22 | `[summary] created=0 confirmed=0 lead_expected_revenue_updated=0 skipped=22 total=22` |
| invoice | US-008 청구서(account.move) | 0 | 0.75 | 0 | 22 | 22 | `[summary] created=0 posted=0 backfilled=0 skipped=22 total=22` |
| po | US-009 매입발주(purchase.order) | 0 | 0.64 | 0 | 22 | 22 | `[summary] created=0 confirmed=0 skipped=22 total=22` |

## 2026-04-17 00:52:45 — tenant=greenpr mode=dry-run status=PASS

**Args**: `--tenant greenpr --days-back 30 --flows-per-partner 2 --dry-run`

**Target**: ODOO_URL=http://localhost:30033  web=ycerp-web-greenpr  db=ycerp-db-greenpr

**Duration**: 1.79s (00:52:45 → 00:52:47)

| step | label | rc | dur(s) | created | skipped | total | summary |
|---|---|---:|---:|---:|---:|---:|---|
| inquiry | US-005 문의(mail.mail) | 0 | 0.04 | - | - | - | `` |
| lead | US-006 CRM 영업건(crm.lead) | 0 | 0.30 | - | - | - | `` |
| quote | US-007 견적서(sale.order) | 0 | 0.45 | - | - | - | `` |
| invoice | US-008 청구서(account.move) | 0 | 0.43 | - | - | - | `` |
| po | US-009 매입발주(purchase.order) | 0 | 0.57 | - | - | - | `` |

## 2026-04-17 00:57:37 — tenant=greenpr mode=live status=PASS

**Args**: `--tenant greenpr --days-back 30 --flows-per-partner 2`

**Target**: ODOO_URL=http://localhost:30033  web=ycerp-web-greenpr  db=ycerp-db-greenpr

**Duration**: 2.62s (00:57:37 → 00:57:40)

| step | label | rc | dur(s) | created | skipped | total | summary |
|---|---|---:|---:|---:|---:|---:|---|
| inquiry | US-005 문의(mail.mail) | 0 | 0.39 | 0 | 22 | 22 | `[summary] created=0 skipped=22 total=22` |
| lead | US-006 CRM 영업건(crm.lead) | 0 | 0.37 | 0 | 22 | 22 | `[summary] created=0 skipped=22 total=22` |
| quote | US-007 견적서(sale.order) | 0 | 0.47 | 0 | 22 | 22 | `[summary] created=0 confirmed=0 lead_expected_revenue_updated=0 skipped=22 total=22` |
| invoice | US-008 청구서(account.move) | 0 | 0.74 | 0 | 22 | 22 | `[summary] created=0 posted=0 backfilled=0 skipped=22 total=22` |
| po | US-009 매입발주(purchase.order) | 0 | 0.66 | 0 | 22 | 22 | `[summary] created=0 confirmed=0 skipped=22 total=22` |

## 2026-04-17 00:57:44 — tenant=greenpr mode=dry-run status=PASS

**Args**: `--tenant greenpr --days-back 30 --flows-per-partner 2 --dry-run`

**Target**: ODOO_URL=http://localhost:30033  web=ycerp-web-greenpr  db=ycerp-db-greenpr

**Duration**: 1.77s (00:57:44 → 00:57:46)

| step | label | rc | dur(s) | created | skipped | total | summary |
|---|---|---:|---:|---:|---:|---:|---|
| inquiry | US-005 문의(mail.mail) | 0 | 0.04 | - | - | - | `` |
| lead | US-006 CRM 영업건(crm.lead) | 0 | 0.29 | - | - | - | `` |
| quote | US-007 견적서(sale.order) | 0 | 0.44 | - | - | - | `` |
| invoice | US-008 청구서(account.move) | 0 | 0.44 | - | - | - | `` |
| po | US-009 매입발주(purchase.order) | 0 | 0.56 | - | - | - | `` |

