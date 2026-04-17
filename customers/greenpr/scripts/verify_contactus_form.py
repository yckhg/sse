"""Verify greenpr `/contactus` form builder action is "Create Opportunity".

US-005 (greenpr-form-automation PRD).

The website form snippet (`s_website_form`) stores the chosen action in the
`<form>` tag's `data-model_name` attribute:

  * `crm.lead`     → "Create Opportunity"   ← required for our automation
  * `mail.mail`    → "Send an Email"
  * `mailing.contact` → "Subscribe to Newsletter"
  * (anything else) → custom / other

Our `base.automation` rule (US-003) only fires when a `crm.lead` row is
created from the website form. If the form action is anything other than
"Create Opportunity" no lead is created and no email is sent.

This script:
  1. Authenticates against the greenpr Odoo via XML-RPC (stdlib only).
  2. Locates the `/contactus` website.page bound to the greenpr website.
  3. Reads the linked `ir.ui.view` arch and pulls the `<form id="contactus_form" …>`
     opening tag's attributes.
  4. Reports rc=0 if `data-model_name == "crm.lead"`, otherwise rc=1 with a
     manual-fix message (web UI cannot be edited from a script — Odoo's
     website builder is the canonical place to switch actions).

Return codes:
  * 0 = OK (form action is "Create Opportunity")
  * 1 = form action mismatch (manual fix required via website builder)
  * 2 = connection/auth error (Odoo unreachable or credentials invalid)

Run from the host (gateway port) or inside the container:

    python3 customers/greenpr/scripts/verify_contactus_form.py
    ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/verify_contactus_form.py
    docker exec ycerp-web-greenpr python3 /tmp/scripts/verify_contactus_form.py
"""

from __future__ import annotations

import re
import sys
from typing import Any

from odoo_client import OdooClient


CONTACTUS_URL = "/contactus"
EXPECTED_MODEL = "crm.lead"
ACTION_LABELS = {
    "crm.lead": "Create Opportunity",
    "mail.mail": "Send an Email",
    "mailing.contact": "Subscribe to Newsletter",
}
FORM_TAG_RE = re.compile(
    r'<form[^>]*\bid\s*=\s*"contactus_form"[^>]*>', re.IGNORECASE
)
DATA_MODEL_RE = re.compile(r'\bdata-model_name\s*=\s*"([^"]*)"', re.IGNORECASE)
DATA_SEND_TO_RE = re.compile(r'\bdata-send-email-to\s*=\s*"([^"]*)"', re.IGNORECASE)


def _pick_target_page(pages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the page whose binding most directly serves greenpr's /contactus.

    A website.page record bound to a specific `website_id` overrides the
    global default page (`website_id=False`). When both exist we prefer the
    bound one. When only the global page exists it is what visitors actually
    see.
    """
    if not pages:
        return None
    bound = [p for p in pages if p.get("website_id")]
    return bound[0] if bound else pages[0]


def _action_label(model_name: str | None) -> str:
    if not model_name:
        return "(no data-model_name attribute)"
    return ACTION_LABELS.get(model_name, f"Custom action → {model_name}")


def _print_manual_fix_instructions(current_label: str, current_model: str | None) -> None:
    print("")
    print("  Current action: " + current_label)
    if current_model:
        print(f"    (data-model_name=\"{current_model}\")")
    print("")
    print("  Required action: Create Opportunity (data-model_name=\"crm.lead\")")
    print("")
    print("  How to fix (manual, via Odoo Website Builder):")
    print("    1. Log in as admin at http://localhost:30033 (or https://greenpr.online).")
    print("    2. Navigate to /contactus.")
    print("    3. Click 'Edit' (top-right) to open the website builder.")
    print("    4. Click anywhere on the form, then in the right-hand panel set")
    print("       'Action' to 'Create an Opportunity'.")
    print("    5. Click 'Save'.")
    print("")
    print("  After saving, re-run this script to confirm.")
    print("")


def main() -> int:
    cli = OdooClient()
    print(f"target: url={cli.url} db={cli.db} login={cli.login}")

    try:
        cli.authenticate()
    except Exception as exc:
        print(
            f"[FAIL] Odoo 인증 실패: {exc} "
            f"(url={cli.url} db={cli.db} login={cli.login})",
            file=sys.stderr,
        )
        return 2

    pages = cli.search_read(
        "website.page",
        [("url", "=", CONTACTUS_URL)],
        ["id", "url", "name", "view_id", "website_id", "is_published"],
        order="website_id desc, id asc",
    )
    print(f"  website.page url={CONTACTUS_URL!r} -> {len(pages)} match(es)")
    for p in pages:
        print(
            f"    - page_id={p['id']} view={p['view_id']} "
            f"website={p['website_id']} published={p['is_published']}"
        )

    target = _pick_target_page(pages)
    if target is None:
        print("  FAIL: no website.page found for /contactus on this database.")
        print("  Manual check required: visit Website > Pages and confirm the contactus page exists.")
        return 1

    if not target.get("is_published"):
        print(f"  WARN: target page id={target['id']} is not published — visitors won't see it.")

    view_ref = target.get("view_id")
    if not view_ref:
        print(f"  FAIL: page id={target['id']} has no linked view_id.")
        return 1
    view_id = view_ref[0]

    view = cli.read("ir.ui.view", [view_id], ["id", "key", "name", "arch_db", "active"])[0]
    if not view.get("active"):
        print(f"  WARN: view id={view_id} key={view.get('key')!r} is inactive.")

    arch = view.get("arch_db") or ""
    form_match = FORM_TAG_RE.search(arch)
    if not form_match:
        print(f"  FAIL: <form id=\"contactus_form\" …> not found in view id={view_id}.")
        print("  The contactus page may have been customized away from the standard snippet.")
        return 1

    form_tag = form_match.group(0)
    model_match = DATA_MODEL_RE.search(form_tag)
    current_model = model_match.group(1) if model_match else None
    send_to_match = DATA_SEND_TO_RE.search(form_tag)
    send_to = send_to_match.group(1) if send_to_match else None

    if send_to:
        print(f"  detected data-send-email-to=\"{send_to}\" (Send Email recipient)")

    label = _action_label(current_model)

    if current_model == EXPECTED_MODEL:
        print(f"  OK: form action is \"{ACTION_LABELS[EXPECTED_MODEL]}\" "
              f"(data-model_name=\"{current_model}\").")
        print("  → base.automation rule (US-003) will receive on_create events from website form submits.")
        return 0

    print(f"  FAIL: form action is NOT \"Create Opportunity\".")
    _print_manual_fix_instructions(label, current_model)
    return 1


if __name__ == "__main__":
    sys.exit(main())
