"""Conformance tests for docs/spec/mcp-tenant-data-access.md (Spec 1).

One test per spec assertion (A..L), named by assertion ID. Black-box: drive from
observable inputs/outputs, never internals. This skill judges conformance; it does
not fix code.

Infra assertions (A,B,C,D,K) observe the live/repo state and run today.
Behavior assertions (E..L) require the Spec-1 secure MCP server to exist; until then
they are xfail(pending implementation) and become the acceptance gate once built.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
GATEWAY = REPO.parent / "gateway"
MCP_CONTAINER = "sse-mcp-server"
PENDING = "requires Spec-1 secure MCP server (implementation step)"


def _sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


# ---------------------------------------------------------------- A
def test_a_no_public_listener():
    """A. 공개/호스트 인터페이스에 MCP 포트 바인딩이 0 (메시/loopback만)."""
    out = _sh("ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null")
    public = [
        ln for ln in out.splitlines()
        if ("8080" in ln or "20007" in ln)
        and ("0.0.0.0" in ln or ":::" in ln)
    ]
    assert not public, f"public listeners present: {public}"


# ---------------------------------------------------------------- B
def test_b_gateway_not_exposed():
    """B. 게이트웨이가 MCP를 프록시/매핑하지 않는다."""
    nginx = (GATEWAY / "nginx.conf")
    compose = (GATEWAY / "docker-compose.yml")
    hits = []
    if nginx.exists() and "20007" in nginx.read_text():
        hits.append("nginx.conf:20007")
    if compose.exists() and "20007" in compose.read_text():
        hits.append("docker-compose:20007")
    assert not hits, f"gateway still exposes MCP: {hits}"


# ---------------------------------------------------------------- C
def test_c_no_docker_sock():
    """C. MCP 서버 컨테이너에 raw docker.sock 마운트가 없다."""
    if not shutil.which("docker"):
        pytest.skip("docker CLI unavailable in this context")
    out = _sh(f"docker inspect {MCP_CONTAINER} -f '{{{{json .Mounts}}}}' 2>/dev/null")
    if not out.strip():
        pytest.skip(f"{MCP_CONTAINER} not running")
    mounts = json.loads(out)
    sock = [m for m in mounts if "docker.sock" in (m.get("Source", "") + m.get("Destination", ""))]
    assert not sock, f"docker.sock mounted: {sock}"


# ---------------------------------------------------------------- D
@pytest.mark.xfail(reason=PENDING, strict=False)
def test_d_tool_set_no_write():
    """D. 노출 도구가 {list_tenants,list_tables,get_schema,query}와 정확히 일치, execute 없음."""
    from mcp_client_helper import list_tools  # provided once the server exists
    assert set(list_tools()) == {"list_tenants", "list_tables", "get_schema", "query"}


# ---------------------------------------------------------------- E
@pytest.mark.xfail(reason=PENDING, strict=False)
def test_e_write_rejected_and_unchanged():
    """E. 쓰기성 SQL은 write_rejected, 사전·사후 행수 동일."""
    raise NotImplementedError(PENDING)


# ---------------------------------------------------------------- F
@pytest.mark.xfail(reason=PENDING, strict=False)
def test_f_readonly_role():
    """F. MCP 접속 롤은 SELECT만 가지며 직접 INSERT/UPDATE가 권한오류로 실패."""
    raise NotImplementedError(PENDING)


# ---------------------------------------------------------------- G
@pytest.mark.xfail(reason=PENDING, strict=False)
def test_g_tenant_scope_enforced():
    """G. 범위 밖 테넌트 query는 forbidden_tenant, list_tenants에도 미노출."""
    raise NotImplementedError(PENDING)


# ---------------------------------------------------------------- H
@pytest.mark.xfail(reason=PENDING, strict=False)
def test_h_row_cap():
    """H. 5,000행 초과 결과는 row_count<=5000 & truncated==True."""
    raise NotImplementedError(PENDING)


# ---------------------------------------------------------------- I
@pytest.mark.xfail(reason=PENDING, strict=False)
def test_i_time_cap():
    """I. 30초 초과 질의는 query_timeout으로 종료."""
    raise NotImplementedError(PENDING)


# ---------------------------------------------------------------- J
@pytest.mark.xfail(reason=PENDING, strict=False)
def test_j_audit_present():
    """J. 호출 직후 감사 로그 끝줄에 identity·tenant·tool·ts·outcome 존재."""
    raise NotImplementedError(PENDING)


# ---------------------------------------------------------------- K
def test_k_no_plaintext_secret():
    """K. 추적되는 저장소 트리에 테넌트 DB 비밀번호 평문이 없다."""
    tracked = _sh(f"git -C {REPO} ls-files")
    leaks = []
    for rel in tracked.splitlines():
        if not (rel.endswith((".py", ".yml", ".yaml", ".conf", ".env", ".sh", ".md", ".toml"))):
            continue
        p = REPO / rel
        try:
            txt = p.read_text(errors="ignore")
        except OSError:
            continue
        # naive: a DB password assignment with the well-known default in MCP context
        for needle in ("DB_PASSWORD: odoo", 'DB_PASSWORD", "odoo"', "DB_PASSWORD=odoo"):
            if needle in txt:
                leaks.append(f"{rel}: {needle}")
    assert not leaks, f"plaintext DB secret in repo: {leaks}"


# ---------------------------------------------------------------- L
@pytest.mark.xfail(reason=PENDING, strict=False)
def test_l_new_tenant_autodiscovered():
    """L. yc-network에 새 ycerp-db-<t>가 뜨고 허가 범위에 들면 재배포 없이 list_tenants에 출현."""
    raise NotImplementedError(PENDING)
