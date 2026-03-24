#!/bin/bash
# network-verify.sh — 네트워크 설치 검증 자동화 스크립트
# Usage: ./scripts/network-verify.sh <domain>

set -euo pipefail

# ── Constants ──
GATEWAY_CONTAINER="cetral-nginx"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPORTS_DIR="$PROJECT_ROOT/reports"
DATE_STAMP=$(date +%Y%m%d)

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

# ── Counters ──
TOTAL=0
PASSED=0
FAILED=0

# ── Usage ──
if [ $# -lt 1 ]; then
    echo "Usage: $0 <domain>"
    echo "Example: $0 greenpr.online"
    exit 1
fi

DOMAIN="$1"
REPORT_FILE="$REPORTS_DIR/network-verify-${DOMAIN}-${DATE_STAMP}.md"

# ── Ensure reports dir ──
mkdir -p "$REPORTS_DIR"

# ── Helper functions ──
log_pass() {
    local item="$1"
    echo -e "  ${GREEN}PASS${NC} $item"
    PASSED=$((PASSED + 1))
    TOTAL=$((TOTAL + 1))
}

log_fail() {
    local item="$1"
    echo -e "  ${RED}FAIL${NC} $item"
    FAILED=$((FAILED + 1))
    TOTAL=$((TOTAL + 1))
}

status_emoji() {
    if [ "$1" = "PASS" ]; then
        echo "✅"
    else
        echo "❌"
    fi
}

# ── Report init ──
init_report() {
    cat > "$REPORT_FILE" <<EOF
# 네트워크 검증 리포트

- **도메인**: $DOMAIN
- **실행 일시**: $(date '+%Y-%m-%d %H:%M:%S')
- **전체 결과**: (검증 완료 후 업데이트)

---
EOF
}

# ── Test stubs ──
run_connectivity() {
    echo -e "\n${BOLD}=== a. 네트워크 연결성 검증 ===${NC}"

    local status result

    # Report section header
    cat >> "$REPORT_FILE" <<'EOF'

## a. 네트워크 연결성 검증

| 항목 | 검증 방법 | 결과 | 상태 |
|------|----------|------|------|
EOF

    # 1. HTTPS 접근
    status=$(curl -sk -o /dev/null -w '%{http_code}' "https://${DOMAIN}/" 2>/dev/null || echo "000")
    if [ "$status" = "200" ] || [ "$status" = "303" ]; then
        result="PASS"
        log_pass "HTTPS 접근 (HTTP $status)"
    else
        result="FAIL"
        log_fail "HTTPS 접근 (HTTP $status)"
    fi
    echo "| HTTPS 접근 | curl -sk https://${DOMAIN} | HTTP $status | $(status_emoji "$result") $result |" >> "$REPORT_FILE"

    # 2. TLS 프로토콜
    local tls_ver
    tls_ver=$(echo "Q" | timeout 5 openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" 2>&1 | awk -F', ' '/^New,/{print $2; exit}')
    [ -z "$tls_ver" ] && tls_ver="unknown"
    if [ "$tls_ver" = "TLSv1.2" ] || [ "$tls_ver" = "TLSv1.3" ]; then
        result="PASS"
        log_pass "TLS 프로토콜 ($tls_ver)"
    else
        result="FAIL"
        log_fail "TLS 프로토콜 ($tls_ver)"
    fi
    echo "| TLS 프로토콜 | openssl s_client Protocol | $tls_ver | $(status_emoji "$result") $result |" >> "$REPORT_FILE"

    # 3. SNI 라우팅
    local sni_status
    sni_status=$(curl -sk -o /dev/null -w '%{http_code}' --resolve "${DOMAIN}:443:127.0.0.1" "https://${DOMAIN}/" 2>/dev/null || echo "000")
    if [ "$sni_status" != "000" ]; then
        result="PASS"
        log_pass "SNI 라우팅 (HTTP $sni_status)"
    else
        result="FAIL"
        log_fail "SNI 라우팅 (HTTP $sni_status)"
    fi
    echo "| SNI 라우팅 | curl --resolve ${DOMAIN}:443:127.0.0.1 | HTTP $sni_status | $(status_emoji "$result") $result |" >> "$REPORT_FILE"

    # 4. WebSocket
    local ws_status
    ws_status=$(curl -sk -o /dev/null -w '%{http_code}' \
        -H "Upgrade: websocket" \
        -H "Connection: Upgrade" \
        -H "Sec-WebSocket-Version: 13" \
        -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
        "https://${DOMAIN}/websocket" 2>/dev/null || echo "000")
    if [ "$ws_status" = "101" ] || [ "$ws_status" = "200" ]; then
        result="PASS"
        log_pass "WebSocket (HTTP $ws_status)"
    else
        result="FAIL"
        log_fail "WebSocket (HTTP $ws_status)"
    fi
    echo "| WebSocket | curl -H 'Upgrade: websocket' /websocket | HTTP $ws_status | $(status_emoji "$result") $result |" >> "$REPORT_FILE"

    # 5. Long-Polling
    local lp_status
    lp_status=$(curl -sk -o /dev/null -w '%{http_code}' -X POST \
        -H "Content-Type: application/json" \
        -d '{}' \
        "https://${DOMAIN}/longpolling/poll" 2>/dev/null || echo "000")
    if [ "$lp_status" = "200" ] || [ "$lp_status" = "400" ]; then
        result="PASS"
        log_pass "Long-Polling (HTTP $lp_status)"
    else
        result="FAIL"
        log_fail "Long-Polling (HTTP $lp_status)"
    fi
    echo "| Long-Polling | curl -X POST /longpolling/poll | HTTP $lp_status | $(status_emoji "$result") $result |" >> "$REPORT_FILE"
}

run_routing() {
    echo -e "\n${BOLD}=== b. 도메인별 라우팅 검증 ===${NC}"
    echo "  (not implemented)"
}

run_security() {
    echo -e "\n${BOLD}=== c. 보안 검증 ===${NC}"
    echo "  (not implemented)"
}

run_performance() {
    echo -e "\n${BOLD}=== d. 성능 검증 ===${NC}"
    echo "  (not implemented)"
}

# ── Main ──
echo -e "${BOLD}네트워크 검증 시작: ${DOMAIN}${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

init_report

run_connectivity
run_routing
run_security
run_performance

# ── Summary ──
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BOLD}전체 결과: ${PASSED}/${TOTAL} PASS${NC}"
echo "리포트: $REPORT_FILE"

# Exit code
if [ "$FAILED" -gt 0 ]; then
    exit 1
else
    exit 0
fi
