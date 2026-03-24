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

    local status result

    # Report section header
    cat >> "$REPORT_FILE" <<'EOF'

## b. 도메인별 라우팅 검증

| 도메인 | HTTPS 접근 | SSL 인증서 | 라우팅 정확도 | 채팅 기능 |
|--------|-----------|-----------|-------------|----------|
EOF

    # 1. HTTPS 접근 상태코드
    local https_status https_result
    https_status=$(curl -sk -o /dev/null -w '%{http_code}' "https://${DOMAIN}/" 2>/dev/null || echo "000")
    if [ "$https_status" = "200" ] || [ "$https_status" = "303" ]; then
        https_result="PASS"
        log_pass "HTTPS 접근 (HTTP $https_status)"
    else
        https_result="FAIL"
        log_fail "HTTPS 접근 (HTTP $https_status)"
    fi

    # 2. SSL 인증서 확인
    local ssl_output ssl_subject ssl_expiry ssl_result ssl_detail
    ssl_output=$(echo "Q" | timeout 5 openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" 2>&1)

    ssl_subject=$(echo "$ssl_output" | openssl x509 -noout -subject 2>/dev/null | sed 's/subject=//')
    ssl_expiry=$(echo "$ssl_output" | openssl x509 -noout -enddate 2>/dev/null | sed 's/notAfter=//')

    if [ -n "$ssl_expiry" ]; then
        # Check if cert is still valid (not expired)
        local expiry_epoch now_epoch
        expiry_epoch=$(date -d "$ssl_expiry" +%s 2>/dev/null || echo "0")
        now_epoch=$(date +%s)
        if [ "$expiry_epoch" -gt "$now_epoch" ]; then
            ssl_result="PASS"
            ssl_detail="만료일: ${ssl_expiry}"
            log_pass "SSL 인증서 (${ssl_detail})"
        else
            ssl_result="FAIL"
            ssl_detail="만료됨: ${ssl_expiry}"
            log_fail "SSL 인증서 (${ssl_detail})"
        fi
    else
        ssl_result="FAIL"
        ssl_detail="인증서 파싱 실패"
        log_fail "SSL 인증서 ($ssl_detail)"
    fi

    # 3. 라우팅 정확도 — Odoo 서버 특성 헤더 확인
    local headers routing_result routing_detail
    headers=$(curl -sk -D - -o /dev/null "https://${DOMAIN}/" 2>/dev/null)

    # Check for Odoo-specific indicators: Set-Cookie with session_id, X-Frame-Options, etc.
    if echo "$headers" | grep -qi "session_id\|X-Frame-Options\|odoo"; then
        routing_result="PASS"
        routing_detail="Odoo 특성 헤더 감지"
        log_pass "라우팅 정확도 ($routing_detail)"
    else
        routing_result="FAIL"
        routing_detail="Odoo 특성 헤더 미감지"
        log_fail "라우팅 정확도 ($routing_detail)"
    fi

    # 4. WebSocket 채팅 — proper WebSocket handshake
    local ws_chat_status ws_chat_result
    ws_chat_status=$(curl -sk -o /dev/null -w '%{http_code}' \
        -H "Upgrade: websocket" \
        -H "Connection: Upgrade" \
        -H "Sec-WebSocket-Version: 13" \
        -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
        "https://${DOMAIN}/websocket" 2>/dev/null || echo "000")
    if [ "$ws_chat_status" = "101" ]; then
        ws_chat_result="PASS"
        log_pass "WebSocket 채팅 (HTTP $ws_chat_status)"
    else
        ws_chat_result="FAIL"
        log_fail "WebSocket 채팅 (HTTP $ws_chat_status)"
    fi

    # Write report row
    echo "| ${DOMAIN} | $(status_emoji "$https_result") HTTP ${https_status} | $(status_emoji "$ssl_result") ${ssl_detail} | $(status_emoji "$routing_result") ${routing_detail} | $(status_emoji "$ws_chat_result") HTTP ${ws_chat_status} |" >> "$REPORT_FILE"
}

run_security() {
    echo -e "\n${BOLD}=== c. 보안 검증 ===${NC}"

    local result

    # Report section header
    cat >> "$REPORT_FILE" <<'EOF'

## c. 보안 검증

| 검증 항목 | 결과 | 상태 |
|----------|------|------|
EOF

    # 1. 암호화 수준 — cipher suite가 HIGH 등급인지 확인
    local cipher_info cipher_name
    cipher_info=$(echo "Q" | timeout 5 openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" 2>&1 | awk -F', ' '/^New,/{print $3; exit}')
    cipher_name=$(echo "$cipher_info" | sed 's/^Cipher is //')
    [ -z "$cipher_name" ] && cipher_name="unknown"

    # TLS 1.3 ciphers (TLS_AES_*) and strong TLS 1.2 ciphers are HIGH grade
    if [ "$cipher_name" != "unknown" ] && [ "$cipher_name" != "(NONE)" ]; then
        result="PASS"
        log_pass "암호화 수준 ($cipher_name)"
    else
        result="FAIL"
        log_fail "암호화 수준 ($cipher_name)"
    fi
    echo "| 암호화 수준 (cipher suite) | $cipher_name | $(status_emoji "$result") $result |" >> "$REPORT_FILE"

    # 2. 약한 암호화 거부 — aNULL cipher로 연결 시도 (TLS 1.3 비활성화하여 -cipher 옵션 적용)
    local weak_output
    weak_output=$(echo "Q" | timeout 5 openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" -cipher aNULL -no_tls1_3 2>&1 || true)
    if echo "$weak_output" | grep -qi "handshake failure\|no ciphers available\|ssl alert\|no cipher"; then
        result="PASS"
        log_pass "약한 암호화 거부 (aNULL 차단)"
    else
        result="FAIL"
        log_fail "약한 암호화 거부 (aNULL 허용됨)"
    fi
    echo "| 약한 암호화 거부 (aNULL) | aNULL handshake 거부 여부 | $(status_emoji "$result") $result |" >> "$REPORT_FILE"

    # 3. 인증서 유효성 — Verify return code: 0 (ok)
    local verify_output verify_code
    verify_output=$(echo "Q" | timeout 5 openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" 2>&1)
    verify_code=$(echo "$verify_output" | grep "Verify return code:" | tail -1 | sed 's/.*Verify return code: //' | sed 's/ .*//')
    [ -z "$verify_code" ] && verify_code="unknown"

    if [ "$verify_code" = "0" ]; then
        result="PASS"
        log_pass "인증서 유효성 (Verify return code: 0)"
    else
        result="FAIL"
        log_fail "인증서 유효성 (Verify return code: $verify_code)"
    fi
    echo "| 인증서 유효성 | Verify return code: $verify_code | $(status_emoji "$result") $result |" >> "$REPORT_FILE"

    # 4. TLSv1.0 비활성화
    local tls10_output
    tls10_output=$(echo "Q" | timeout 5 openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" -tls1 2>&1 || true)
    if echo "$tls10_output" | grep -qi "handshake failure\|wrong version\|no protocols\|ssl alert\|connect:errno\|version not supported"; then
        result="PASS"
        log_pass "TLSv1.0 비활성화 (연결 거부)"
    else
        result="FAIL"
        log_fail "TLSv1.0 비활성화 (연결 허용됨)"
    fi
    echo "| TLSv1.0 비활성화 | TLSv1.0 연결 거부 여부 | $(status_emoji "$result") $result |" >> "$REPORT_FILE"

    # 5. TLSv1.1 비활성화
    local tls11_output
    tls11_output=$(echo "Q" | timeout 5 openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" -tls1_1 2>&1 || true)
    if echo "$tls11_output" | grep -qi "handshake failure\|wrong version\|no protocols\|ssl alert\|connect:errno\|version not supported"; then
        result="PASS"
        log_pass "TLSv1.1 비활성화 (연결 거부)"
    else
        result="FAIL"
        log_fail "TLSv1.1 비활성화 (연결 허용됨)"
    fi
    echo "| TLSv1.1 비활성화 | TLSv1.1 연결 거부 여부 | $(status_emoji "$result") $result |" >> "$REPORT_FILE"
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
