"""US-011: greenpr Odoo 테넌트의 전체 데모 플로우(문의 → CRM → 견적 → 청구 → 매입)를
하나의 스크립트로 오케스트레이션한다. 각 단계는 `customers/<tenant>/scripts/` 아래의
기존 5개 스테이지 스크립트(US-005~US-009)를 subprocess 로 호출한다.

PRD AC 구조:
    --tenant              테넌트 이름 (greenpr, mediapolytech, ...)
    --days-back           기본 30 (target-partners.json 재생성 시 참조, 현재는 정보성)
    --flows-per-partner   기본 2 (target-partners.json 재생성 시 참조, 현재는 정보성)
    --dry-run             실제 INSERT 없이 각 단계의 plan 만 출력

각 단계 함수:
    send_inquiry(cfg, dry_run) → StageResult     # US-005
    create_lead(cfg, dry_run)  → StageResult     # US-006
    create_quote(cfg, dry_run) → StageResult     # US-007
    create_invoice(cfg, dry_run)→ StageResult    # US-008
    create_po(cfg, dry_run)    → StageResult     # US-009

실행:
    # 호스트에서 (게이트웨이 포트 자동 매핑)
    python3 scripts/generate-full-flow.py --tenant greenpr
    python3 scripts/generate-full-flow.py --tenant greenpr --dry-run

로그:
    customers/<tenant>/docs/execution-log-YYYY-MM-DD.md (자동 append)
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


# customers/<tenant>/CLAUDE.md 및 sse/CLAUDE.md 의 포트 매핑과 일치해야 함.
TENANT_CONFIG: dict[str, dict] = {
    "greenpr":       {"port": 30033, "web": "ycerp-web-greenpr",       "db": "ycerp-db-greenpr"},
    "mediapolytech": {"port": 30043, "web": "ycerp-web-mediapolytech", "db": "ycerp-db-mediapolytech"},
    "visualoft":     {"port": 30053, "web": "ycerp-web-visualoft",     "db": "ycerp-db-visualoft"},
    "jnj_i":         {"port": 30063, "web": "ycerp-web-jnj_i",         "db": "ycerp-db-jnj_i"},
    "freeworks":     {"port": 30073, "web": "ycerp-web-freeworks",     "db": "ycerp-db-freeworks"},
}


STAGES = [
    # (step_key, label, script_name, extra_args_builder)
    ("inquiry",  "US-005 문의(mail.mail)",      "send_inquiries.py",        lambda cfg: []),
    ("lead",     "US-006 CRM 영업건(crm.lead)", "create_leads.py",          lambda cfg: []),
    ("quote",    "US-007 견적서(sale.order)",   "create_sale_orders.py",    lambda cfg: ["--db-container", cfg.db_container]),
    ("invoice",  "US-008 청구서(account.move)", "create_invoices.py",       lambda cfg: []),
    ("po",       "US-009 매입발주(purchase.order)", "create_purchase_orders.py", lambda cfg: []),
]


@dataclass
class TenantConfig:
    tenant: str
    port: int
    web_container: str
    db_container: str
    odoo_url: str
    project_root: Path
    scripts_dir: Path
    docs_dir: Path

    @classmethod
    def resolve(cls, tenant: str, project_root: Path) -> "TenantConfig":
        if tenant not in TENANT_CONFIG:
            raise SystemExit(
                f"[err] unknown tenant '{tenant}'. known: {sorted(TENANT_CONFIG)}"
            )
        t = TENANT_CONFIG[tenant]
        tenant_dir = project_root / "customers" / tenant
        scripts_dir = tenant_dir / "scripts"
        docs_dir = tenant_dir / "docs"
        if not scripts_dir.is_dir():
            raise SystemExit(
                f"[err] {scripts_dir} missing. 스테이지 스크립트가 없으면 오케스트레이션 불가.\n"
                f"      greenpr 외 테넌트는 US-005~US-009 스크립트를 먼저 이식해야 함."
            )
        return cls(
            tenant=tenant,
            port=t["port"],
            web_container=t["web"],
            db_container=t["db"],
            odoo_url=f"http://localhost:{t['port']}",
            project_root=project_root,
            scripts_dir=scripts_dir,
            docs_dir=docs_dir,
        )


@dataclass
class StageResult:
    step: str
    label: str
    cmd: list[str]
    returncode: int
    duration_sec: float
    stdout_tail: str
    stderr_tail: str
    summary: str = ""
    created: int | None = None
    skipped: int | None = None
    total: int | None = None


def tail(text: str, lines: int = 40) -> str:
    if not text:
        return ""
    out = text.rstrip().splitlines()
    return "\n".join(out[-lines:])


def parse_summary(stdout: str) -> tuple[int | None, int | None, int | None, str]:
    """각 스테이지 스크립트가 `[summary] created=.. skipped=.. total=..` 를 표준으로 찍는다.
    그 줄을 추출해 숫자와 원문 한 줄 둘 다 반환."""
    created = skipped = total = None
    summary_line = ""
    for line in reversed(stdout.splitlines()):
        if "[summary]" in line:
            summary_line = line.strip()
            for tok in line.split():
                if "=" not in tok:
                    continue
                k, _, v = tok.partition("=")
                try:
                    n = int(v)
                except ValueError:
                    continue
                if k == "created":
                    created = n
                elif k == "skipped":
                    skipped = n
                elif k == "total":
                    total = n
            break
    return created, skipped, total, summary_line


def run_stage(
    cfg: TenantConfig,
    step: str,
    label: str,
    script_name: str,
    extra_args: list[str],
    dry_run: bool,
) -> StageResult:
    script_path = cfg.scripts_dir / script_name
    if not script_path.is_file():
        raise SystemExit(f"[err] stage script missing: {script_path}")

    cmd = [sys.executable, str(script_path)]
    if dry_run:
        cmd.append("--dry-run")
    cmd.extend(extra_args)

    env = os.environ.copy()
    env.setdefault("ODOO_URL", cfg.odoo_url)
    env.setdefault("ODOO_DB", "odoo")
    env.setdefault("ODOO_LOGIN", "admin")
    env.setdefault("ODOO_PASSWORD", "admin")
    env["PYTHONUNBUFFERED"] = "1"

    print(f"\n========== [{step}] {label} ==========")
    print(f"$ ODOO_URL={cfg.odoo_url} " + " ".join(cmd))
    t0 = time.time()
    # 스테이지 출력이 그대로 콘솔에 흘러나오도록 capture + mirror.
    # stdout/stderr 를 각각 별도 스레드로 스트리밍 소비 — 한쪽 PIPE 버퍼(~64KB)가 포화되어
    # 자식이 write 에서 블록되는 상황을 피한다. (예전엔 stdout 만 drain 하고 wait 후 stderr
    # 를 read 했기 때문에 stderr 대량 로그 시 데드락 가능성이 있었음.)
    proc = subprocess.Popen(
        cmd,
        cwd=str(cfg.project_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None and proc.stderr is not None

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _pump(src, mirror, buf: list[str]) -> None:
        for line in src:
            mirror.write(line)
            mirror.flush()
            buf.append(line)
        src.close()

    t_out = threading.Thread(
        target=_pump, args=(proc.stdout, sys.stdout, stdout_lines), daemon=True
    )
    t_err = threading.Thread(
        target=_pump, args=(proc.stderr, sys.stderr, stderr_lines), daemon=True
    )
    t_out.start()
    t_err.start()
    proc.wait()
    t_out.join()
    t_err.join()

    duration = time.time() - t0
    stdout_full = "".join(stdout_lines)
    stderr_full = "".join(stderr_lines)
    created, skipped, total, summary_line = parse_summary(stdout_full)

    return StageResult(
        step=step,
        label=label,
        cmd=cmd,
        returncode=proc.returncode,
        duration_sec=duration,
        stdout_tail=tail(stdout_full, 40),
        stderr_tail=tail(stderr_full, 20),
        summary=summary_line,
        created=created,
        skipped=skipped,
        total=total,
    )


# --- PRD-required stage functions (public API) ------------------------------


def send_inquiry(cfg: TenantConfig, dry_run: bool) -> StageResult:
    step, label, script, build = STAGES[0]
    return run_stage(cfg, step, label, script, build(cfg), dry_run)


def create_lead(cfg: TenantConfig, dry_run: bool) -> StageResult:
    step, label, script, build = STAGES[1]
    return run_stage(cfg, step, label, script, build(cfg), dry_run)


def create_quote(cfg: TenantConfig, dry_run: bool) -> StageResult:
    step, label, script, build = STAGES[2]
    return run_stage(cfg, step, label, script, build(cfg), dry_run)


def create_invoice(cfg: TenantConfig, dry_run: bool) -> StageResult:
    step, label, script, build = STAGES[3]
    return run_stage(cfg, step, label, script, build(cfg), dry_run)


def create_po(cfg: TenantConfig, dry_run: bool) -> StageResult:
    step, label, script, build = STAGES[4]
    return run_stage(cfg, step, label, script, build(cfg), dry_run)


STAGE_FUNCS = [send_inquiry, create_lead, create_quote, create_invoice, create_po]


# --- Execution log ----------------------------------------------------------


def write_execution_log(
    log_path: Path,
    cfg: TenantConfig,
    args_ns: argparse.Namespace,
    started_at: dt.datetime,
    ended_at: dt.datetime,
    results: list[StageResult],
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    header_needed = not log_path.exists()

    all_ok = all(r.returncode == 0 for r in results)
    status_str = "PASS" if all_ok else "FAIL"
    mode = "dry-run" if args_ns.dry_run else "live"

    out: list[str] = []
    if header_needed:
        out.append(f"# Execution Log — {log_path.stem.split('-', 2)[-1]}\n\n")
        out.append(
            "`sse/scripts/generate-full-flow.py` 실행 이력. 각 섹션은 1회 실행.\n\n"
        )

    out.append(
        f"## {started_at.strftime('%Y-%m-%d %H:%M:%S')} — "
        f"tenant={cfg.tenant} mode={mode} status={status_str}\n\n"
    )
    out.append(
        "**Args**: "
        f"`--tenant {args_ns.tenant} --days-back {args_ns.days_back} "
        f"--flows-per-partner {args_ns.flows_per_partner}"
        f"{' --dry-run' if args_ns.dry_run else ''}"
        f"{' --stop-on-error' if args_ns.stop_on_error else ''}`\n\n"
    )
    out.append(
        f"**Target**: ODOO_URL={cfg.odoo_url}  web={cfg.web_container}  db={cfg.db_container}\n\n"
    )
    out.append(
        f"**Duration**: {(ended_at - started_at).total_seconds():.2f}s "
        f"({started_at.strftime('%H:%M:%S')} → {ended_at.strftime('%H:%M:%S')})\n\n"
    )

    out.append("| step | label | rc | dur(s) | created | skipped | total | summary |\n")
    out.append("|---|---|---:|---:|---:|---:|---:|---|\n")
    for r in results:
        out.append(
            "| {step} | {label} | {rc} | {dur:.2f} | {c} | {s} | {t} | `{sum}` |\n".format(
                step=r.step,
                label=r.label,
                rc=r.returncode,
                dur=r.duration_sec,
                c="-" if r.created is None else r.created,
                s="-" if r.skipped is None else r.skipped,
                t="-" if r.total is None else r.total,
                sum=(r.summary or "").replace("|", "\\|"),
            )
        )

    # Failure detail.
    failures = [r for r in results if r.returncode != 0]
    if failures:
        out.append("\n### Failures\n\n")
        for r in failures:
            out.append(f"#### {r.step} — rc={r.returncode}\n\n")
            out.append("```\n" + r.stdout_tail + "\n```\n\n")
            if r.stderr_tail:
                out.append("stderr:\n```\n" + r.stderr_tail + "\n```\n\n")

    out.append("\n")

    with log_path.open("a", encoding="utf-8") as f:
        f.writelines(out)


# --- CLI --------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--tenant", required=True, choices=sorted(TENANT_CONFIG))
    ap.add_argument("--days-back", type=int, default=30,
                    help="최근 N일 (기본 30). target-partners.json 재생성 시 참조. "
                         "현재는 execution-log 감사 정보로만 기록.")
    ap.add_argument("--flows-per-partner", type=int, default=2,
                    help="파트너당 플로우 건수 (기본 2). target-partners.json 의 planned_dates 길이와 매치.")
    ap.add_argument("--dry-run", action="store_true",
                    help="실제 INSERT 없이 각 단계의 plan 만 출력.")
    ap.add_argument("--only", choices=[s[0] for s in STAGES], default=None,
                    help="특정 단계만 실행 (디버깅용).")
    ap.add_argument("--start-from", choices=[s[0] for s in STAGES], default=None,
                    help="지정한 단계부터 끝까지 실행.")
    ap.add_argument("--stop-on-error", action="store_true",
                    help="어느 단계라도 rc != 0 이면 즉시 중단 (기본: 전부 시도).")
    ap.add_argument("--log-dir", type=Path, default=None,
                    help="execution-log 저장 디렉터리. 기본: customers/<tenant>/docs/")
    return ap.parse_args(argv)


def project_root_from_script(script_path: Path) -> Path:
    # <root>/scripts/generate-full-flow.py → root = parent.parent
    return script_path.resolve().parent.parent


def select_stages(args_ns: argparse.Namespace):
    keys = [s[0] for s in STAGES]
    start_idx = 0
    if args_ns.start_from:
        start_idx = keys.index(args_ns.start_from)
    if args_ns.only:
        idx = keys.index(args_ns.only)
        return [STAGE_FUNCS[idx]]
    return STAGE_FUNCS[start_idx:]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    project_root = project_root_from_script(Path(__file__))
    cfg = TenantConfig.resolve(args.tenant, project_root)

    today = dt.date.today().isoformat()
    log_dir = args.log_dir or cfg.docs_dir
    log_path = log_dir / f"execution-log-{today}.md"

    mode = "dry-run" if args.dry_run else "live"
    print(f"[start] tenant={cfg.tenant} mode={mode} odoo_url={cfg.odoo_url}")
    print(f"        project_root={project_root}")
    print(f"        scripts_dir={cfg.scripts_dir}")
    print(f"        log_path={log_path}")
    print(f"        days_back={args.days_back} flows_per_partner={args.flows_per_partner}")

    stage_funcs = select_stages(args)
    started_at = dt.datetime.now()
    results: list[StageResult] = []
    for fn in stage_funcs:
        r = fn(cfg, args.dry_run)
        results.append(r)
        if r.returncode != 0:
            print(
                f"[stage-fail] step={r.step} rc={r.returncode} — "
                f"{'중단' if args.stop_on_error else '다음 단계 계속 진행'}"
            )
            if args.stop_on_error:
                break
    ended_at = dt.datetime.now()

    # ---- Summary ----
    all_ok = all(r.returncode == 0 for r in results)
    print("\n========== [summary] ==========")
    print(f"tenant={cfg.tenant}  mode={mode}  status={'PASS' if all_ok else 'FAIL'}")
    for r in results:
        print(
            f"  {r.step:>7}  rc={r.returncode}  dur={r.duration_sec:6.2f}s  "
            f"created={r.created}  skipped={r.skipped}  total={r.total}  | {r.summary}"
        )

    try:
        write_execution_log(log_path, cfg, args, started_at, ended_at, results)
        print(f"[log] appended to {log_path}")
    except Exception as e:  # 로그 실패가 전체 실패를 가리지 않도록
        print(f"[log] WARN: {e}", file=sys.stderr)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
