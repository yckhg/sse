"""US-005: Replay demo flow orchestrator — cleanup + replay + verify.

`customers/<tenant>/scripts/` 의 3개 스크립트를 순서대로 실행해 ralph-demo-flow
데모 데이터를 재구성한다:

    cleanup_demo_mails.py   (US-001)   → 기존 22 고아 mail.mail 삭제
    replay_demo_leads.py    (US-002)   → 22 crm.lead 에 템플릿 mail 재생성
    verify_demo_replay.py   (US-003)   → 5 검사로 최종 상태 확인

각 단계 stdout 을 콘솔에 mirror 하고 `[summary]` 를 파싱해
`customers/<tenant>/docs/execution-log-<DATE>.md` 에 한 섹션으로 append
(US-004 `scripts/replay_execution_log.py` writer 를 사용).

실행::

    # dry-run — 실제 cleanup/send 없음. plan 만 출력.
    python3 scripts/replay-demo-flow.py --tenant greenpr --dry-run

    # live — 실 cleanup + 실 force_send + 검증까지.
    python3 scripts/replay-demo-flow.py --tenant greenpr

    # 호스트 파이썬으로 직접 실행 (게이트웨이 타임아웃 위험 있음).
    python3 scripts/replay-demo-flow.py --tenant greenpr --exec-mode host

    # 중간 단계 실패 시에도 끝까지 시도.
    python3 scripts/replay-demo-flow.py --tenant greenpr --no-stop-on-error

`--exec-mode container` (기본) 는 `docker cp` 로 스테이지 스크립트를 웹 컨테이너
`/tmp/sse-replay-stage-<pid>/` 에 복사한 뒤 `docker exec` 로 실행한다. 호스트에서
게이트웨이(30033 등) 로 RPC 를 쏠 때 긴 쿼리에서 간헐적으로 `ConnectionResetError`
가 나는 것을 회피한다. 실행 종료 시 임시 디렉터리는 자동 제거된다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay_execution_log import (  # noqa: E402
    ReplayStepResult,
    append_section,
    parse_summary,
)


# customers/<tenant>/CLAUDE.md 및 sse/CLAUDE.md 의 포트 매핑과 일치.
TENANT_CONFIG: dict[str, dict] = {
    "greenpr":       {"port": 30033, "web": "ycerp-web-greenpr",       "db": "ycerp-db-greenpr"},
    "mediapolytech": {"port": 30043, "web": "ycerp-web-mediapolytech", "db": "ycerp-db-mediapolytech"},
    "visualoft":     {"port": 30053, "web": "ycerp-web-visualoft",     "db": "ycerp-db-visualoft"},
    "jnj_i":         {"port": 30063, "web": "ycerp-web-jnj_i",         "db": "ycerp-db-jnj_i"},
    "freeworks":     {"port": 30073, "web": "ycerp-web-freeworks",     "db": "ycerp-db-freeworks"},
}


# (step_key, label, script_name, accepts_dry_run)
# verify_demo_replay.py 는 `--dry-run` 대신 `--no-write` 로 JSON overwrite 만 차단.
STAGES: list[tuple[str, str, str, bool]] = [
    ("cleanup", "US-001 cleanup_demo_mails", "cleanup_demo_mails.py", True),
    ("replay",  "US-002 replay_demo_leads",  "replay_demo_leads.py",  True),
    ("verify",  "US-003 verify_demo_replay", "verify_demo_replay.py", False),
]


@dataclass
class TenantCfg:
    tenant: str
    port: int
    web: str
    db: str
    odoo_url: str
    project_root: Path
    scripts_dir: Path
    docs_dir: Path


def tail(text: str, lines: int = 40) -> str:
    if not text:
        return ""
    return "\n".join(text.rstrip().splitlines()[-lines:])


def resolve_tenant(name: str, project_root: Path) -> TenantCfg:
    if name not in TENANT_CONFIG:
        raise SystemExit(
            f"[err] unknown tenant {name!r}. known: {sorted(TENANT_CONFIG)}"
        )
    t = TENANT_CONFIG[name]
    tenant_dir = project_root / "customers" / name
    scripts_dir = tenant_dir / "scripts"
    docs_dir = tenant_dir / "docs"
    if not scripts_dir.is_dir():
        raise SystemExit(f"[err] scripts dir missing: {scripts_dir}")
    for _, _, script_name, _ in STAGES:
        if not (scripts_dir / script_name).is_file():
            raise SystemExit(f"[err] stage script missing: {scripts_dir / script_name}")
    return TenantCfg(
        tenant=name,
        port=t["port"],
        web=t["web"],
        db=t["db"],
        odoo_url=f"http://localhost:{t['port']}",
        project_root=project_root,
        scripts_dir=scripts_dir,
        docs_dir=docs_dir,
    )


def _pump_proc(proc: subprocess.Popen) -> tuple[int, str, str]:
    """stdout/stderr 를 별도 스레드로 drain 하면서 mirror. PIPE 버퍼 포화 방지."""
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
    return proc.returncode, "".join(stdout_lines), "".join(stderr_lines)


def prepare_container_stage_dir(cfg: TenantCfg) -> str:
    """스테이지 스크립트 디렉터리를 웹 컨테이너 내부 임시 경로로 tar-pipe 복사.

    `docker cp` 대신 `tar -c … | docker exec tar -x` 파이프를 쓰는 이유:
    - 호스트의 `__pycache__` 는 ubuntu UID 로 생성되어 있는데 컨테이너는
      `odoo` UID 로 돌아 교차 UID 이슈 발생 (cleanup rm 시 perm denied).
    - `tar --exclude=__pycache__` 로 pyc 를 아예 제외하면 문제 회피 +
      불필요 바이트 제거.

    Returns the in-container absolute directory path (뒤에서 cleanup 대상).
    """
    target = f"/tmp/sse-replay-stage-{os.getpid()}"

    # 1) 기존 동일 경로 제거 (pid 재사용 + root 로 강제).
    subprocess.run(
        ["docker", "exec", "-u", "0", cfg.web, "rm", "-rf", target],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # 2) mkdir target (odoo 유저 권한으로 생성).
    r = subprocess.run(
        ["docker", "exec", cfg.web, "mkdir", "-p", target],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise SystemExit(
            f"[err] docker exec mkdir failed rc={r.returncode}\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )

    # 3) tar pipe (src 에서 __pycache__ 제외, 컨테이너에서 그대로 extract).
    tar_src = subprocess.Popen(
        [
            "tar", "-cf", "-",
            "--exclude=__pycache__",
            "-C", str(cfg.scripts_dir), ".",
        ],
        stdout=subprocess.PIPE,
    )
    tar_dst = subprocess.Popen(
        ["docker", "exec", "-i", cfg.web, "tar", "-xf", "-", "-C", target],
        stdin=tar_src.stdout,
    )
    assert tar_src.stdout is not None
    tar_src.stdout.close()  # allow tar_src to SIGPIPE cleanly if dst exits early
    tar_dst_rc = tar_dst.wait()
    tar_src_rc = tar_src.wait()
    if tar_src_rc != 0 or tar_dst_rc != 0:
        raise SystemExit(
            f"[err] tar pipe failed src_rc={tar_src_rc} dst_rc={tar_dst_rc}"
        )

    return target


def cleanup_container_stage_dir(cfg: TenantCfg, target: str) -> None:
    # -u 0 으로 강제 root 삭제 — pyc 등 교차 UID 파일도 깨끗이 제거.
    subprocess.run(
        ["docker", "exec", "-u", "0", cfg.web, "rm", "-rf", target],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def build_stage_extra_args(step: str, accepts_dry_run: bool, dry_run: bool) -> list[str]:
    extra: list[str] = []
    if dry_run and accepts_dry_run:
        extra.append("--dry-run")
    if step == "verify" and dry_run:
        # verify 는 dry-run 플래그가 없어 읽기 쿼리는 그대로 돌지만,
        # JSON overwrite 방지를 위해 --no-write 지정.
        extra.append("--no-write")
    return extra


def run_stage(
    step: str,
    label: str,
    script_name: str,
    accepts_dry_run: bool,
    cfg: TenantCfg,
    args: argparse.Namespace,
    env: dict,
    container_dir: str | None,
) -> ReplayStepResult:
    extra = build_stage_extra_args(step, accepts_dry_run, args.dry_run)

    print(f"\n========== [{step}] {label} ==========", flush=True)
    t0 = time.time()

    if args.exec_mode == "container":
        assert container_dir is not None
        # 컨테이너 내부에서는 게이트웨이를 우회해 localhost:8069 로 직접.
        in_container_url = "http://localhost:8069"
        cmd = [
            "docker", "exec", "-i",
            "-e", f"ODOO_URL={in_container_url}",
            "-e", f"ODOO_DB={env.get('ODOO_DB', 'odoo')}",
            "-e", f"ODOO_LOGIN={env.get('ODOO_LOGIN', 'admin')}",
            "-e", f"ODOO_PASSWORD={env.get('ODOO_PASSWORD', 'admin')}",
            "-e", "PYTHONUNBUFFERED=1",
            cfg.web,
            "python3", f"{container_dir}/{script_name}",
            *extra,
        ]
        print("$ " + " ".join(cmd), flush=True)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    else:
        # host 모드: 게이트웨이 경유 (ODOO_URL=http://localhost:<port>)
        cmd = [sys.executable, str(cfg.scripts_dir / script_name), *extra]
        print(f"$ ODOO_URL={env['ODOO_URL']} " + " ".join(cmd), flush=True)
        proc = subprocess.Popen(
            cmd,
            cwd=str(cfg.project_root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    rc, stdout_full, stderr_full = _pump_proc(proc)
    duration = time.time() - t0

    nums, raw = parse_summary(stdout_full)

    return ReplayStepResult(
        step=step,
        label=label,
        returncode=rc,
        duration_sec=duration,
        # cleanup 은 deleted, replay 는 created 로 매핑. verify 는 둘 다 None.
        deleted=nums.get("deleted") if step == "cleanup" else None,
        created=nums.get("created") if step == "replay" else None,
        skipped=nums.get("skipped"),
        total=nums.get("total"),
        summary=raw,
        stdout_tail=tail(stdout_full, 40),
        stderr_tail=tail(stderr_full, 20),
    )


def build_args_str(args: argparse.Namespace) -> str:
    parts = [f"--tenant {args.tenant}"]
    if args.dry_run:
        parts.append("--dry-run")
    if not args.stop_on_error:
        parts.append("--no-stop-on-error")
    if args.exec_mode != "container":
        parts.append(f"--exec-mode {args.exec_mode}")
    if args.log_dir is not None:
        parts.append(f"--log-dir {args.log_dir}")
    return " ".join(parts)


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--tenant",
        required=True,
        choices=sorted(TENANT_CONFIG),
        help="대상 테넌트.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 cleanup/send 없이 각 단계의 plan 만 출력.",
    )
    ap.add_argument(
        "--exec-mode",
        choices=["container", "host"],
        default="container",
        help=(
            "스테이지 스크립트 실행 위치. 기본 'container' 는 docker cp + docker exec "
            "로 웹 컨테이너 내부에서 실행(게이트웨이 타임아웃 회피). "
            "'host' 는 현재 셸에서 ODOO_URL 환경변수로 게이트웨이 경유."
        ),
    )
    # --stop-on-error 는 기본 on. --no-stop-on-error 로 해제.
    ap.add_argument(
        "--stop-on-error",
        dest="stop_on_error",
        action="store_true",
        default=True,
        help="중간 단계 실패 시 즉시 중단 (기본 on).",
    )
    ap.add_argument(
        "--no-stop-on-error",
        dest="stop_on_error",
        action="store_false",
        help="중간 단계가 실패해도 남은 단계를 계속 실행.",
    )
    ap.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="execution-log 저장 디렉터리. 기본: customers/<tenant>/docs/.",
    )
    return ap.parse_args(argv)


def project_root_from_script(script_path: Path) -> Path:
    # <root>/scripts/replay-demo-flow.py → root = parent.parent
    return script_path.resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    project_root = project_root_from_script(Path(__file__))
    cfg = resolve_tenant(args.tenant, project_root)

    today = dt.date.today().isoformat()
    log_dir = args.log_dir or cfg.docs_dir
    log_path = log_dir / f"execution-log-{today}.md"

    mode = "dry-run" if args.dry_run else "live"
    print(f"[start] tenant={cfg.tenant} mode={mode} exec={args.exec_mode} "
          f"stop_on_error={args.stop_on_error}")
    print(f"        odoo_url={cfg.odoo_url}  web={cfg.web}  db={cfg.db}")
    print(f"        project_root={project_root}")
    print(f"        scripts_dir={cfg.scripts_dir}")
    print(f"        log_path={log_path}")

    env = os.environ.copy()
    env.setdefault("ODOO_URL", cfg.odoo_url)
    env.setdefault("ODOO_DB", "odoo")
    env.setdefault("ODOO_LOGIN", "admin")
    env.setdefault("ODOO_PASSWORD", "admin")
    env["PYTHONUNBUFFERED"] = "1"

    container_dir: str | None = None
    if args.exec_mode == "container":
        container_dir = prepare_container_stage_dir(cfg)
        print(f"[prep]  container stage dir: {cfg.web}:{container_dir}")

    started_at = dt.datetime.now()
    results: list[ReplayStepResult] = []
    try:
        for step, label, script_name, accepts_dry_run in STAGES:
            r = run_stage(
                step, label, script_name, accepts_dry_run,
                cfg, args, env, container_dir,
            )
            results.append(r)
            if r.returncode != 0:
                action = "중단" if args.stop_on_error else "다음 단계 계속 진행"
                print(f"[stage-fail] step={r.step} rc={r.returncode} — {action}",
                      flush=True)
                if args.stop_on_error:
                    break
    finally:
        if container_dir is not None:
            cleanup_container_stage_dir(cfg, container_dir)

    ended_at = dt.datetime.now()

    # ---- Summary ----
    all_ok = bool(results) and all(r.returncode == 0 for r in results)
    executed_steps = {r.step for r in results}
    incomplete = any(
        step not in executed_steps for step, _, _, _ in STAGES
    )
    status = "PASS" if all_ok and not incomplete else "FAIL"

    print("\n========== [summary] ==========")
    print(f"tenant={cfg.tenant}  mode={mode}  status={status}")
    for r in results:
        summary_disp = r.summary or "(no summary)"
        print(
            f"  {r.step:>7}  rc={r.returncode}  dur={r.duration_sec:6.2f}s  "
            f"| {summary_disp}"
        )
    if incomplete:
        not_run = [s for s, _, _, _ in STAGES if s not in executed_steps]
        print(f"  not_run: {not_run}")

    # ---- execution-log append ----
    try:
        append_section(
            log_path,
            tenant=cfg.tenant,
            odoo_url=cfg.odoo_url,
            web_container=cfg.web,
            db_container=cfg.db,
            mode=mode,
            started_at=started_at,
            ended_at=ended_at,
            args_str=build_args_str(args),
            results=results,
        )
        print(f"[log] appended to {log_path}")
    except Exception as e:  # 로그 실패가 스테이지 실패를 가리지 않도록
        print(f"[log] WARN: {e}", file=sys.stderr)

    return 0 if all_ok and not incomplete else 1


if __name__ == "__main__":
    sys.exit(main())
