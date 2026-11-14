#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

: "${BEDROCK_MODEL_ID:?Set a Bedrock model or inference profile available in the workshop account}"
export AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
stack_prefix="${STACK_PREFIX:-alphaforge}"
image_tag="${IMAGE_TAG:-$(git rev-parse --short=12 HEAD)-$(date -u +%Y%m%d%H%M%S)}"

aws sts get-caller-identity --query Account --output text
aws cloudformation deploy --stack-name "$stack_prefix-registry" \
  --template-file deploy/registry.yml --no-fail-on-empty-changeset

stack_output() {
  aws cloudformation describe-stacks --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue | [0]" --output text
}

repo="$(stack_output "$stack_prefix-registry" RepositoryUri)"
registry="${repo%%/*}"
aws ecr get-login-password | docker login --username AWS --password-stdin "$registry"
docker build --platform linux/amd64 -t "$repo:$image_tag" .
container="$(docker run -d --read-only --tmpfs /dev/shm -p 127.0.0.1::8080 "$repo:$image_tag")"
trap 'docker rm -f "$container" >/dev/null' EXIT
port="$(docker port "$container" 8080/tcp | cut -d: -f2)"
curl --fail --silent --show-error --max-time 5 --retry 12 --retry-all-errors --retry-delay 1 "http://127.0.0.1:$port/api/health/"
curl --fail --silent --show-error --max-time 5 "http://127.0.0.1:$port/" > /dev/null
docker rm -f "$container" >/dev/null
trap - EXIT
docker push "$repo:$image_tag"

aws cloudformation deploy --stack-name "$stack_prefix-service" \
  --template-file deploy/service.yml --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
  --parameter-overrides "Image=$repo:$image_tag" "BedrockModelId=$BEDROCK_MODEL_ID"

endpoint="$(stack_output "$stack_prefix-service" Endpoint)"
case "$endpoint" in
  https://*|http://*) ;;
  *) endpoint="https://$endpoint" ;;
esac
endpoint="${endpoint%/}"
curl --fail --silent --show-error --max-time 15 --retry 10 --retry-all-errors --retry-delay 5 "$endpoint/api/health/"
curl --fail --silent --show-error --max-time 15 "$endpoint/" > /dev/null
curl --fail --silent --show-error --max-time 40 "$endpoint/api/analysis/?ticker=NVDA&date=2024-08-29&profile=robert" |
  python -c 'import json,sys; r=json.load(sys.stdin); assert r["event"]["mode"] == r["impact"]["mode"] == "bedrock", "Les deux agents doivent répondre via Bedrock"'
printf '\nApplication : %s\n' "$endpoint"
