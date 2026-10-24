#!/usr/bin/env bash
# Start Omega (singnet/Omega v0.1.20) in Docker with the World Tennis plugin.
# Keys and settings come from .env. Logs: docker logs -f omega-tennis
set -euo pipefail
cd "$(dirname "$0")"
if [ -f .env ]; then set -a; . ./.env; set +a; fi

IMAGE="${IMAGE:-singularitynet/omega:v0.1.20}"
PROVIDER="${PROVIDER:-OpenAIAPI}"
PORT="${PORT:-8787}"
if [ "$PROVIDER" = "Anthropic" ]; then ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-claude-sonnet-5-5}"; MODEL=""; fi
if [ "$PROVIDER" != "OpenAIAPI" ]; then OPENAIAPI_URL=""; fi

case "$PROVIDER" in
  OpenAIAPI)  KEY_VAR=OPENAIAPI_API_KEY;  EMB=Local ;;
  Anthropic)  KEY_VAR=ANTHROPIC_API_KEY;  EMB=Local ;;
  OpenAI)     KEY_VAR=OPENAI_API_KEY;     EMB=OpenAI ;;
  ASIOne)     KEY_VAR=ASIONE_API_KEY;     EMB=Local ;;
  *) echo "Unknown PROVIDER $PROVIDER"; exit 1 ;;
esac
if [ -z "${!KEY_VAR:-}" ]; then
  echo "No $KEY_VAR found. Put it in .env"; exit 1
fi

docker rm -f omega-tennis >/dev/null 2>&1 || true
docker run -d -it \
  --name omega-tennis --init \
  --security-opt no-new-privileges:true \
  --add-host=host.docker.internal:host-gateway \
  --tmpfs /tmp:size=64m,mode=1777 \
  --tmpfs /var/tmp:size=64m,mode=1777 \
  --tmpfs /run:size=16m,mode=755 \
  --volume omega-tennis-memory:/PeTTa/repos/Omega/memory \
  --volume "$PWD/omega-plugin/tennis:/PeTTa/repos/Omega/plugins/tennis:ro" \
  --volume "$PWD/omega-plugin/plugins.yaml:/PeTTa/repos/Omega/config/plugins.yaml:ro" \
  -e "$KEY_VAR=${!KEY_VAR}" \
  -e OMEGA_AUTH_SECRET="${OMEGA_AUTH_SECRET:-0000}" \
  -e IMPORT_KB_ON_START=0 \
  "$IMAGE" \
  commchannel=websocket \
  "provider=$PROVIDER" \
  "embeddingprovider=$EMB" \
  securityPolicyPath=/PeTTa/repos/Omega/profile/policy.yaml \
  "WS_URL=ws://host.docker.internal:$PORT/agent" \
  WS_TOKEN= \
  ${ANTHROPIC_MODEL:+"anthropic_model=$ANTHROPIC_MODEL"} \
  ${OPENAIAPI_URL:+"openaiapi_url=$OPENAIAPI_URL"} \
  ${MODEL:+"model=$MODEL"}

echo "Omega is starting with provider $PROVIDER. Watch: docker logs -f omega-tennis"
