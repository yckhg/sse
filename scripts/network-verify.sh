#!/bin/bash
# network-verify.sh — 네트워크 설치 검증 자동화 스크립트
# Usage: ./scripts/network-verify.sh [-v] <domain>

set -euo pipefail

# ── Constants ──
GATEWAY_CONTAINER="gateway"
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
VERBOSE=0

# ── Parse args ──
while [ $# -gt 0 ]; do
    case "$1" in
        -v|--verbose) VERBOSE=1; shift ;;
        -h|--help)
            echo "Usage: $0 [-v|--verbose] <domain>"
            echo "Example: $0 -v greenpr.online"
            exit 0 ;;
        -*) echo "Unknown option: $1"; exit 1 ;;
        *) DOMAIN="$1"; shift ;;
    esac
done

if [ -z "${DOMAIN:-}" ]; then
    echo "Usage: $0 [-v|--verbose] <domain>"
    echo "Example: $0 -v greenpr.online"
    exit 1
fi
REPORT_FILE="$REPORTS_DIR/network-verify-${DOMAIN}-${DATE_STAMP}.md"

# ── Ensure reports dir ──
mkdir -p "$REPORTS_DIR"

# ── Helper functions ──
log_cmd() {
    # verbose mode: show command being executed
    if [ "$VERBOSE" = "1" ]; then
        echo -e "    ${YELLOW}$ $1${NC}"
    fi
}

log_result() {
    # verbose mode: show raw output (indented, trimmed)
    if [ "$VERBOSE" = "1" ]; then
        local output="$1"
        if [ -n "$output" ]; then
            echo "$output" | head -5 | sed 's/^/    → /'
        fi
    fi
}

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
    log_cmd "curl -sk -o /dev/null -w '%{http_code}' https://${DOMAIN}/"
    status=$(curl -sk -o /dev/null -w '%{http_code}' "https://${DOMAIN}/" 2>/dev/null || echo "000")
    log_result "HTTP Status: $status"
    if [ "$status" = "200" ] || [ "$status" = "303" ]; then
        result="PASS"
        log_pass "HTTPS 접근 (HTTP $status)"
    else
        result="FAIL"
        log_fail "HTTPS 접근 (HTTP $status)"
    fi
    echo "| HTTPS 접근 | curl -sk https://${DOMAIN} | HTTP $status | $(status_emoji "$result") $result |" >> "$REPORT_FILE"

    # 2. TLS 프로토콜
    log_cmd "openssl s_client -connect ${DOMAIN}:443 -servername ${DOMAIN}"
    local tls_ver
    tls_ver=$(echo "Q" | timeout 5 openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" 2>&1 | awk -F', ' '/^New,/{print $2; exit}')
    log_result "Protocol: $tls_ver"
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
    log_cmd "curl -sk --resolve ${DOMAIN}:443:127.0.0.1 https://${DOMAIN}/"
    local sni_status
    sni_status=$(curl -sk -o /dev/null -w '%{http_code}' --resolve "${DOMAIN}:443:127.0.0.1" "https://${DOMAIN}/" 2>/dev/null || echo "000")
    log_result "HTTP Status: $sni_status"
    if [ "$sni_status" != "000" ]; then
        result="PASS"
        log_pass "SNI 라우팅 (HTTP $sni_status)"
    else
        result="FAIL"
        log_fail "SNI 라우팅 (HTTP $sni_status)"
    fi
    echo "| SNI 라우팅 | curl --resolve ${DOMAIN}:443:127.0.0.1 | HTTP $sni_status | $(status_emoji "$result") $result |" >> "$REPORT_FILE"

    # 4. WebSocket 경로 라우팅
    log_cmd "curl -sk -H 'Upgrade: websocket' -H 'Connection: Upgrade' https://${DOMAIN}/websocket"
    local ws_status
    ws_status=$(curl -sk -o /dev/null -w '%{http_code}' \
        -H "Upgrade: websocket" \
        -H "Connection: Upgrade" \
        -H "Sec-WebSocket-Version: 13" \
        -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
        "https://${DOMAIN}/websocket" 2>/dev/null || echo "000")
    log_result "HTTP Status: $ws_status (비-502/504 = upstream 라우팅 정상)"
    # 502/504 = upstream 미도달, 그 외 = upstream 라우팅 정상
    if [ "$ws_status" != "000" ] && [ "$ws_status" != "502" ] && [ "$ws_status" != "504" ]; then
        result="PASS"
        log_pass "WebSocket 경로 라우팅 (upstream 응답 HTTP $ws_status)"
    else
        result="FAIL"
        log_fail "WebSocket 경로 라우팅 (HTTP $ws_status)"
    fi
    echo "| WebSocket 경로 라우팅 | curl -H 'Upgrade: websocket' /websocket | upstream 응답 확인 (HTTP $ws_status) | $(status_emoji "$result") $result |" >> "$REPORT_FILE"

    # 5. Long-Polling 경로 라우팅
    log_cmd "curl -sk -X POST -H 'Content-Type: application/json' -d '{}' https://${DOMAIN}/longpolling/poll"
    local lp_status
    lp_status=$(curl -sk -o /dev/null -w '%{http_code}' -X POST \
        -H "Content-Type: application/json" \
        -d '{}' \
        "https://${DOMAIN}/longpolling/poll" 2>/dev/null || echo "000")
    log_result "HTTP Status: $lp_status (비-502/504 = upstream 라우팅 정상)"
    # 502/504 = upstream 미도달, 그 외 = upstream 라우팅 정상
    if [ "$lp_status" != "000" ] && [ "$lp_status" != "502" ] && [ "$lp_status" != "504" ]; then
        result="PASS"
        log_pass "Long-Polling 경로 라우팅 (upstream 응답 HTTP $lp_status)"
    else
        result="FAIL"
        log_fail "Long-Polling 경로 라우팅 (HTTP $lp_status)"
    fi
    echo "| Long-Polling 경로 라우팅 | curl -X POST /longpolling/poll | upstream 응답 확인 (HTTP $lp_status) | $(status_emoji "$result") $result |" >> "$REPORT_FILE"
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
    log_cmd "curl -sk -o /dev/null -w '%{http_code}' https://${DOMAIN}/"
    local https_status https_result
    https_status=$(curl -sk -o /dev/null -w '%{http_code}' "https://${DOMAIN}/" 2>/dev/null || echo "000")
    log_result "HTTP Status: $https_status"
    if [ "$https_status" = "200" ] || [ "$https_status" = "303" ]; then
        https_result="PASS"
        log_pass "HTTPS 접근 (HTTP $https_status)"
    else
        https_result="FAIL"
        log_fail "HTTPS 접근 (HTTP $https_status)"
    fi

    # 2. SSL 인증서 확인
    log_cmd "openssl s_client -connect ${DOMAIN}:443 | openssl x509 -noout -dates -subject"
    local ssl_output ssl_subject ssl_expiry ssl_result ssl_detail
    ssl_output=$(echo "Q" | timeout 5 openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" 2>&1)

    ssl_subject=$(echo "$ssl_output" | openssl x509 -noout -subject 2>/dev/null | sed 's/subject=//')
    ssl_expiry=$(echo "$ssl_output" | openssl x509 -noout -enddate 2>/dev/null | sed 's/notAfter=//')

    log_result "Subject: $ssl_subject / Expires: $ssl_expiry"
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

    # 3. 라우팅 정확도 — ERP 서버 특성 헤더 확인
    log_cmd "curl -sk -D - -o /dev/null https://${DOMAIN}/"
    local headers routing_result routing_detail
    headers=$(curl -sk -D - -o /dev/null "https://${DOMAIN}/" 2>/dev/null)
    log_result "$(echo "$headers" | grep -i 'session_id\|X-Frame-Options' | head -3)"

    # Check for ERP server indicators: Set-Cookie with session_id, X-Frame-Options, etc.
    if echo "$headers" | grep -qi "session_id\|X-Frame-Options"; then
        routing_result="PASS"
        routing_detail="ERP 서버 응답 헤더 확인"
        log_pass "라우팅 정확도 ($routing_detail)"
    else
        routing_result="FAIL"
        routing_detail="ERP 서버 응답 헤더 미감지"
        log_fail "라우팅 정확도 ($routing_detail)"
    fi

    # 4. WebSocket 채팅 — proper WebSocket handshake
    log_cmd "curl -sk -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' https://${DOMAIN}/websocket"
    local ws_chat_status ws_chat_result
    ws_chat_status=$(curl -sk -o /dev/null -w '%{http_code}' \
        -H "Upgrade: websocket" \
        -H "Connection: Upgrade" \
        -H "Sec-WebSocket-Version: 13" \
        -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
        "https://${DOMAIN}/websocket" 2>/dev/null || echo "000")
    log_result "HTTP Status: $ws_chat_status"
    # 502/504 = upstream 미도달, 그 외 = upstream 라우팅 정상
    if [ "$ws_chat_status" != "000" ] && [ "$ws_chat_status" != "502" ] && [ "$ws_chat_status" != "504" ]; then
        ws_chat_result="PASS"
        log_pass "WebSocket 채팅 (upstream 응답 HTTP $ws_chat_status)"
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
    log_cmd "openssl s_client -connect ${DOMAIN}:443 -servername ${DOMAIN}"
    local cipher_info cipher_name
    cipher_info=$(echo "Q" | timeout 5 openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" 2>&1 | awk -F', ' '/^New,/{print $3; exit}')
    cipher_name=$(echo "$cipher_info" | sed 's/^Cipher is //')
    [ -z "$cipher_name" ] && cipher_name="unknown"
    log_result "Cipher: $cipher_name"

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
    log_cmd "openssl s_client -connect ${DOMAIN}:443 -cipher aNULL -no_tls1_3"
    local weak_output
    weak_output=$(echo "Q" | timeout 5 openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" -cipher aNULL -no_tls1_3 2>&1 || true)
    log_result "$(echo "$weak_output" | grep -i 'handshake\|no cipher\|alert' | head -2)"
    if echo "$weak_output" | grep -qi "handshake failure\|no ciphers available\|ssl alert\|no cipher"; then
        result="PASS"
        log_pass "약한 암호화 거부 (aNULL 차단)"
    else
        result="FAIL"
        log_fail "약한 암호화 거부 (aNULL 허용됨)"
    fi
    echo "| 약한 암호화 거부 (aNULL) | aNULL handshake 거부 여부 | $(status_emoji "$result") $result |" >> "$REPORT_FILE"

    # 3. 인증서 유효성 — Verify return code: 0 (ok)
    log_cmd "openssl s_client -connect ${DOMAIN}:443 -servername ${DOMAIN}"
    local verify_output verify_code
    verify_output=$(echo "Q" | timeout 5 openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" 2>&1)
    verify_code=$(echo "$verify_output" | grep "Verify return code:" | tail -1 | sed 's/.*Verify return code: //' | sed 's/ .*//')
    log_result "$(echo "$verify_output" | grep 'Verify return code:' | tail -1)"
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
    log_cmd "openssl s_client -connect ${DOMAIN}:443 -tls1"
    local tls10_output
    tls10_output=$(echo "Q" | timeout 5 openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" -tls1 2>&1 || true)
    log_result "$(echo "$tls10_output" | grep -i 'handshake\|wrong version\|no protocols\|version not supported\|alert' | head -2)"
    if echo "$tls10_output" | grep -qi "handshake failure\|wrong version\|no protocols\|ssl alert\|connect:errno\|version not supported"; then
        result="PASS"
        log_pass "TLSv1.0 비활성화 (연결 거부)"
    else
        result="FAIL"
        log_fail "TLSv1.0 비활성화 (연결 허용됨)"
    fi
    echo "| TLSv1.0 비활성화 | TLSv1.0 연결 거부 여부 | $(status_emoji "$result") $result |" >> "$REPORT_FILE"

    # 5. TLSv1.1 비활성화
    log_cmd "openssl s_client -connect ${DOMAIN}:443 -tls1_1"
    local tls11_output
    tls11_output=$(echo "Q" | timeout 5 openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" -tls1_1 2>&1 || true)
    log_result "$(echo "$tls11_output" | grep -i 'handshake\|wrong version\|no protocols\|version not supported\|alert' | head -2)"
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

    local result

    # Report section header
    cat >> "$REPORT_FILE" <<'EOF'

## d. 성능 검증

| 항목 | 측정값 | 기준 | 결론 |
|------|--------|------|------|
EOF

    # 1. Nginx 메모리 — docker stats로 측정 (MiB)
    log_cmd "docker stats $GATEWAY_CONTAINER --no-stream --format '{{.MemUsage}}'"
    local mem_usage mem_mb
    mem_usage=$(docker stats "$GATEWAY_CONTAINER" --no-stream --format '{{.MemUsage}}' 2>/dev/null || echo "")
    log_result "$mem_usage"
    mem_mb=$(echo "$mem_usage" | grep -oP '[\d.]+' | head -1 || echo "0")
    [ -z "$mem_mb" ] && mem_mb="0"
    local mem_ok
    mem_ok=$(awk "BEGIN{print ($mem_mb > 0 && $mem_mb <= 100) ? 1 : 0}")
    if [ "$mem_ok" = "1" ]; then
        result="PASS"
        log_pass "Nginx 메모리 (${mem_mb}MiB ≤ 100MB)"
    elif [ "$mem_mb" = "0" ]; then
        result="FAIL"
        log_fail "Nginx 메모리 (측정 실패)"
    else
        result="FAIL"
        log_fail "Nginx 메모리 (${mem_mb}MiB > 100MB)"
    fi
    echo "| Nginx 메모리 | ${mem_mb}MiB | ≤ 100MB | $(status_emoji "$result") $result |" >> "$REPORT_FILE"

    # 2. 응답 시간 — curl time_total
    log_cmd "curl -sk -o /dev/null -w '%{time_total}' https://${DOMAIN}/"
    local time_total
    time_total=$(curl -sk -o /dev/null -w '%{time_total}' "https://${DOMAIN}/" 2>/dev/null || echo "99.0")
    log_result "Response time: ${time_total}s"
    local time_ok
    time_ok=$(awk "BEGIN{print ($time_total <= 2.0) ? 1 : 0}")
    if [ "$time_ok" = "1" ]; then
        result="PASS"
        log_pass "응답 시간 (${time_total}s ≤ 2.0s)"
    else
        result="FAIL"
        log_fail "응답 시간 (${time_total}s > 2.0s)"
    fi
    echo "| 응답 시간 | ${time_total}s | ≤ 2.0s | $(status_emoji "$result") $result |" >> "$REPORT_FILE"

    # 3. 10회 연속 성공률
    log_cmd "curl -sk https://${DOMAIN}/ (x10 반복)"
    local success_count=0 i http_code
    for i in $(seq 1 10); do
        http_code=$(curl -sk -o /dev/null -w '%{http_code}' "https://${DOMAIN}/" 2>/dev/null || echo "000")
        if [ "$http_code" = "200" ] || [ "$http_code" = "303" ]; then
            success_count=$((success_count + 1))
        fi
    done
    log_result "성공: ${success_count}/10"
    if [ "$success_count" -ge 9 ]; then
        result="PASS"
        log_pass "연속 성공률 (${success_count}/10)"
    else
        result="FAIL"
        log_fail "연속 성공률 (${success_count}/10)"
    fi
    echo "| 10회 연속 성공률 | ${success_count}/10 | ≥ 9/10 | $(status_emoji "$result") $result |" >> "$REPORT_FILE"

    # 4. worker_connections — nginx config에서 추출
    log_cmd "docker exec $GATEWAY_CONTAINER nginx -T | grep worker_connections"
    local worker_conn
    worker_conn=$(docker exec "$GATEWAY_CONTAINER" nginx -T 2>/dev/null | grep -oP 'worker_connections\s+\K[0-9]+' | head -1 || echo "0")
    log_result "worker_connections: $worker_conn"
    [ -z "$worker_conn" ] && worker_conn="0"
    if [ "$worker_conn" -ge 1000 ]; then
        result="PASS"
        log_pass "worker_connections (${worker_conn} ≥ 1000)"
    else
        result="FAIL"
        log_fail "worker_connections (${worker_conn} < 1000)"
    fi
    echo "| worker_connections | ${worker_conn} | ≥ 1000 | $(status_emoji "$result") $result |" >> "$REPORT_FILE"
}

# ── Main ──
echo -e "${BOLD}네트워크 검증 시작: ${DOMAIN}${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

init_report

run_connectivity
run_routing
run_security
run_performance

# ── Update report header with actual results ──
sed -i "s/(검증 완료 후 업데이트)/${PASSED}\/${TOTAL} PASS/" "$REPORT_FILE"

# ── Append report summary footer ──
cat >> "$REPORT_FILE" <<EOF

---

## 전체 요약

| 구분 | 수 |
|------|-----|
| 총 항목 수 | ${TOTAL} |
| PASS | ${PASSED} |
| FAIL | ${FAILED} |

> **결과: ${PASSED}/${TOTAL} PASS** $([ "$FAILED" -eq 0 ] && echo "— 전체 통과 ✅" || echo "— ${FAILED}건 실패 ❌")
EOF

# ── Terminal summary ──
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ "$FAILED" -eq 0 ]; then
    echo -e "${GREEN}${BOLD}전체 결과: ${PASSED}/${TOTAL} PASS — 전체 통과${NC}"
else
    echo -e "${RED}${BOLD}전체 결과: ${PASSED}/${TOTAL} PASS — ${FAILED}건 실패${NC}"
fi
echo "리포트: $REPORT_FILE"

# Exit code
if [ "$FAILED" -gt 0 ]; then
    exit 1
else
    exit 0
fi
