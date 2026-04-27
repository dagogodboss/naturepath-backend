#!/usr/bin/env bash
# Build API image with Colima/Docker, push to ECR, force ECS rolling deploy.
# Prereqs: aws login (or valid creds), colima start, docker context = colima.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
export REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
export ECR_REPOSITORY="${ECR_REPOSITORY:-natural-path-api}"
export IMAGE_TAG="${DEPLOY_IMAGE_TAG:-$(git rev-parse --short HEAD)}"
export ECS_CLUSTER="${ECS_CLUSTER:-natural-path-prod}"
export ECS_SERVICE="${ECS_SERVICE:-natural-path-service}"

echo "Deploy: account=${AWS_ACCOUNT_ID} region=${AWS_REGION} image=${REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG}"

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not reachable. Start Colima: colima start" >&2
  exit 1
fi

aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$REGISTRY"

docker build --platform linux/amd64 \
  -t "${ECR_REPOSITORY}:${IMAGE_TAG}" \
  -f backend/Dockerfile \
  backend

docker tag "${ECR_REPOSITORY}:${IMAGE_TAG}" "${REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG}"
docker tag "${ECR_REPOSITORY}:${IMAGE_TAG}" "${REGISTRY}/${ECR_REPOSITORY}:latest"

docker push "${REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG}"
docker push "${REGISTRY}/${ECR_REPOSITORY}:latest"

aws ecs update-service \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --force-new-deployment \
  --region "$AWS_REGION" \
  --query 'service.{status:status,running:runningCount,desired:desiredCount,deployments:deployments[*].{status:status,rollout:rolloutState}}' \
  --output json

echo "Done: pushed ${REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG} and :latest; ECS rollout started."
