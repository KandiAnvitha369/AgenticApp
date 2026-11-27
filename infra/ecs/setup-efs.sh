#!/usr/bin/env bash
# =============================================================================
# setup-efs.sh — One-time setup for EFS mount targets and security groups
# =============================================================================
# Run this ONCE before deploying ECS services. It:
#   1. Creates a security group for EFS that allows NFS (port 2049) from ECS tasks
#   2. Creates mount targets in each of your ECS subnets
#   3. Creates the /faiss_store root directory on the EFS volume
# =============================================================================

set -euo pipefail

# ---- Configuration (UPDATE THESE) ----
AWS_REGION="ap-southeast-2"
EFS_FILE_SYSTEM_ID="fs-003e4c4a500b481ba"
VPC_ID="vpc-XXXXXXXXX"                       # <-- Your VPC ID
ECS_SUBNETS=("subnet-XXXXXXXXX" "subnet-YYYYYYYYY")  # <-- Your ECS private subnets
ECS_SECURITY_GROUP="sg-XXXXXXXXX"             # <-- Your ECS tasks security group

echo "============================================="
echo " EFS Setup for RAG Chatbot"
echo "============================================="

# ---- Step 1: Create EFS Security Group ----
echo ""
echo "[1/3] Creating EFS security group..."

EFS_SG_ID=$(aws ec2 create-security-group \
  --group-name "rag-chatbot-efs-sg" \
  --description "Allow NFS from ECS tasks to EFS" \
  --vpc-id "${VPC_ID}" \
  --region "${AWS_REGION}" \
  --query 'GroupId' --output text 2>/dev/null || \
  aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=rag-chatbot-efs-sg" "Name=vpc-id,Values=${VPC_ID}" \
    --region "${AWS_REGION}" \
    --query 'SecurityGroups[0].GroupId' --output text)

echo "  EFS Security Group: ${EFS_SG_ID}"

# Allow inbound NFS (port 2049) from the ECS tasks security group
aws ec2 authorize-security-group-ingress \
  --group-id "${EFS_SG_ID}" \
  --protocol tcp \
  --port 2049 \
  --source-group "${ECS_SECURITY_GROUP}" \
  --region "${AWS_REGION}" 2>/dev/null || echo "  (Inbound rule already exists)"

echo "  Inbound NFS rule configured."

# ---- Step 2: Create Mount Targets ----
echo ""
echo "[2/3] Creating EFS mount targets in each subnet..."

for SUBNET in "${ECS_SUBNETS[@]}"; do
  echo "  -> Subnet: ${SUBNET}"
  aws efs create-mount-target \
    --file-system-id "${EFS_FILE_SYSTEM_ID}" \
    --subnet-id "${SUBNET}" \
    --security-groups "${EFS_SG_ID}" \
    --region "${AWS_REGION}" 2>/dev/null || echo "    (Mount target already exists in ${SUBNET})"
done

echo "  Waiting for mount targets to become available..."
sleep 15

aws efs describe-mount-targets \
  --file-system-id "${EFS_FILE_SYSTEM_ID}" \
  --region "${AWS_REGION}" \
  --query 'MountTargets[*].{SubnetId:SubnetId,State:LifeCycleState,IP:IpAddress}' \
  --output table

# ---- Step 3: Create the /faiss_store directory ----
echo ""
echo "[3/3] MANUAL STEP: Create the /faiss_store directory on EFS"
echo ""
echo "  After mount targets are 'available', SSH into any EC2 instance in the same"
echo "  VPC (or use an ECS exec session) and run:"
echo ""
echo "    sudo mkdir -p /mnt/efs"
echo "    sudo mount -t nfs4 -o nfsvers=4.1 ${EFS_FILE_SYSTEM_ID}.efs.${AWS_REGION}.amazonaws.com:/ /mnt/efs"
echo "    sudo mkdir -p /mnt/efs/faiss_store"
echo "    sudo chmod 777 /mnt/efs/faiss_store"
echo "    sudo umount /mnt/efs"
echo ""
echo "  Or use EFS Access Points to auto-create the directory (recommended for production)."

echo ""
echo "============================================="
echo " EFS setup complete!"
echo "============================================="
echo " File System:  ${EFS_FILE_SYSTEM_ID}"
echo " Security Grp: ${EFS_SG_ID}"
echo " Root Dir:     /faiss_store"
echo "============================================="
