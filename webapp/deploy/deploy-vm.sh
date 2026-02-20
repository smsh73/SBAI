#!/bin/bash
set -euo pipefail

# ─────────────────────────────────────────────
# SBAI - SB선보 P&ID 도면 AI 변환 시스템
# OCI Compute VM 배포 스크립트 (고정 IP)
# ─────────────────────────────────────────────

REGION="${OCI_REGION:-ap-chuncheon-1}"
COMPARTMENT_ID="${OCI_COMPARTMENT_ID:-ocid1.compartment.oc1..aaaaaaaa3275p27ivkt2u722n64degacykpzkgbm3evcjto6jkm3rh3vppeq}"
SUBNET_ID="${OCI_SUBNET_ID:-ocid1.subnet.oc1.ap-chuncheon-1.aaaaaaaanivd55ra4jfhrywi3qnajqc2iw67gugele6yqtfdhtz22n3yvmja}"
AD="${OCI_AD:-AvAs:AP-CHUNCHEON-1-AD-1}"
# Oracle Linux 8.10 (2026.01.29)
IMAGE_ID="ocid1.image.oc1.ap-chuncheon-1.aaaaaaaa6mymminhhlcwnog3wmbufd42bhj5xemldflnysud2rb6hkkkx2wq"
SHAPE="VM.Standard.E4.Flex"

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSH_KEY_PUB="$HOME/.ssh/sbai_oci_vm.pub"
SSH_KEY_PRIV="$HOME/.ssh/sbai_oci_vm"
SSH_USER="opc"  # Oracle Linux default user

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

export SUPPRESS_LABEL_WARNING=True

# ── Reserved Public IP 생성 ──
create_reserved_ip() {
    info "Reserved Public IP 생성 중..."

    # 기존 Reserved IP 확인
    EXISTING_IP=$(oci network public-ip list \
        --compartment-id "${COMPARTMENT_ID}" \
        --scope REGION \
        --lifetime RESERVED \
        --query 'data[?"display-name"==`sbai-platform-ip`]."ip-address" | [0]' \
        --raw-output 2>/dev/null || echo "None")

    if [ "$EXISTING_IP" != "None" ] && [ -n "$EXISTING_IP" ]; then
        info "기존 Reserved IP 발견: ${EXISTING_IP}"
        echo "$EXISTING_IP" > "${PROJECT_ROOT}/deploy/.vm_public_ip"
        return
    fi

    RESULT=$(oci network public-ip create \
        --compartment-id "${COMPARTMENT_ID}" \
        --lifetime RESERVED \
        --display-name "sbai-platform-ip" 2>&1)

    IP=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['ip-address'])" 2>/dev/null || echo "")
    IP_ID=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['id'])" 2>/dev/null || echo "")

    if [ -n "$IP" ]; then
        info "Reserved IP 생성 완료: ${IP}"
        echo "$IP" > "${PROJECT_ROOT}/deploy/.vm_public_ip"
        echo "$IP_ID" > "${PROJECT_ROOT}/deploy/.reserved_ip_id"
    else
        warn "Reserved IP 생성 실패. VM 생성 시 자동 할당 IP를 사용합니다."
    fi
}

# ── VM 생성 ──
create_vm() {
    info "OCI Compute VM 생성 중..."

    [ -f "$SSH_KEY_PUB" ] || error "SSH 공개키가 없습니다: $SSH_KEY_PUB"

    # Reserved IP 확인
    RESERVED_IP_ID=""
    if [ -f "${PROJECT_ROOT}/deploy/.reserved_ip_id" ]; then
        RESERVED_IP_ID=$(cat "${PROJECT_ROOT}/deploy/.reserved_ip_id")
    fi

    # Cloud-init: OS 방화벽 포트 개방
    CLOUD_INIT=$(cat <<'CLOUDINIT'
#!/bin/bash
firewall-cmd --permanent --add-port=80/tcp
firewall-cmd --permanent --add-port=443/tcp
firewall-cmd --permanent --add-port=8000/tcp
firewall-cmd --reload
CLOUDINIT
)
    CLOUD_INIT_FILE=$(mktemp)
    echo "$CLOUD_INIT" > "$CLOUD_INIT_FILE"

    LAUNCH_ARGS=(
        --availability-domain "${AD}"
        --compartment-id "${COMPARTMENT_ID}"
        --display-name "sbai-platform-vm"
        --shape "${SHAPE}"
        --shape-config '{"ocpus":1,"memoryInGBs":8}'
        --subnet-id "${SUBNET_ID}"
        --image-id "${IMAGE_ID}"
        --ssh-authorized-keys-file "${SSH_KEY_PUB}"
        --user-data-file "${CLOUD_INIT_FILE}"
        --wait-for-state RUNNING
        --wait-interval-seconds 30
        --max-wait-seconds 600
    )

    # Reserved IP가 없으면 자동 할당
    if [ -z "$RESERVED_IP_ID" ]; then
        LAUNCH_ARGS+=(--assign-public-ip true)
    fi

    RESULT=$(oci compute instance launch "${LAUNCH_ARGS[@]}" 2>&1) || true
    rm -f "$CLOUD_INIT_FILE"

    INSTANCE_ID=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['id'])" 2>/dev/null || echo "")

    if [ -z "$INSTANCE_ID" ]; then
        echo "$RESULT"
        error "VM 생성 실패"
    fi

    info "VM 생성 완료: $INSTANCE_ID"
    echo "$INSTANCE_ID" > "${PROJECT_ROOT}/deploy/.vm_instance_id"

    # Reserved IP가 있으면 VNIC에 연결
    if [ -n "$RESERVED_IP_ID" ]; then
        info "Reserved IP를 VM에 연결 중..."
        sleep 10

        VNIC_ID=$(oci compute instance list-vnics \
            --instance-id "$INSTANCE_ID" \
            --query 'data[0]."id"' \
            --raw-output 2>/dev/null || echo "")

        if [ -n "$VNIC_ID" ]; then
            PRIVATE_IP_ID=$(oci network private-ip list \
                --vnic-id "$VNIC_ID" \
                --query 'data[0]."id"' \
                --raw-output 2>/dev/null || echo "")

            if [ -n "$PRIVATE_IP_ID" ]; then
                oci network public-ip update \
                    --public-ip-id "$RESERVED_IP_ID" \
                    --private-ip-id "$PRIVATE_IP_ID" \
                    --force 2>/dev/null || warn "Reserved IP 연결 실패. 수동 연결이 필요합니다."
            fi
        fi
    fi

    # 공인 IP 조회
    sleep 5
    VNIC_ID=$(oci compute instance list-vnics \
        --instance-id "$INSTANCE_ID" \
        --query 'data[0]."id"' \
        --raw-output 2>/dev/null || echo "")

    if [ -n "$VNIC_ID" ]; then
        PUBLIC_IP=$(oci network vnic get \
            --vnic-id "$VNIC_ID" \
            --query 'data."public-ip"' \
            --raw-output 2>/dev/null || echo "조회 실패")

        echo "$PUBLIC_IP" > "${PROJECT_ROOT}/deploy/.vm_public_ip"
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        info "VM 공인 IP: ${PUBLIC_IP}"
        info "SSH 접속: ssh -i ${SSH_KEY_PRIV} ${SSH_USER}@${PUBLIC_IP}"
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    else
        warn "VNIC ID 조회 실패. OCI 콘솔에서 확인하세요."
    fi
}

# ── VM 설정 (Docker 설치 - Oracle Linux 8) ──
setup_vm() {
    IP="${1:-$(cat "${PROJECT_ROOT}/deploy/.vm_public_ip" 2>/dev/null || echo "")}"
    [ -n "$IP" ] || error "사용법: $0 setup <IP주소>"

    info "VM에 Docker 설치 중... (${IP})"

    SSH_CMD="ssh -i ${SSH_KEY_PRIV} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ${SSH_USER}@${IP}"

    $SSH_CMD << 'SETUP_EOF'
set -e
echo "=== Docker 설치 (Oracle Linux 8) ==="

# Docker 설치
sudo dnf install -y dnf-utils
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Docker 시작
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER

# Docker Compose standalone
sudo curl -L "https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# git (파일 복사 후 빌드에 필요할 수 있음)
sudo dnf install -y git

echo "=== 설치 완료 ==="
docker --version
docker-compose --version
SETUP_EOF

    info "VM Docker 설치 완료"
}

# ── 프로젝트 파일 복사 ──
copy_files() {
    IP="${1:-$(cat "${PROJECT_ROOT}/deploy/.vm_public_ip" 2>/dev/null || echo "")}"
    [ -n "$IP" ] || error "사용법: $0 copy <IP주소>"

    info "프로젝트 파일을 VM으로 복사 중... (${IP})"

    SSH_OPTS="-i ${SSH_KEY_PRIV} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

    ssh $SSH_OPTS ${SSH_USER}@${IP} "mkdir -p ~/sbai"

    rsync -avz --progress \
        -e "ssh ${SSH_OPTS}" \
        --exclude 'node_modules' \
        --exclude '.git' \
        --exclude '__pycache__' \
        --exclude '*.pyc' \
        --exclude 'dist' \
        --exclude '.DS_Store' \
        --exclude 'test_extraction_output' \
        --exclude 'test_extraction.py' \
        "${PROJECT_ROOT}/" \
        "${SSH_USER}@${IP}:~/sbai/"

    info "파일 복사 완료"
}

# ── VM에서 배포 ──
deploy_on_vm() {
    IP="${1:-$(cat "${PROJECT_ROOT}/deploy/.vm_public_ip" 2>/dev/null || echo "")}"
    [ -n "$IP" ] || error "사용법: $0 deploy <IP주소>"

    info "VM에서 Docker Compose 배포 시작... (${IP})"

    ssh -i ${SSH_KEY_PRIV} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ${SSH_USER}@${IP} << 'DEPLOY_EOF'
set -e
cd ~/sbai

# newgrp docker 대신 sudo 사용 (첫 배포 시 docker 그룹 미반영)
sudo docker-compose down 2>/dev/null || true
sudo docker-compose up -d --build

echo "서비스 시작 대기 중 (20초)..."
sleep 20

sudo docker-compose ps

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "배포 완료!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
DEPLOY_EOF

    info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    info "SBAI 플랫폼 접속: http://${IP}"
    info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ── 업데이트 (파일 복사 + 재배포) ──
update() {
    IP="${1:-$(cat "${PROJECT_ROOT}/deploy/.vm_public_ip" 2>/dev/null || echo "")}"
    [ -n "$IP" ] || error "사용법: $0 update <IP주소>"

    copy_files "$IP"
    deploy_on_vm "$IP"
}

# ── 헬스체크 ──
healthcheck() {
    IP="${1:-$(cat "${PROJECT_ROOT}/deploy/.vm_public_ip" 2>/dev/null || echo "")}"
    [ -n "$IP" ] || error "사용법: $0 healthcheck <IP주소>"

    info "헬스체크: http://${IP}"

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

# ── VM 삭제 ──
delete_vm() {
    INSTANCE_FILE="${PROJECT_ROOT}/deploy/.vm_instance_id"
    [ -f "$INSTANCE_FILE" ] || error "VM 인스턴스 ID 파일이 없습니다"

    INSTANCE_ID=$(cat "$INSTANCE_FILE")
    info "VM 삭제 중: $INSTANCE_ID"

    oci compute instance terminate \
        --instance-id "$INSTANCE_ID" \
        --force \
        --wait-for-state TERMINATED

    rm -f "$INSTANCE_FILE"
    info "VM 삭제 완료 (Reserved IP는 유지됩니다)"
}

# ── 메인 ──
usage() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  SBAI - OCI VM 배포 (고정 IP)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "사용법: $0 <command> [IP]"
    echo ""
    echo "Commands:"
    echo "  create             Reserved IP + VM 생성"
    echo "  setup [IP]         Docker 설치"
    echo "  copy [IP]          프로젝트 파일 복사"
    echo "  deploy [IP]        Docker Compose 배포"
    echo "  update [IP]        파일 복사 + 재배포"
    echo "  healthcheck [IP]   헬스체크"
    echo "  delete             VM 삭제 (IP 유지)"
    echo "  all                전체 (create → setup → copy → deploy)"
    echo ""
    echo "IP를 생략하면 .vm_public_ip 파일에서 읽습니다."
    echo ""
}

CMD="${1:-}"
case "$CMD" in
    create)
        create_reserved_ip
        create_vm
        ;;
    setup)       setup_vm "${2:-}" ;;
    copy)        copy_files "${2:-}" ;;
    deploy)      deploy_on_vm "${2:-}" ;;
    update)      update "${2:-}" ;;
    healthcheck) healthcheck "${2:-}" ;;
    delete)      delete_vm ;;
    all)
        create_reserved_ip
        create_vm
        IP=$(cat "${PROJECT_ROOT}/deploy/.vm_public_ip" 2>/dev/null || echo "")
        if [ -n "$IP" ]; then
            info "60초 대기 (VM 부팅 완료)..."
            sleep 60
            setup_vm "$IP"
            copy_files "$IP"
            deploy_on_vm "$IP"
            sleep 20
            healthcheck "$IP"
        else
            error "VM IP 조회 실패"
        fi
        ;;
    *)
        usage
        exit 1
        ;;
esac
