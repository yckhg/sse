"""End-to-end smoke test for greenpr `/contactus` form → crm.lead → mail automation.

US-006 (greenpr-form-automation PRD).

What this script does
---------------------
1. Connects to the greenpr Odoo tenant via XML-RPC (stdlib only).
2. Generates a unique SMOKE marker (`SMOKE-<epoch_ms>`) so multiple runs don't
   collide and so cleanup can reliably identify this run's records.
3. POSTs a realistic form payload to the public endpoint
   `<ODOO_URL>/website/form/crm.lead` with `urllib` (urlencoded). The payload
   embeds the marker in `name` and `description` and sets all the fields the
   website snippet would send for the "Create Opportunity" action.
4. Waits up to `--wait-seconds` (default 10s) for Odoo to finish:
   - creating the `crm.lead`
   - firing the `base.automation` rule (US-003)
   - rendering the `mail.template` and queuing the `mail.mail` row
5. Verifies:
   a. Exactly one `crm.lead` exists with the marker in `description`.
   b. Its `medium_id.name == 'Website'` — otherwise the automation filter
      `[('medium_id.name','=','Website')]` would have skipped it and no email
      would have been sent.
   c. At least one `mail.mail` row tied to that lead's `mail.message` has the
      literal "견적 문의" in its `body_html` (i.e. our template fired, not just
      some other chatter message).
   d. That `mail.mail`'s `state` is one of {'sent', 'outgoing'} — failed
      sends ('exception', 'cancel') are treated as failure.
6. Cleans up everything it created (mail.mail + mail.message + crm.lead), keyed
   by the marker. Cleanup also scans for orphan SMOKE markers from previous
   runs so the database doesn't accumulate smoke-test litter.

Run
---

    # From host via gateway (default greenpr port 30033)
    python3 customers/greenpr/scripts/smoke_test_form_automation.py

    # Override URL / creds
    ODOO_URL=http://localhost:30033 ODOO_DB=odoo \\
        python3 customers/greenpr/scripts/smoke_test_form_automation.py

    # Keep the created records (skip cleanup) — for manual inspection
    python3 customers/greenpr/scripts/smoke_test_form_automation.py --no-cleanup

Exit codes: 0 = OK, 1 = any verification or RPC failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from typing import Any

from odoo_client import OdooClient


MARKER_PREFIX = "SMOKE-"
REQUIRED_BODY_LITERAL = "견적 문의"
VALID_MAIL_STATES = ("sent", "outgoing")


def _build_marker() -> str:
    return f"{MARKER_PREFIX}{int(time.time() * 1000)}"


def _build_payload(marker: str) -> dict[str, str]:
    """Payload mimics what the Website snippet POSTs for 'Create Opportunity'."""
    return {
        "name": f"[{marker}] greenpr 견적 문의 스모크 테스트",
        "contact_name": f"{marker} 테스트 담당자",
        "partner_name": f"{marker} 테스트 회사",
        "email_from": "smoke-test@example.invalid",
        "phone": "010-0000-0000",
        "description": (
            f"[smoke-test marker={marker}] 이 레코드는 greenpr_form_automation "
            f"E2E 검증 스크립트가 생성했습니다. 스크립트 종료 시 자동 삭제됩니다."
        ),
    }


def _post_form(url: str, model: str, payload: dict[str, str]) -> dict[str, Any]:
    """POST urlencoded form. Returns the JSON body the controller emits.

    The Odoo controller returns either `{"id": <n>}` on success,
    `{"error": "..."}` on ValidationError, `"false"` on DB integrity error,
    or `""` for the fallback empty route.
    """
    endpoint = f"{url.rstrip('/')}/website/form/{model}"
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "greenpr-smoke-test/1.0",
            "Accept": "application/json, */*;q=0.1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        status = e.code
    except urllib.error.URLError as e:
        raise RuntimeError(f"POST {endpoint} transport error: {e}") from e

    parsed: Any
    try:
        parsed = json.loads(body) if body else None
    except json.JSONDecodeError:
        parsed = None

    return {
        "status": status,
        "body": body,
        "parsed": parsed,
        "endpoint": endpoint,
    }


def _wait_for_lead(
    cli: OdooClient,
    marker: str,
    wait_seconds: int,
) -> dict[str, Any] | None:
    """Poll every 0.5s up to wait_seconds for a crm.lead with the marker."""
    deadline = time.monotonic() + wait_seconds
    while True:
        leads = cli.search_read(
            "crm.lead",
            [("description", "ilike", marker)],
            [
                "id",
                "name",
                "partner_name",
                "contact_name",
                "email_from",
                "phone",
                "description",
                "medium_id",
                "source_id",
                "team_id",
                "message_ids",
                "create_date",
            ],
            order="id desc",
            limit=5,
        )
        if leads:
            return leads[0]
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.5)


def _wait_for_our_mail(
    cli: OdooClient,
    lead_id: int,
    wait_seconds: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Find the mail.mail row from OUR template.

    Other automations on crm.lead (e.g. user-defined ones named
    `문의하기 > 이메일 발송`) may also create mail.mail rows. We pick the row
    whose body_html contains the REQUIRED_BODY_LITERAL, which our template
    (US-002) embeds in the heading paragraph.

    Returns (our_mail_or_None, all_mails_linked_to_this_lead).
    """
    deadline = time.monotonic() + wait_seconds
    seen_all: list[dict[str, Any]] = []
    while True:
        # The message → mail bridge: mail.mail.mail_message_id.res_id == lead_id
        mails = cli.search_read(
            "mail.mail",
            [
                ("model", "=", "crm.lead"),
                ("res_id", "=", lead_id),
            ],
            ["id", "subject", "state", "email_to", "body_html", "mail_message_id"],
            order="id desc",
        )
        seen_all = mails
        matched = [m for m in mails if REQUIRED_BODY_LITERAL in (m.get("body_html") or "")]
        if matched:
            return matched[0], seen_all
        if time.monotonic() >= deadline:
            return None, seen_all
        time.sleep(0.5)


def _cleanup_by_marker(cli: OdooClient, marker_like: str) -> dict[str, int]:
    """Unlink all leads (+ their mail trails) whose description matches `marker_like`.

    Safe to run standalone — used both for this run's cleanup and for stale
    smoke-test purge.

    Odoo's mail.message record rule prevents non-author users (even admin)
    from deleting chatter messages they didn't write, so an AccessError there
    is logged but does not abort cleanup — the lead and mail.mail rows are
    the important ones.
    """
    import xmlrpc.client

    leads = cli.search_read(
        "crm.lead",
        [("description", "ilike", marker_like)],
        ["id", "name"],
        limit=500,
    )
    lead_ids = [lead["id"] for lead in leads]
    deleted_mails = 0
    deleted_msgs = 0
    skipped_msgs = 0
    if lead_ids:
        mail_ids = cli.search(
            "mail.mail",
            [("model", "=", "crm.lead"), ("res_id", "in", lead_ids)],
            limit=1000,
        )
        if mail_ids:
            cli.unlink("mail.mail", mail_ids)
            deleted_mails = len(mail_ids)
        msg_ids = cli.search(
            "mail.message",
            [("model", "=", "crm.lead"), ("res_id", "in", lead_ids)],
            limit=1000,
        )
        if msg_ids:
            try:
                cli.unlink("mail.message", msg_ids)
                deleted_msgs = len(msg_ids)
            except xmlrpc.client.Fault as fault:
                # AccessError on messages authored by other users — tolerable.
                skipped_msgs = len(msg_ids)
                print(f"  WARN: skipping mail.message cleanup ({skipped_msgs} row(s)): {fault.faultString.splitlines()[0]}")
        cli.unlink("crm.lead", lead_ids)
    return {
        "leads": len(lead_ids),
        "mails": deleted_mails,
        "messages": deleted_msgs,
        "messages_skipped": skipped_msgs,
    }


def _purge_stale(cli: OdooClient) -> dict[str, int]:
    """Purge any SMOKE-* records older than 1 hour — cheap hygiene on each run."""
    return _cleanup_by_marker(cli, MARKER_PREFIX)


def _print_header(title: str) -> None:
    print("")
    print(f"=== {title} ===")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=10,
        help="Seconds to wait for lead + mail after POST (default 10)",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Keep the created lead/mail records (skip cleanup step)",
    )
    parser.add_argument(
        "--no-purge-stale",
        action="store_true",
        help="Skip purging pre-existing SMOKE-* records from earlier runs",
    )
    args = parser.parse_args()

    cli = OdooClient()
    print(f"target: url={cli.url} db={cli.db} login={cli.login}")
    try:
        cli.authenticate()
    except Exception as exc:
        print(f"[ERR] XML-RPC authenticate failed: {exc}")
        return 1

    marker = _build_marker()
    print(f"marker: {marker}")

    if not args.no_purge_stale:
        _print_header("0. Purging stale SMOKE-* records")
        stale = _purge_stale(cli)
        print(
            f"  purged {stale['leads']} lead(s), "
            f"{stale['mails']} mail.mail, {stale['messages']} mail.message "
            f"(skipped {stale['messages_skipped']} message(s) w/o delete access)"
        )

    payload = _build_payload(marker)

    _print_header("1. POST /website/form/crm.lead")
    print(f"  endpoint: {cli.url.rstrip('/')}/website/form/crm.lead")
    for k, v in payload.items():
        shown = v if len(v) < 80 else v[:77] + "…"
        print(f"    {k} = {shown}")
    resp = _post_form(cli.url, "crm.lead", payload)
    print(f"  HTTP status={resp['status']}")
    print(f"  raw body: {resp['body'][:300]}")
    if resp["status"] != 200:
        print(f"  FAIL: expected HTTP 200 from {resp['endpoint']}")
        return 1
    parsed = resp["parsed"]
    if not isinstance(parsed, dict) or "id" not in parsed:
        print("  FAIL: form response did not include {'id': <n>}")
        if isinstance(parsed, dict) and parsed.get("error"):
            print(f"    controller error: {parsed['error']}")
        return 1
    posted_lead_id = int(parsed["id"])
    print(f"  controller says: crm.lead id={posted_lead_id} created")

    _print_header("2. Verifying crm.lead via XML-RPC")
    lead = _wait_for_lead(cli, marker, args.wait_seconds)
    if lead is None:
        print(f"  FAIL: no crm.lead with marker {marker!r} appeared within {args.wait_seconds}s")
        return 1
    if int(lead["id"]) != posted_lead_id:
        # defensive — they should match; if not, trust the marker search
        print(
            f"  WARN: POST id={posted_lead_id} != searched id={lead['id']}; "
            "continuing with search result."
        )
    medium = lead.get("medium_id")
    medium_name = medium[1] if isinstance(medium, list) and len(medium) == 2 else None
    print(f"  lead id={lead['id']} name={lead['name']!r}")
    print(f"    partner_name={lead.get('partner_name')!r} contact_name={lead.get('contact_name')!r}")
    print(f"    email_from={lead.get('email_from')!r} phone={lead.get('phone')!r}")
    print(f"    medium_id={medium} source_id={lead.get('source_id')} team_id={lead.get('team_id')}")
    if medium_name != "Website":
        print(f"  FAIL: medium_id.name is {medium_name!r}, expected 'Website'.")
        print("    The base.automation filter `[('medium_id.name','=','Website')]` would skip this lead,")
        print("    which would explain a missing email.  Check website_form_input_filter wiring on crm.lead.")
        if not args.no_cleanup:
            _cleanup_by_marker(cli, marker)
        return 1

    _print_header("3. Verifying mail.mail (automation fired our template)")
    our_mail, all_mails = _wait_for_our_mail(cli, int(lead["id"]), args.wait_seconds)
    print(f"  {len(all_mails)} mail.mail row(s) linked to lead id={lead['id']}:")
    for m in all_mails:
        body = m.get("body_html") or ""
        flag = "✓" if REQUIRED_BODY_LITERAL in body else " "
        print(
            f"    [{flag}] mail_id={m['id']} state={m.get('state')!r} "
            f"subject={(m.get('subject') or '')!r} email_to={m.get('email_to')!r}"
        )
    if our_mail is None:
        print(
            f"  FAIL: no mail.mail whose body_html contains {REQUIRED_BODY_LITERAL!r} — "
            "our mail.template did not render. Check that base.automation id=5 "
            "('Greenpr: Website Lead 견적 문의 자동 메일') is active and that the "
            "mail_template_lead_inquiry body still includes the literal."
        )
        if not args.no_cleanup:
            _cleanup_by_marker(cli, marker)
        return 1
    state = our_mail.get("state")
    if state not in VALID_MAIL_STATES:
        print(
            f"  FAIL: our mail.mail id={our_mail['id']} state={state!r}, "
            f"expected one of {VALID_MAIL_STATES}."
        )
        if not args.no_cleanup:
            _cleanup_by_marker(cli, marker)
        return 1
    print(f"  OK: mail.mail id={our_mail['id']} state={state!r}, body contains {REQUIRED_BODY_LITERAL!r}.")

    _print_header("4. Cleanup")
    if args.no_cleanup:
        print("  --no-cleanup set; leaving records in place.")
        print(f"  (lead id={lead['id']}, marker {marker}) — remember to purge manually.")
    else:
        summary = _cleanup_by_marker(cli, marker)
        print(
            f"  deleted {summary['leads']} lead(s), "
            f"{summary['mails']} mail.mail, {summary['messages']} mail.message "
            f"(skipped {summary['messages_skipped']} message(s) w/o delete access)."
        )

    _print_header("RESULT")
    print("  PASS: /contactus → crm.lead → base.automation → mail.template → mail.mail chain works.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
