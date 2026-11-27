#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Build, push, and deploy the RAG Chatbot to AWS ECS with EFS
# =============================================================================
# Prerequisites:
#   - AWS CLI v2 configured with correct credentials
#   - Docker installed and running
#   - ECR repository created:  rag-chatbot
#   - ECS cluster created
#   - SSM parameters stored (see README)
#   - EFS file system fs-003e4c4a500b481ba exists with mount targets in ECS subnets
# =============================================================================

set -euo pipefail

# ---- Configuration ----
AWS_ACCOUNT_ID="377074487303"
AWS_REGION="ap-southeast-2"
ECR_REPO="rag-chatbot"
ECS_CLUSTER="rag-chatbot-cluster"       # <-- Set your ECS cluster name
WEB_SERVICE="rag-chatbot-web-svc"       # <-- Set your ECS web service name
WORKER_SERVICE="rag-chatbot-worker-svc" # <-- Set your ECS worker service name

ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="${SCRIPT_DIR}/../infra/ecs"

echo "============================================="
echo " RAG Chatbot — ECS Deployment"
echo "============================================="

# ---- Step 1: Authenticate Docker with ECR ----
echo ""
echo "[1/6] Authenticating Docker with ECR..."
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${ECR_URI}"

# ---- Step 2: Build Docker image ----
echo ""
echo "[2/6] Building Docker image..."
docker build -t "${ECR_REPO}:latest" ./backend/

# ---- Step 3: Tag and push to ECR ----
echo ""
echo "[3/6] Pushing image to ECR..."
docker tag "${ECR_REPO}:latest" "${ECR_URI}:latest"
docker push "${ECR_URI}:latest"

# ---- Step 4: Register ECS Task Definitions ----
echo ""
echo "[4/6] Registering ECS task definitions..."

echo "  -> Web task definition..."
aws ecs register-task-definition \
  --cli-input-json "file://${INFRA_DIR}/task-def-web.json" \
  --region "${AWS_REGION}" > /dev/null

echo "  -> Worker task definition..."
aws ecs register-task-definition \
  --cli-input-json "file://${INFRA_DIR}/task-def-worker.json" \
  --region "${AWS_REGION}" > /dev/null

# ---- Step 5: Update ECS Services ----
echo ""
echo "[5/6] Updating ECS services to use new task definitions..."

echo "  -> Updating web service..."
aws ecs update-service \
  --cluster "${ECS_CLUSTER}" \
  --service "${WEB_SERVICE}" \
  --task-definition rag-chatbot-web \
  --force-new-deployment \
  --region "${AWS_REGION}" > /dev/null

echo "  -> Updating worker service..."
aws ecs update-service \
  --cluster "${ECS_CLUSTER}" \
  --service "${WORKER_SERVICE}" \
  --task-definition rag-chatbot-worker \
  --force-new-deployment \
  --region "${AWS_REGION}" > /dev/null

# ---- Step 6: Wait for stability ----
echo ""
echo "[6/6] Waiting for services to stabilize..."
echo "  (This may take 2-5 minutes...)"

aws ecs wait services-stable \
  --cluster "${ECS_CLUSTER}" \
  --services "${WEB_SERVICE}" "${WORKER_SERVICE}" \
  --region "${AWS_REGION}"

echo ""
echo "============================================="
echo " Deployment complete!"
echo "============================================="
echo " Web Service:    ${WEB_SERVICE}"
echo " Worker Service: ${WORKER_SERVICE}"
echo " EFS Volume:     fs-003e4c4a500b481ba:/faiss_store"
echo " ECR Image:      ${ECR_URI}:latest"
echo "============================================="
