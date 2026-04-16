"""US-005: 문의하기(Inquiry) 이메일을 mail.mail 레코드로 생성.

전체 플로우(문의 → CRM → 견적 → 청구 → 매입)의 첫 단계.
`docs/01-inquiry.md` 에 기재된 방식 C (mail.mail create + state='sent' 수동).

실행:
    # 컨테이너 내부
    python3 /tmp/send_inquiries.py
    # 호스트 (게이트웨이 경유)
    ODOO_URL=http://localhost:30033 python3 customers/greenpr/scripts/send_inquiries.py

인자:
    --dry-run          생성하지 않고 계획만 출력
    --limit N          앞 N 건만 처리
    --partners-json P  기본: 스크립트 옆 ../docs/target-partners.json
    --products-json P  기본: 스크립트 옆 ../docs/products.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odoo_client import OdooClient  # noqa: E402


INTERNAL_TO = "greenpr9@gmail.com"
FALLBACK_FROM = "inquiry-noreply@greenpr.local"
MAIL_SERVER_ID = 4
TENANT_KEY = "greenpr"
MARKER_PREFIX = "ralph-demo-flow id="
SEED = 20260416


_CONTAINER_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def container_name_arg(value: str) -> str:
    """argparse ``type=`` validator for docker container names.

    Enforces a strict allowlist so shell metacharacters (``;``, ``&&``,
    spaces, quotes, ``$``, etc.) can never reach ``docker exec`` even if
    the CLI arg is later wired to untrusted input. argparse converts the
    raised ``ArgumentTypeError`` into an ``rc=2`` exit before any
    subprocess runs.
    """
    if not _CONTAINER_NAME_RE.match(value):
        raise argparse.ArgumentTypeError(
            f"invalid docker container name: {value!r}; "
            "must match ^[a-zA-Z0-9_-]+$"
        )
    return value


QUANTITY_POOL = [
    (2, 1), (3, 2), (5, 3), (10, 3), (20, 2), (50, 1),
]  # (수량, 가중치)


DELIVERY_OFFSETS_DAYS = [5, 7, 10, 14, 21]


TONE_TEMPLATES = [
    (
        "{partner_name} 담당자입니다. 홈페이지 보고 연락드립니다. "
        "{product_name} 약 {qty}개 정도 주문하려 하는데 단가와 납기 알려주시면 감사하겠습니다. "
        "희망 납기일은 {delivery}입니다. 회신 부탁드립니다."
    ),
    (
        "안녕하세요, {partner_name}입니다. {product_name} 견적을 요청드립니다. "
        "수량은 {qty}개 내외로 예상하며, {delivery}까지 수령 가능한지 확인 부탁드립니다. "
        "추가 문의사항 있으시면 회신 주세요."
    ),
    (
        "{partner_name}에서 행사용으로 {product_name} 구매를 검토 중입니다. "
        "약 {qty}개 기준 견적과 납기(희망 {delivery})를 함께 회신해주시면 내부 품의 후 정식 발주 드리겠습니다. "
        "감사합니다."
    ),
]


def weighted_choice(pool, rng):
    total = sum(w for _, w in pool)
    r = rng.random() * total
    acc = 0
    for val, w in pool:
        acc += w
        if r <= acc:
            return val
    return pool[-1][0]


def find_docs_path(name: str) -> Path:
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "docs" / name,          # customers/greenpr/docs/
        Path("/tmp") / name,                  # docker cp 시
        Path.cwd() / "docs" / name,
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"{name} not found in any of: {candidates}")


def load_partners(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data["target_partners"]


def load_products(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    top = data.get("recent_top_products") or []
    if not top:
        top = data.get("sample", [])[:9]
    return top


def build_subject(product_name: str, partner_name: str) -> str:
    return f"[문의] {product_name} 견적 문의 - {partner_name}"


def build_body_html(
    partner: dict, product: dict, qty: int, planned_date: str, tone_idx: int
) -> tuple[str, str]:
    planned_dt = dt.date.fromisoformat(planned_date)
    offset = DELIVERY_OFFSETS_DAYS[tone_idx % len(DELIVERY_OFFSETS_DAYS)]
    delivery_dt = planned_dt + dt.timedelta(days=offset)
    delivery_str = delivery_dt.strftime("%Y-%m-%d")

    template = TONE_TEMPLATES[tone_idx % len(TONE_TEMPLATES)]
    text = template.format(
        partner_name=partner["partner_name"],
        product_name=product["name"],
        qty=qty,
        delivery=delivery_str,
    )
    marker_val = f"{TENANT_KEY}:{partner['partner_id']}:{planned_date}"
    body_html = (
        f"<p>{html.escape(text)}</p>"
        f"<hr/>"
        f"<p style='color:#888;font-size:12px;'>문의 접수: {planned_date} / "
        f"파트너 id={partner['partner_id']} / 제품 id={product['id']}</p>"
        f"<!-- {MARKER_PREFIX}{marker_val} -->"
    )
    return body_html, marker_val


def already_exists(cli: OdooClient, marker_val: str) -> list[int]:
    # 접미 ` -->` 를 포함해 HTML 주석 종단을 앵커 — `:1:...` 가 `:10:...` 에 섞이지 않는다.
    needle = f"{MARKER_PREFIX}{marker_val} -->"
    return cli.search("mail.mail", [["body_html", "like", needle]])


def plan_flows(partners: list[dict], products: list[dict]) -> list[dict]:
    """파트너 × 2건 → 22건 flow. 제품·수량 결정. 재현 가능 (seed 고정)."""
    rng = random.Random(SEED)
    flows = []
    for p in partners:
        for idx, date_iso in enumerate(p["planned_dates"]):
            product = products[(p["partner_id"] + idx) % len(products)]
            qty = weighted_choice(QUANTITY_POOL, rng)
            tone_idx = (p["partner_id"] + idx) % len(TONE_TEMPLATES)
            email_from = p.get("email") or FALLBACK_FROM
            flows.append({
                "partner_id": p["partner_id"],
                "partner_name": p["partner_name"],
                "planned_date": date_iso,
                "product_id": product["id"],
                "product_name": product["name"],
                "qty": qty,
                "tone_idx": tone_idx,
                "email_from": email_from,
            })
    return flows


def render_body(partner: dict, flow: dict) -> tuple[str, str]:
    product_stub = {"id": flow["product_id"], "name": flow["product_name"]}
    return build_body_html(
        partner=partner,
        product=product_stub,
        qty=flow["qty"],
        planned_date=flow["planned_date"],
        tone_idx=flow["tone_idx"],
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--partners-json", type=Path, default=None)
    ap.add_argument("--products-json", type=Path, default=None)
    ap.add_argument(
        "--log-path", type=Path, default=None,
        help="inquiry-log.md 경로. 기본: docs/inquiry-log.md",
    )
    args = ap.parse_args()

    partners_path = args.partners_json or find_docs_path("target-partners.json")
    products_path = args.products_json or find_docs_path("products.json")
    partners = load_partners(partners_path)
    products = load_products(products_path)

    partners_by_id = {p["partner_id"]: p for p in partners}
    flows = plan_flows(partners, products)
    if args.limit is not None:
        flows = flows[: args.limit]

    print(f"[plan] partners={len(partners)} products={len(products)} flows={len(flows)}")

    if args.dry_run:
        for f in flows:
            print(
                f"  {f['planned_date']}  partner_id={f['partner_id']:>4}  "
                f"product_id={f['product_id']:>4}  qty={f['qty']:>3}  tone={f['tone_idx']}  "
                f"name={f['partner_name']}"
            )
        return 0

    cli = OdooClient()
    cli.authenticate()
    print(f"[auth] uid={cli.uid} version={cli.version().get('server_version')}")

    created = 0
    skipped = 0
    log_rows = []
    for f in flows:
        partner = partners_by_id[f["partner_id"]]
        body_html, marker_val = render_body(partner, f)
        existing = already_exists(cli, marker_val)
        if existing:
            print(f"  [skip] marker={marker_val} exists -> mail.mail {existing}")
            log_rows.append({
                **f,
                "mail_mail_id": existing[0],
                "status": "skipped",
                "marker": marker_val,
            })
            skipped += 1
            continue

        subject = build_subject(f["product_name"], f["partner_name"])
        vals = {
            "subject": subject,
            "body_html": body_html,
            "email_from": f["email_from"],
            "email_to": INTERNAL_TO,
            "reply_to": f["email_from"],
            "mail_server_id": MAIL_SERVER_ID,
            "message_type": "email",
            "model": "res.partner",
            "res_id": f["partner_id"],
            "auto_delete": False,
        }
        mail_id = cli.create("mail.mail", vals)
        # send 없이 상태만 sent 로 마킹 → 외부 SMTP 실제 발송 회피
        cli.write("mail.mail", [mail_id], {"state": "sent"})
        print(
            f"  [ok]   mail.mail id={mail_id:>5}  partner_id={f['partner_id']:>4}  "
            f"date={f['planned_date']}  subject={subject}"
        )
        log_rows.append({
            **f,
            "mail_mail_id": mail_id,
            "status": "created",
            "marker": marker_val,
        })
        created += 1

    print()
    print(f"[summary] created={created} skipped={skipped} total={len(flows)}")

    log_path = args.log_path or (Path(__file__).resolve().parent.parent / "docs" / "inquiry-log.md")
    try:
        append_log(log_path, log_rows, created, skipped)
        print(f"[log] appended to {log_path}")
    except Exception as e:  # 로그 실패는 전체 실패로 만들지 않음
        print(f"[log] WARN: {e}", file=sys.stderr)

    return 0


def append_log(path: Path, rows: list[dict], created: int, skipped: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header_needed = not path.exists()
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    if header_needed:
        lines.append("# Inquiry Log (US-005)\n")
        lines.append(
            "US-005 `send_inquiries.py` 실행 이력. 각 섹션은 1회 실행.\n"
        )
    lines.append(f"\n## {now} — created={created} skipped={skipped} total={len(rows)}\n")
    lines.append(
        "| mail.mail id | partner_id | partner | date | product_id | qty | status | marker |\n"
    )
    lines.append("|---|---|---|---|---|---|---|---|\n")
    for r in rows:
        lines.append(
            "| {mid} | {pid} | {pname} | {d} | {prod} | {qty} | {st} | {mk} |\n".format(
                mid=r.get("mail_mail_id", "-"),
                pid=r["partner_id"],
                pname=r["partner_name"],
                d=r["planned_date"],
                prod=r["product_id"],
                qty=r["qty"],
                st=r["status"],
                mk=r["marker"],
            )
        )
    with path.open("a", encoding="utf-8") as f:
        f.writelines(lines)


if __name__ == "__main__":
    sys.exit(main())
