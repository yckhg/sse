"""US-004: replay-demo-flow (cleanup + replay + verify) 실행 이력 로거.

`scripts/generate-full-flow.py` 의 `write_execution_log()` 와 같은 마크다운
테이블 포맷을 사용하되, `created/deleted` 컬럼으로 cleanup(deleted), replay(created)
양쪽을 한 표에 담는다. 기존 섹션은 절대 훼손하지 않는 append-only.

US-005 오케스트레이터가 다음과 같이 사용한다::

    from scripts.replay_execution_log import (
        ReplayStepResult, append_section, parse_summary,
    )

    nums, raw = parse_summary(stdout)
    results.append(ReplayStepResult(
        step="cleanup",
        label="US-001 cleanup_demo_mails",
        returncode=rc,
        duration_sec=dur,
        deleted=nums.get("deleted"),
        skipped=nums.get("skipped"),
        total=nums.get("total"),
        summary=raw,
    ))
    append_section(log_path, tenant=..., results=results, ...)

동일 컬럼 수를 유지해 기존 generate-full-flow 섹션과 시각적으로 호환된다.

`python3 -m scripts.replay_execution_log --self-test` 로 자체 검증 가능.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from dataclasses import dataclass, field
from pathlib import Path


HEADER_LINE = (
    "| step | label | rc | dur(s) | created/deleted | skipped | total | summary |\n"
)
HEADER_SEP = "|---|---|---:|---:|---:|---:|---:|---|\n"


@dataclass
class ReplayStepResult:
    """One row of the replay execution-log table.

    Either `deleted` (cleanup) or `created` (replay) populates the
    `created/deleted` column. `verify` step typically leaves both `None`.
    `summary` is the raw `[summary] ...` line emitted by the stage script.
    """

    step: str
    label: str
    returncode: int
    duration_sec: float
    deleted: int | None = None
    created: int | None = None
    skipped: int | None = None
    total: int | None = None
    summary: str = ""
    stdout_tail: str = ""
    stderr_tail: str = ""

    def created_or_deleted_cell(self) -> str:
        if self.deleted is not None:
            return str(self.deleted)
        if self.created is not None:
            return str(self.created)
        return "-"


# `[summary] foo=1 bar=2 ...` 토큰 중 우리가 의미를 부여하는 키.
# - cleanup:   deleted, skipped
# - replay:    replayed→created (정규화), skipped, total
# - dry-run:   target→total (정규화)
# 다른 키는 무시한다.
_KEY_NORMALIZE = {
    "replayed": "created",
    "target": "total",
}
_KNOWN_KEYS = {"deleted", "created", "skipped", "total"}


def parse_summary(stdout: str) -> tuple[dict[str, int], str]:
    """마지막 `[summary] ...` 라인을 찾아 (정수 키-값 dict, raw 라인) 반환.

    `[summary]` 라인이 없으면 `({}, "")`. dry-run 처럼 `[summary] dry-run target=N`
    형태도 처리하며 `target` 은 `total` 로 정규화한다.
    """
    nums: dict[str, int] = {}
    raw = ""
    for line in reversed(stdout.splitlines()):
        if "[summary]" not in line:
            continue
        raw = line.strip()
        for tok in line.split():
            if "=" not in tok:
                continue
            k, _, v = tok.partition("=")
            try:
                n = int(v)
            except ValueError:
                continue
            k = _KEY_NORMALIZE.get(k, k)
            if k in _KNOWN_KEYS:
                nums[k] = n
        break
    return nums, raw


def _ensure_header(log_path: Path) -> bool:
    """파일이 없거나 비어 있으면 True (호출자가 # H1 + intro 를 출력해야 함)."""
    if not log_path.exists():
        return True
    return log_path.stat().st_size == 0


def _md_escape(text: str) -> str:
    return (text or "").replace("|", "\\|")


def _date_from_log_name(log_path: Path) -> str:
    """`execution-log-2026-04-17.md` -> `2026-04-17`. 그 외 stem 그대로."""
    stem = log_path.stem
    if stem.startswith("execution-log-"):
        return stem[len("execution-log-") :]
    return stem


def append_section(
    log_path: Path,
    *,
    tenant: str,
    odoo_url: str,
    web_container: str,
    db_container: str,
    mode: str,
    started_at: dt.datetime,
    ended_at: dt.datetime,
    args_str: str,
    results: list[ReplayStepResult],
    flow_label: str = "replay-demo-flow",
) -> None:
    """execution-log-<DATE>.md 에 새 섹션 한 개를 append.

    - 파일이 없으면 H1 + intro 라인을 먼저 쓴다.
    - 기존 섹션 내용은 절대 변경하지 않는다 (open mode='a').
    - 행 순서는 `results` 입력 순서를 유지.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    need_header = _ensure_header(log_path)

    all_ok = all(r.returncode == 0 for r in results)
    status_str = "PASS" if all_ok else "FAIL"

    out: list[str] = []
    if need_header:
        date_str = _date_from_log_name(log_path)
        out.append(f"# Execution Log — {date_str}\n\n")
        out.append(
            "`sse/scripts/generate-full-flow.py` / `sse/scripts/replay-demo-flow.py` "
            "실행 이력. 각 섹션은 1회 실행.\n\n"
        )

    out.append(
        f"## {started_at.strftime('%Y-%m-%d %H:%M:%S')} — "
        f"tenant={tenant} mode={mode} flow={flow_label} status={status_str}\n\n"
    )
    out.append(f"**Args**: `{args_str}`\n\n")
    out.append(
        f"**Target**: ODOO_URL={odoo_url}  web={web_container}  db={db_container}\n\n"
    )
    out.append(
        f"**Duration**: {(ended_at - started_at).total_seconds():.2f}s "
        f"({started_at.strftime('%H:%M:%S')} → {ended_at.strftime('%H:%M:%S')})\n\n"
    )

    out.append(HEADER_LINE)
    out.append(HEADER_SEP)
    for r in results:
        out.append(
            "| {step} | {label} | {rc} | {dur:.2f} | {cd} | {s} | {t} | `{sum}` |\n".format(
                step=r.step,
                label=_md_escape(r.label),
                rc=r.returncode,
                dur=r.duration_sec,
                cd=r.created_or_deleted_cell(),
                s="-" if r.skipped is None else r.skipped,
                t="-" if r.total is None else r.total,
                sum=_md_escape(r.summary),
            )
        )

    failures = [r for r in results if r.returncode != 0]
    if failures:
        out.append("\n### Failures\n\n")
        for r in failures:
            out.append(f"#### {r.step} — rc={r.returncode}\n\n")
            if r.stdout_tail:
                out.append("```\n" + r.stdout_tail + "\n```\n\n")
            if r.stderr_tail:
                out.append("stderr:\n```\n" + r.stderr_tail + "\n```\n\n")

    out.append("\n")

    with log_path.open("a", encoding="utf-8") as f:
        f.writelines(out)


# ---- self-test (no external deps) ------------------------------------------


def _self_test() -> int:
    import tempfile

    errors: list[str] = []

    def _check(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    # 1) parse_summary - cleanup live
    nums, raw = parse_summary(
        "[scan] mail.mail LIKE '%ralph-demo-flow%' -> found=22\n"
        "[summary] deleted=22\n"
    )
    _check(nums == {"deleted": 22}, f"cleanup parse: {nums}")
    _check(raw == "[summary] deleted=22", f"cleanup raw: {raw!r}")

    # 2) parse_summary - replay live
    nums, _ = parse_summary("[summary] replayed=22 skipped=0 total=22\n")
    _check(
        nums == {"created": 22, "skipped": 0, "total": 22},
        f"replay parse: {nums}",
    )

    # 3) parse_summary - dry-run target normalised to total
    nums, _ = parse_summary("[summary] dry-run target=22\n")
    _check(nums == {"total": 22}, f"dry-run parse: {nums}")

    # 4) parse_summary - empty
    nums, raw = parse_summary("nothing here\n")
    _check(nums == {} and raw == "", f"empty parse: {nums}, {raw!r}")

    # 5) append_section: header on first call, append on second
    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "execution-log-2099-01-01.md"
        t0 = dt.datetime(2099, 1, 1, 12, 0, 0)
        t1 = dt.datetime(2099, 1, 1, 12, 0, 5)

        results1 = [
            ReplayStepResult(
                step="cleanup",
                label="US-001 cleanup_demo_mails",
                returncode=0,
                duration_sec=0.42,
                deleted=22,
                summary="[summary] deleted=22",
            ),
            ReplayStepResult(
                step="replay",
                label="US-002 replay_demo_leads",
                returncode=0,
                duration_sec=2.18,
                created=22,
                skipped=0,
                total=22,
                summary="[summary] replayed=22 skipped=0 total=22",
            ),
            ReplayStepResult(
                step="verify",
                label="US-003 verify_demo_replay",
                returncode=0,
                duration_sec=0.91,
                summary="[summary] checks=5/5 leads=22/22",
            ),
        ]
        append_section(
            log_path,
            tenant="greenpr",
            odoo_url="http://localhost:30033",
            web_container="ycerp-web-greenpr",
            db_container="ycerp-db-greenpr",
            mode="live",
            started_at=t0,
            ended_at=t1,
            args_str="--tenant greenpr",
            results=results1,
        )

        body = log_path.read_text(encoding="utf-8")
        _check(body.startswith("# Execution Log — 2099-01-01\n\n"), "header H1 missing")
        _check("tenant=greenpr mode=live flow=replay-demo-flow status=PASS" in body,
               "section header missing")
        _check("| cleanup |" in body and "| 22 |" in body, "cleanup row missing")
        _check("| replay |" in body and "[summary] replayed=22" in body,
               "replay row missing")
        _check("| verify |" in body and "| - | - | - |" in body,
               "verify row should have - placeholders")
        _check(HEADER_LINE.strip() in body, "table header line missing")

        # Second call — append a dry-run + a failure, verify append-only.
        original_body = body
        t2 = dt.datetime(2099, 1, 1, 13, 0, 0)
        t3 = dt.datetime(2099, 1, 1, 13, 0, 1)
        results2 = [
            ReplayStepResult(
                step="cleanup",
                label="US-001 cleanup_demo_mails",
                returncode=0,
                duration_sec=0.10,
                total=22,
                summary="[summary] dry-run target=22",
            ),
            ReplayStepResult(
                step="replay",
                label="US-002 replay_demo_leads",
                returncode=2,
                duration_sec=0.15,
                summary="",
                stderr_tail="boom",
            ),
        ]
        append_section(
            log_path,
            tenant="greenpr",
            odoo_url="http://localhost:30033",
            web_container="ycerp-web-greenpr",
            db_container="ycerp-db-greenpr",
            mode="dry-run",
            started_at=t2,
            ended_at=t3,
            args_str="--tenant greenpr --dry-run",
            results=results2,
        )

        body2 = log_path.read_text(encoding="utf-8")
        _check(body2.startswith(original_body), "earlier content was modified (NOT append-only)")
        _check(body2.count("# Execution Log — 2099-01-01") == 1,
               "header should not be re-emitted")
        _check("status=FAIL" in body2, "failure status missing")
        _check("### Failures" in body2 and "stderr:\n```\nboom" in body2,
               "failure detail block missing")
        _check("dry-run" in body2 and "| - |" in body2,
               "dry-run section missing")

    if errors:
        for e in errors:
            print(f"  [FAIL] {e}", file=sys.stderr)
        print(f"[self-test] {len(errors)} failure(s)", file=sys.stderr)
        return 1
    print("[self-test] OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true",
                    help="내장 self-test 실행 (rc=0 통과).")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    if args.self_test:
        return _self_test()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
