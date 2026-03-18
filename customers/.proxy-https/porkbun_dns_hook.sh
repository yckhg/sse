#!/bin/bash
#
# Porkbun DNS Hook for Certbot
# Used for Let's Encrypt DNS-01 challenge via Porkbun API
#

# API 인증 정보
API_KEY="pk1_3bc07d86a83f3d478bab6a20a270a7c157f67974e6da6df8739efa11e462132e"
SECRET_API_KEY="sk1_ac27a2fffb7f3dc41b6c43a757e4f87c13a285a1712ed8327ae924133795e1f4"
API_URL="https://api.porkbun.com/api/json/v3"

# Certbot에서 전달되는 환경 변수
CERTBOT_DOMAIN="${CERTBOT_DOMAIN}"
CERTBOT_VALIDATION="${CERTBOT_VALIDATION}"

# 레더리(test) 모드 지원
CERTBOT_AUTH_OUTPUT="${CERTBOT_AUTH_OUTPUT:--}"

# 도메인에서 베이스 도메인 추출 (예: _acme-challenge.greenpr.online → greenpr.online)
extract_base_domain() {
    local domain="$1"
    # _acme-challenge 제거
    domain="${domain#_acme-challenge.}"
    # 첫 레벨 서브도메인 제거 (예: www.greenpr.online → greenpr.online)
    # 하지만 Let's Encrypt는 항상 _acme-challenge.DOMAIN 형태로 전달
    echo "$domain"
}

# DNS 레코드 생성 함수
create_dns_record() {
    local domain="$1"
    local validation="$2"
    
    # 베이스 도메인 추출
    local base_domain=$(extract_base_domain "$domain")
    
    # 서브도메인 이름 (_acme-challenge만 사용)
    local subdomain="_acme-challenge"
    
    # FQDN에서 서브도메인이 더 있다면 추가
    if [[ "$domain" != "$base_domain" ]]; then
        # 예: _acme-challenge.www.greenpr.online → www._acme-challenge
        local prefix="${domain%.$base_domain}"
        if [[ "$prefix" != "_acme-challenge" ]]; then
            subdomain="$prefix._acme-challenge"
        fi
    fi
    
    echo "[INFO] Creating DNS TXT record for domain: $base_domain"
    echo "[INFO] Subdomain: $subdomain"
    echo "[INFO] Validation token: $validation"
    
    # Porkbun API call: DNS Create Record
    local response=$(curl -s -X POST "$API_URL/dns/create/$base_domain" \
        -H "Content-Type: application/json" \
        -d "{
            \"apikey\": \"$API_KEY\",
            \"secretapikey\": \"$SECRET_API_KEY\",
            \"name\": \"$subdomain\",
            \"type\": \"TXT\",
            \"content\": \"$validation\",
            \"ttl\": \"600\"
        }")
    
    echo "[DEBUG] API Response: $response"
    
    # JSON 파싱 (Python 사용으로 더 안정적으로)
    local status=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', ''))" 2>/dev/null)
    
    if [[ "$status" == "SUCCESS" ]]; then
        local record_id=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin).get('id', ''))" 2>/dev/null)
        echo "[SUCCESS] DNS record created. Record ID: $record_id"
        # Record ID를 환경변수로 저장 (정리할 때 사용)
        echo "$record_id" > "/tmp/porkbun_dns_${base_domain}.txt"
        
        # DNS 전파 대기 (중요!)
        echo "[INFO] Waiting 5 seconds for DNS propagation..."
        sleep 5
        
        return 0
    else
        local error_msg=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin).get('message', ''))" 2>/dev/null)
        echo "[ERROR] Failed to create DNS record: $error_msg"
        echo "[ERROR] Full response: $response"
        return 1
    fi
}

# DNS 레코드 삭제 함수
delete_dns_record() {
    local domain="$1"
    
    # 베이스 도메인 추출
    local base_domain=$(extract_base_domain "$domain")
    
    # 이전에 저장된 Record ID 읽기
    if [[ -f "/tmp/porkbun_dns_${base_domain}.txt" ]]; then
        local record_id=$(cat "/tmp/porkbun_dns_${base_domain}.txt")
        
        echo "[INFO] Deleting DNS TXT record (ID: $record_id) for domain: $base_domain"
        
        # Porkbun API call: DNS Delete Record by ID
        local response=$(curl -s -X POST "$API_URL/dns/delete/$base_domain/$record_id" \
            -H "Content-Type: application/json" \
            -d "{
                \"apikey\": \"$API_KEY\",
                \"secretapikey\": \"$SECRET_API_KEY\"
            }")
        
        echo "[DEBUG] API Response: $response"
        
        # 응답에서 status 확인
        local status=$(echo "$response" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
        
        if [[ "$status" == "SUCCESS" ]]; then
            echo "[SUCCESS] DNS record deleted successfully"
            rm -f "/tmp/porkbun_dns_${base_domain}.txt"
            return 0
        else
            echo "[ERROR] Failed to delete DNS record"
            echo "[ERROR] Full response: $response"
            return 1
        fi
    else
        echo "[WARNING] No record ID found for domain: $base_domain"
        return 0
    fi
}

# Main logic
case "$CERTBOT_AUTH_OUTPUT" in
    *)
        # 기본 동작: DNS 레코드 생성 (auth phase)
        if [[ -z "$CERTBOT_DOMAIN" ]] || [[ -z "$CERTBOT_VALIDATION" ]]; then
            echo "[ERROR] CERTBOT_DOMAIN and CERTBOT_VALIDATION must be set"
            exit 1
        fi
        
        # _acme-challenge 레코드 생성
        # CERTBOT_DOMAIN은 이미 _acme-challenge를 포함할 수 있음
        # 또는 base domain만 전달될 수 있음 (certbot 버전에 따라)
        if [[ "$CERTBOT_DOMAIN" == _acme-challenge* ]]; then
            create_dns_record "$CERTBOT_DOMAIN" "$CERTBOT_VALIDATION"
        else
            create_dns_record "_acme-challenge.$CERTBOT_DOMAIN" "$CERTBOT_VALIDATION"
        fi
        ;;
esac

# 종료 상태 반환
exit $?
