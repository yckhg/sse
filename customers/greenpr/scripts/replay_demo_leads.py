"""US-002: 기존 22개 crm.lead 에 대해 `greenpr_form_automation.mail_template_lead_inquiry`
템플릿을 직접 호출해 `mail.mail` 을 재생성한다.

목적
----
PRD-2(greenpr-form-automation) 로 `/contactus` 폼 자동화가 구축되었지만,
기존 데모 crm.lead 22건은 그 자동화가 만들어지기 전에 생성되었기 때문에
mail.mail 이 연결되어 있지 않다(혹은 고아 mail.mail 만 있다).
본 스크립트는 각 lead 에 대해 `mail.template.send_mail(lead_id, force_send=True)`
를 호출하여 **crm.lead ↔ mail.mail 연결 + 실제 SMTP 발송** 을 달성한다.

사전 조건
---------
- US-001 `cleanup_demo_mails.py` 로 고아 mail.mail(model=res.partner,
  body_html 에 `ralph-demo-flow` 포함) 22건이 삭제되어 있어야 한다.
  (US-005 오케스트레이터가 순서를 보장한다.)

실행
----
    # 컨테이너 내부 (권장, 게이트웨이 타임아웃 회피)
    docker cp customers/greenpr/scripts/replay_demo_leads.py ycerp-web-greenpr:/tmp/
    docker exec ycerp-web-greenpr python3 /tmp/replay_demo_leads.py --dry-run
    docker exec ycerp-web-greenpr python3 /tmp/replay_demo_leads.py

    # 호스트 (게이트웨이 경유)
    ODOO_URL=http://localhost:30033 \
        python3 customers/greenpr/scripts/replay_demo_leads.py

인자
----
    --dry-run        실제 send 없이 계획만 출력
    --limit N        앞 N 건만 처리 (디버깅용)
    --log-path P     per-row 로그 append 경로. 기본: docs/lead-replay-log.md

출력
----
성공 시 rc=0, 요약 라인: `[summary] replayed=N skipped=M total=22`.
멱등: 재실행 시 replayed=0 skipped=22 (각 lead 에 이미 "견적 문의" mail.mail 존재).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odoo_client import OdooClient  # noqa: E402


MARKER = "ralph-demo-flow"
TEMPLATE_MODULE = "greenpr_form_automation"
TEMPLATE_NAME = "mail_template_lead_inquiry"

# 템플릿이 렌더하는 본문/제목에 반드시 포함되는 리터럴.
# 기존 고아 mail.mail(body: "성명 : {{ object.contact_name }}"), subject "견적문의_xxx"
# (띄어쓰기 없음) 과 구분하기 위해 공백 포함 형태로 매칭한다.
OUR_TEMPLATE_LITERAL = "견적 문의"


def _resolve_template_id(cli: OdooClient) -> int:
    rows = cli.search_read(
        "ir.model.data",
        [
            ("module", "=", TEMPLATE_MODULE),
            ("name", "=", TEMPLATE_NAME),
            ("model", "=", "mail.template"),
        ],
        ["res_id"],
        limit=1,
    )
    if not rows:
        raise RuntimeError(
            f"mail.template xml_id={TEMPLATE_MODULE}.{TEMPLATE_NAME} not found. "
            f"Is the {TEMPLATE_MODULE} addon installed in this tenant?"
        )
    return int(rows[0]["res_id"])


def _find_target_leads(cli: OdooClient) -> list[dict]:
    return cli.search_read(
        "crm.lead",
        [("description", "like", f"%{MARKER}%")],
        ["id", "name", "partner_name", "contact_name", "email_from"],
        order="id asc",
    )


def _already_replayed(cli: OdooClient, lead_id: int) -> int | None:
    """Return the mail.mail id from a previous replay, if any.

    A replay is identified by a mail.mail linked to (model=crm.lead,
    res_id=lead_id) whose body_html contains our template's literal
    `견적 문의` (with space). The pre-existing `견적문의_xxx` chatter
    mails from an unrelated automation use `견적문의` without space, so
    they won't false-match.
    """
    rows = cli.search_read(
        "mail.mail",
        [
            ("model", "=", "crm.lead"),
            ("res_id", "=", lead_id),
            ("body_html", "like", f"%{OUR_TEMPLATE_LITERAL}%"),
        ],
        ["id", "state"],
        order="id desc",
        limit=1,
    )
    if rows:
        return int(rows[0]["id"])
    return None


def _send(cli: OdooClient, template_id: int, lead_id: int) -> int:
    """Invoke mail.template.send_mail(lead_id, force_send=True), returning the new mail.mail id."""
    result = cli.execute_kw(
        "mail.template",
        "send_mail",
        [[template_id], lead_id],
        {"force_send": True},
    )
    if not isinstance(result, int):
        raise RuntimeError(
            f"mail.template.send_mail returned unexpected type {type(result).__name__}: {result!r}"
        )
    return int(result)


def _append_log(path: Path, rows: list[dict], replayed: int, skipped: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header_needed = not path.exists()
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []
    if header_needed:
        lines.append("# Lead Replay Log (US-002)\n")
        lines.append(
            "US-002 `replay_demo_leads.py` 실행 이력. 각 섹션은 1회 실행.\n"
        )
    lines.append(
        f"\n## {now} — replayed={replayed} skipped={skipped} total={len(rows)}\n"
    )
    lines.append(
        "| lead_id | partner | contact | mail.mail id | status | state | note |\n"
    )
    lines.append("|---|---|---|---|---|---|---|\n")
    for r in rows:
        lines.append(
            "| {lid} | {pname} | {cname} | {mid} | {st} | {state} | {note} |\n".format(
                lid=r["lead_id"],
                pname=r.get("partner_name") or "-",
                cname=r.get("contact_name") or "-",
                mid=r.get("mail_id") or "-",
                st=r["status"],
                state=r.get("state") or "-",
                note=r.get("note") or "",
            )
        )
    with path.open("a", encoding="utf-8") as f:
        f.writelines(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--log-path",
        type=Path,
        default=None,
        help="per-row 로그 경로. 기본: docs/lead-replay-log.md",
    )
    args = ap.parse_args()

    cli = OdooClient()
    cli.authenticate()
    print(f"[auth] uid={cli.uid} version={cli.version().get('server_version')}")

    template_id = _resolve_template_id(cli)
    print(f"[template] {TEMPLATE_MODULE}.{TEMPLATE_NAME} -> mail.template id={template_id}")

    leads = _find_target_leads(cli)
    if args.limit is not None:
        leads = leads[: args.limit]
    found = len(leads)
    print(f"[scan] crm.lead description LIKE '%{MARKER}%' -> found={found} (expected=22)")

    if args.dry_run:
        for lead in leads:
            already = _already_replayed(cli, lead["id"])
            tag = "skip" if already else "plan"
            print(
                f"  [{tag:>5}] lead id={lead['id']:>4}  partner={lead.get('partner_name')!r}  "
                f"contact={lead.get('contact_name')!r}  already_mail_id={already}"
            )
        print(f"[summary] dry-run target={found}")
        return 0

    replayed = 0
    skipped = 0
    log_rows: list[dict] = []
    for lead in leads:
        lid = int(lead["id"])
        existing = _already_replayed(cli, lid)
        if existing:
            print(
                f"  [skip] lead id={lid:>4} already has mail.mail id={existing} "
                f"matching {OUR_TEMPLATE_LITERAL!r} — idempotent skip"
            )
            log_rows.append({
                "lead_id": lid,
                "partner_name": lead.get("partner_name"),
                "contact_name": lead.get("contact_name"),
                "mail_id": existing,
                "status": "skipped",
                "state": None,
                "note": "existing mail.mail found",
            })
            skipped += 1
            continue

        mail_id = _send(cli, template_id, lid)
        mail_row = cli.read("mail.mail", [mail_id], ["id", "subject", "state", "email_to"])
        state = mail_row[0].get("state") if mail_row else None
        subject = mail_row[0].get("subject") if mail_row else ""
        print(
            f"  [ok]   lead id={lid:>4} -> mail.mail id={mail_id:>5} state={state!r} "
            f"subject={subject!r}"
        )
        log_rows.append({
            "lead_id": lid,
            "partner_name": lead.get("partner_name"),
            "contact_name": lead.get("contact_name"),
            "mail_id": mail_id,
            "status": "replayed",
            "state": state,
            "note": "",
        })
        replayed += 1

    print()
    print(f"[summary] replayed={replayed} skipped={skipped} total={found}")

    log_path = args.log_path or (
        Path(__file__).resolve().parent.parent / "docs" / "lead-replay-log.md"
    )
    try:
        _append_log(log_path, log_rows, replayed, skipped)
        print(f"[log] appended to {log_path}")
    except Exception as e:  # 로그 실패는 전체 실패로 만들지 않음
        print(f"[log] WARN: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
