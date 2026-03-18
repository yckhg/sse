#!/bin/bash
#
# Porkbun DNS Cleanup Hook for Certbot
# Removes DNS records after Let's Encrypt validation
#

# API 인증 정보
API_KEY="pk1_3bc07d86a83f3d478bab6a20a270a7c157f67974e6da6df8739efa11e462132e"
SECRET_API_KEY="sk1_ac27a2fffb7f3dc41b6c43a757e4f87c13a285a1712ed8327ae924133795e1f4"
API_URL="https://api.porkbun.com/api/json/v3"

# Certbot에서 전달되는 환경 변수
CERTBOT_DOMAIN="${CERTBOT_DOMAIN}"

# 도메인에서 베이스 도메인 추출
extract_base_domain() {
    local domain="$1"
    domain="${domain#_acme-challenge.}"
    echo "$domain"
}

# 기본 동작: DNS 레코드 삭제 (cleanup phase)
if [[ -z "$CERTBOT_DOMAIN" ]]; then
    echo "[ERROR] CERTBOT_DOMAIN must be set"
    exit 1
fi

# 베이스 도메인 추출
base_domain=$(extract_base_domain "$CERTBOT_DOMAIN")

# 이전에 저장된 Record ID 읽기
if [[ -f "/tmp/porkbun_dns_${base_domain}.txt" ]]; then
    record_id=$(cat "/tmp/porkbun_dns_${base_domain}.txt")
    
    echo "[INFO] Cleaning up DNS TXT record (ID: $record_id) for domain: $base_domain"
    
    # Porkbun API call: DNS Delete Record by ID
    response=$(curl -s -X POST "$API_URL/dns/delete/$base_domain/$record_id" \
        -H "Content-Type: application/json" \
        -d "{
            \"apikey\": \"$API_KEY\",
            \"secretapikey\": \"$SECRET_API_KEY\"
        }")
    
    echo "[DEBUG] API Response: $response"
    
    # JSON 파싱 (Python 사용으로 더 안정적으로)
    status=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', ''))" 2>/dev/null)
    
    if [[ "$status" == "SUCCESS" ]]; then
        echo "[SUCCESS] DNS record cleaned up successfully"
        rm -f "/tmp/porkbun_dns_${base_domain}.txt"
        exit 0
    else
        error_msg=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin).get('message', ''))" 2>/dev/null)
        echo "[ERROR] Failed to cleanup DNS record: $error_msg"
        echo "[ERROR] Full response: $response"
        exit 1
    fi
else
    echo "[WARNING] No record ID found for cleanup: $base_domain"
    exit 0
fi
