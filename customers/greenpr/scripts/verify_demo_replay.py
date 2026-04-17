"""US-003: cleanup(US-001) + replay(US-002) 실행 이후 DB 상태를 검증한다.

PRD-3(greenpr-demo-replay) 의 목표인
    "실제 SMTP 발송 + crm.lead ↔ mail.mail 연결"
이 22건 전부에서 충족되었는지 확인하는 읽기 전용 스크립트.

검사 항목 (PRD US-003 AC)
-----------------------
C1. ralph-demo-flow 마커 crm.lead 정확히 22건 존재
C2. 각 crm.lead 에 "견적 문의" 제목(공백 포함) 의 mail.mail 이 최소 1건 매달려 있다
    (mail.message.res_id = crm.lead.id, mail.message.model = 'crm.lead')
C3. 각 crm.lead 에 매달린 해당 mail.mail 중 최소 1건의 state 가 'sent' 또는 'outgoing'
C4. 해당 mail.mail 들의 email_to 가 'greenpr9@gmail.com'
C5. `ralph-demo-flow` 마커를 가진 mail.mail 중 res_id 가 NULL (= False) 인 건 0건

실행
----
    # 호스트에서 게이트웨이 경유
    ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/verify_demo_replay.py

    # 컨테이너 내부 (권장, 타임아웃 회피)
    docker cp customers/greenpr/scripts/verify_demo_replay.py ycerp-web-greenpr:/tmp/
    docker exec ycerp-web-greenpr python3 /tmp/verify_demo_replay.py

인자
----
    --output-json P   JSON 결과 저장 경로. 기본: ../docs/99-demo-replay-verification.json
    --no-write        JSON 저장 생략 (콘솔 출력만)

종료 코드
--------
    rc=0  모든 검사 PASS
    rc=1  하나 이상 검사 FAIL (stdout 및 JSON 에 실패 상세)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odoo_client import OdooClient  # noqa: E402


MARKER = "ralph-demo-flow"
EXPECTED_LEADS = 22
OUR_SUBJECT_LITERAL = "견적 문의"  # US-002 템플릿이 렌더하는 공백 포함 리터럴
EXPECTED_EMAIL_TO = "greenpr9@gmail.com"
VALID_STATES = {"sent", "outgoing"}


def _find_lead_mails(cli: OdooClient, lead_id: int) -> list[dict]:
    """lead 에 연결된 'our' mail.mail(공백 포함 '견적 문의' subject/body) 을 모두 반환."""
    return cli.search_read(
        "mail.mail",
        [
            ("model", "=", "crm.lead"),
            ("res_id", "=", lead_id),
            "|",
            ("subject", "like", f"%{OUR_SUBJECT_LITERAL}%"),
            ("body_html", "like", f"%{OUR_SUBJECT_LITERAL}%"),
        ],
        ["id", "subject", "state", "email_to", "res_id"],
        order="id desc",
    )


def run_checks(cli: OdooClient) -> tuple[list[dict], dict]:
    """5 검사를 차례로 실행. (check_rows, summary) 반환."""
    checks: list[dict] = []

    # ---------- C1 ----------
    leads = cli.search_read(
        "crm.lead",
        [("description", "like", f"%{MARKER}%")],
        ["id", "name", "partner_name", "contact_name", "email_from"],
        order="id asc",
    )
    leads_found = len(leads)
    checks.append({
        "id": "C1",
        "name": f"crm.lead with '{MARKER}' marker = {EXPECTED_LEADS}",
        "ok": leads_found == EXPECTED_LEADS,
        "detail": f"found={leads_found} expected={EXPECTED_LEADS}",
    })

    # ---------- C2 / C3 / C4 (per-lead) ----------
    per_lead: list[dict] = []
    c2_fail, c3_fail, c4_fail = [], [], []
    for lead in leads:
        lid = int(lead["id"])
        mails = _find_lead_mails(cli, lid)
        entry: dict = {
            "lead_id": lid,
            "partner_name": lead.get("partner_name"),
            "contact_name": lead.get("contact_name"),
            "mail_count": len(mails),
            "mails": mails,
        }

        if not mails:
            entry["c2_ok"] = False
            entry["c3_ok"] = False
            entry["c4_ok"] = False
            entry["reason"] = "no mail.mail with '견적 문의' linked to this lead"
            per_lead.append(entry)
            c2_fail.append(lid)
            c3_fail.append(lid)
            c4_fail.append(lid)
            continue

        entry["c2_ok"] = True

        # C3: any mail in a valid sending state
        state_ok = any((m.get("state") or "") in VALID_STATES for m in mails)
        entry["c3_ok"] = state_ok
        if not state_ok:
            entry["reason_c3"] = (
                f"no mail in state∈{sorted(VALID_STATES)} (states={[m.get('state') for m in mails]})"
            )
            c3_fail.append(lid)

        # C4: at least one mail must be addressed to the expected recipient
        #     (mail.mail.email_to may embed multiple addresses)
        to_ok = any(
            EXPECTED_EMAIL_TO in (m.get("email_to") or "") for m in mails
        )
        entry["c4_ok"] = to_ok
        if not to_ok:
            entry["reason_c4"] = (
                f"no mail with email_to containing {EXPECTED_EMAIL_TO!r} "
                f"(email_to={[m.get('email_to') for m in mails]})"
            )
            c4_fail.append(lid)

        per_lead.append(entry)

    checks.append({
        "id": "C2",
        "name": f"each crm.lead has ≥1 mail.mail with subject containing '{OUR_SUBJECT_LITERAL}'",
        "ok": len(c2_fail) == 0,
        "detail": (
            f"pass={leads_found - len(c2_fail)}/{leads_found}"
            + (f" failing_lead_ids={c2_fail}" if c2_fail else "")
        ),
    })
    checks.append({
        "id": "C3",
        "name": f"each matching mail.mail state ∈ {sorted(VALID_STATES)}",
        "ok": len(c3_fail) == 0,
        "detail": (
            f"pass={leads_found - len(c3_fail)}/{leads_found}"
            + (f" failing_lead_ids={c3_fail}" if c3_fail else "")
        ),
    })
    checks.append({
        "id": "C4",
        "name": f"each matching mail.mail email_to contains {EXPECTED_EMAIL_TO!r}",
        "ok": len(c4_fail) == 0,
        "detail": (
            f"pass={leads_found - len(c4_fail)}/{leads_found}"
            + (f" failing_lead_ids={c4_fail}" if c4_fail else "")
        ),
    })

    # ---------- C5 ----------
    # mail.mail 의 res_id=False (NULL) 은 XML-RPC 상 False 로 반환된다.
    orphan_rows = cli.search_read(
        "mail.mail",
        [
            ("body_html", "like", f"%{MARKER}%"),
            ("res_id", "=", False),
        ],
        ["id", "subject", "state", "email_to", "model", "res_id"],
        order="id asc",
    )
    checks.append({
        "id": "C5",
        "name": f"no orphan mail.mail with '{MARKER}' marker and res_id IS NULL",
        "ok": len(orphan_rows) == 0,
        "detail": (
            f"orphan_count={len(orphan_rows)}"
            + (f" ids={[r['id'] for r in orphan_rows]}" if orphan_rows else "")
        ),
    })

    # ---- 부가 (informational, PASS/FAIL 에는 영향 없음) ----
    partner_linked = cli.search_read(
        "mail.mail",
        [
            ("body_html", "like", f"%{MARKER}%"),
            ("model", "=", "res.partner"),
        ],
        ["id"],
    )
    # cleanup(US-001) 이 아직 돌지 않았다면 22건 남아 있을 수 있음.
    # PRD 는 C5(res_id=NULL 0건) 만 hard gate 지만, 운영 관점에서 가시화.
    info_partner_orphans = len(partner_linked)

    summary = {
        "leads_expected": EXPECTED_LEADS,
        "leads_found": leads_found,
        "leads_with_expected_mail": leads_found - len(c2_fail),
        "leads_with_valid_state": leads_found - len(c3_fail),
        "leads_with_expected_email_to": leads_found - len(c4_fail),
        "orphan_mails_res_id_null": len(orphan_rows),
        "info_mails_linked_to_res_partner": info_partner_orphans,
        "total_checks": len(checks),
        "passed_checks": sum(1 for c in checks if c["ok"]),
        "failed_checks": sum(1 for c in checks if not c["ok"]),
    }

    return checks, {"summary": summary, "per_lead": per_lead, "orphan_rows": orphan_rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="JSON 결과 저장 경로. 기본: docs/99-demo-replay-verification.json",
    )
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    cli = OdooClient()
    cli.authenticate()
    print(f"[auth] uid={cli.uid} version={cli.version().get('server_version')}")

    checks, payload = run_checks(cli)
    summary = payload["summary"]

    print()
    for c in checks:
        flag = "PASS" if c["ok"] else "FAIL"
        print(f"  [{flag}] {c['id']} {c['name']}")
        print(f"         {c['detail']}")

    print()
    print(
        f"[summary] checks={summary['passed_checks']}/{summary['total_checks']} "
        f"leads={summary['leads_found']}/{summary['leads_expected']} "
        f"orphan_null_res_id={summary['orphan_mails_res_id_null']} "
        f"info_partner_linked={summary['info_mails_linked_to_res_partner']}"
    )

    if not args.no_write:
        out_path = args.output_json or (
            Path(__file__).resolve().parent.parent
            / "docs"
            / "99-demo-replay-verification.json"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "marker": MARKER,
            "expected_leads": EXPECTED_LEADS,
            "expected_subject_literal": OUR_SUBJECT_LITERAL,
            "expected_email_to": EXPECTED_EMAIL_TO,
            "valid_states": sorted(VALID_STATES),
            "summary": summary,
            "checks": checks,
            "per_lead": payload["per_lead"],
            "orphan_rows": payload["orphan_rows"],
        }
        out_path.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"[json] wrote {out_path}")

    return 0 if summary["failed_checks"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
