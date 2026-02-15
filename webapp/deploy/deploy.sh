#!/bin/bash
set -euo pipefail

# ─────────────────────────────────────────────
# SBAI - SB선보 P&ID 도면 AI 변환 시스템
# OCI Container Instance 배포 스크립트
# ─────────────────────────────────────────────

REGION="${OCI_REGION:-ap-chuncheon-1}"
NAMESPACE="${OCI_NAMESPACE:-axz2nubbzory}"
COMPARTMENT_ID="${OCI_COMPARTMENT_ID:-ocid1.tenancy.oc1..aaaaaaaaqqvkziyie25od72fkzlr2nscaeczaqpvpkcsmbmzlnlke3ljspxq}"
SUBNET_ID="${OCI_SUBNET_ID:-ocid1.subnet.oc1.ap-chuncheon-1.aaaaaaaanivd55ra4jfhrywi3qnajqc2iw67gugele6yqtfdhtz22n3yvmja}"
AD="${OCI_AD:-AvAs:AP-CHUNCHEON-1-AD-1}"

REGISTRY="${REGION}.ocir.io/${NAMESPACE}"
BACKEND_IMAGE="${REGISTRY}/sbai-backend:latest"
FRONTEND_IMAGE="${REGISTRY}/sbai-frontend:latest"

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

check_prerequisites() {
    info "사전 요구사항 확인 중..."
    command -v docker >/dev/null 2>&1 || error "Docker가 설치되지 않았습니다"
    command -v oci >/dev/null 2>&1    || error "OCI CLI가 설치되지 않았습니다"
    docker info >/dev/null 2>&1       || error "Docker 데몬이 실행 중이 아닙니다"
    info "사전 요구사항 확인 완료"
}

build_images() {
    info "Docker 이미지 빌드 중..."
    info "  Backend 이미지 빌드..."
    docker build -t sbai-backend "${PROJECT_ROOT}/backend"
    info "  Frontend 이미지 빌드 (OCI용 nginx.conf)..."
    docker build --build-arg NGINX_CONF=nginx.oci.conf -t sbai-frontend "${PROJECT_ROOT}/frontend"
    info "이미지 빌드 완료"
}

login_ocir() {
    info "OCIR 로그인..."
    OCIR_USER="${OCI_USER:-seungmin.lee@saltlux.com}"
    docker login "${REGION}.ocir.io" -u "${NAMESPACE}/${OCIR_USER}"
    info "OCIR 로그인 완료"
}

push_images() {
    info "이미지 태그 지정..."
    docker tag sbai-backend  "$BACKEND_IMAGE"
    docker tag sbai-frontend "$FRONTEND_IMAGE"
    info "OCIR에 이미지 푸시 중..."
    docker push "$BACKEND_IMAGE"
    docker push "$FRONTEND_IMAGE"
    info "이미지 푸시 완료"
}

generate_ci_config() {
    info "Container Instance 설정 JSON 생성..."

    ENV_FILE="${PROJECT_ROOT}/backend/.env"
    ANTHROPIC_KEY=""
    OPENAI_KEY=""
    GOOGLE_KEY=""
    if [ -f "$ENV_FILE" ]; then
        ANTHROPIC_KEY=$(grep "^ANTHROPIC_API_KEY=" "$ENV_FILE" | cut -d'=' -f2- || echo "")
        OPENAI_KEY=$(grep "^OPENAI_API_KEY=" "$ENV_FILE" | cut -d'=' -f2- || echo "")
        GOOGLE_KEY=$(grep "^GOOGLE_API_KEY=" "$ENV_FILE" | cut -d'=' -f2- || echo "")
    fi

    cat > "${PROJECT_ROOT}/deploy/container-instance.json" << CIEOF
{
  "displayName": "sbai-platform",
  "compartmentId": "${COMPARTMENT_ID}",
  "availabilityDomain": "${AD}",
  "shape": "CI.Standard.E4.Flex",
  "shapeConfig": {
    "ocpus": 1,
    "memoryInGBs": 8
  },
  "vnics": [
    {
      "subnetId": "${SUBNET_ID}",
      "isPublicIpAssigned": true
    }
  ],
  "containers": [
    {
      "displayName": "backend",
      "imageUrl": "${BACKEND_IMAGE}",
      "environmentVariables": {
        "ANTHROPIC_API_KEY": "${ANTHROPIC_KEY}",
        "OPENAI_API_KEY": "${OPENAI_KEY}",
        "GOOGLE_API_KEY": "${GOOGLE_KEY}",
        "DEBUG": "false"
      }
    },
    {
      "displayName": "frontend",
      "imageUrl": "${FRONTEND_IMAGE}"
    }
  ]
}
CIEOF
    info "설정 파일 생성: deploy/container-instance.json"
}

create_container_instance() {
    info "Container Instance 생성 중..."

    CI_JSON="${PROJECT_ROOT}/deploy/container-instance.json"
    [ -f "$CI_JSON" ] || error "container-instance.json이 없습니다. generate 명령을 먼저 실행하세요."

    RESULT=$(oci container-instances container-instance create \
        --from-json "file://${CI_JSON}" \
        --wait-for-state ACTIVE \
        --wait-interval-seconds 30 \
        --max-wait-seconds 600 2>&1) || true

    echo "$RESULT"

    CI_ID=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['id'])" 2>/dev/null || echo "")

    if [ -n "$CI_ID" ]; then
        info "Container Instance 생성 완료: $CI_ID"
        sleep 10
        VNIC_ID=$(oci container-instances container-instance get \
            --container-instance-id "$CI_ID" \
            --query "data.vnics[0].\"vnic-id\"" \
            --raw-output 2>/dev/null || echo "")
        if [ -n "$VNIC_ID" ]; then
            IP=$(oci network vnic get \
                --vnic-id "$VNIC_ID" \
                --query "data.\"public-ip\"" \
                --raw-output 2>/dev/null || echo "조회 실패")
        else
            IP="조회 실패 - OCI 콘솔에서 확인하세요"
        fi
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        info "SBAI 플랫폼 접속 주소: http://${IP}"
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    else
        warn "Container Instance ID를 파싱할 수 없습니다. OCI 콘솔에서 확인하세요."
    fi
}

healthcheck() {
    IP="${1:-}"
    [ -n "$IP" ] || error "사용법: $0 healthcheck <IP주소>"
    info "헬스체크 실행: http://${IP}"

    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://${IP}/api/health" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        info "  Backend: OK (${HTTP_CODE})"
    else
        warn "  Backend: FAIL (${HTTP_CODE})"
    fi

    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://${IP}/" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        info "  Frontend: OK (${HTTP_CODE})"
    else
        warn "  Frontend: FAIL (${HTTP_CODE})"
    fi
}

usage() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  SBAI - SB선보 P&ID 도면 AI 변환 시스템"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "사용법: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  check              사전 요구사항 확인"
    echo "  build              Docker 이미지 빌드"
    echo "  login              OCIR 로그인"
    echo "  push               이미지 태그 & OCIR 푸시"
    echo "  generate           Container Instance JSON 설정 생성"
    echo "  deploy             Container Instance 생성 (OCI)"
    echo "  healthcheck <IP>   배포 후 헬스체크"
    echo "  all                전체 파이프라인 (build → login → push → generate → deploy)"
    echo ""
}

CMD="${1:-}"
case "$CMD" in
    check)       check_prerequisites ;;
    build)       build_images ;;
    login)       login_ocir ;;
    push)        push_images ;;
    generate)    generate_ci_config ;;
    deploy)      create_container_instance ;;
    healthcheck) healthcheck "${2:-}" ;;
    all)
        check_prerequisites
        build_images
        login_ocir
        push_images
        generate_ci_config
        create_container_instance
        ;;
    *)
        usage
        exit 1
        ;;
esac
