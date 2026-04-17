"""US-001: 기존 `ralph-demo-flow` 마커 mail.mail 삭제.

22건의 고아 mail.mail(수동 state='sent', res_id=파트너) 을 제거하여
US-002 replay 가 생성할 신규 mail.mail 과 중복되지 않도록 한다.

실행:
    # dry-run (삭제 없이 plan)
    ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/cleanup_demo_mails.py --dry-run
    # live
    ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/cleanup_demo_mails.py

인자:
    --dry-run    unlink 없이 삭제 대상 출력만
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odoo_client import OdooClient  # noqa: E402


MARKER = "ralph-demo-flow"
MAIL_DOMAIN = [["body_html", "like", f"%{MARKER}%"]]
FIELDS = ["id", "subject", "email_to", "state", "res_id", "model", "body_html"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cli = OdooClient()
    cli.authenticate()
    print(f"[auth] uid={cli.uid} version={cli.version().get('server_version')}")

    rows = cli.search_read("mail.mail", MAIL_DOMAIN, FIELDS, order="id asc")
    found = len(rows)
    print(f"[scan] mail.mail LIKE '%{MARKER}%' -> found={found} (expected=22)")

    # 안전장치: 혹시라도 도메인 오매칭으로 엉뚱한 레코드가 섞였다면 거부.
    for r in rows:
        if MARKER not in (r.get("body_html") or ""):
            print(
                f"[abort] mail.mail id={r['id']} body_html 에 {MARKER!r} 가 없음 — 매칭 이상, 삭제 거부",
                file=sys.stderr,
            )
            return 2

    # 요약 출력 (ids / email_to / state)
    for r in rows:
        print(
            f"  id={r['id']:>5}  state={r['state']:<9}  email_to={r['email_to']!r:<40}  "
            f"model={r['model']}  res_id={r['res_id']}  subject={r['subject']!r}"
        )

    if args.dry_run:
        print(f"[summary] dry-run target={found}")
        return 0

    if not rows:
        print("[summary] deleted=0 skipped=0")
        return 0

    ids = [r["id"] for r in rows]
    cli.unlink("mail.mail", ids)
    print(f"[summary] deleted={len(ids)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
