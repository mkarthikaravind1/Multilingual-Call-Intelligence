#!/usr/bin/env bash
set -e

# Change directory to script's parent folder
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=========================================================="
echo "Starting Call Analysis LLM Server (GPU / vLLM Stack)"
echo "=========================================================="

# Check if .env exists, if not copy from .env.example
if [ ! -f .env ]; then
    echo "[!] .env not found. Copying .env.example to .env..."
    cp .env.example .env
fi

# Export variables from .env
set -a
source .env
set +a

# Verify Docker and NVIDIA runtime
if command -v docker &> /dev/null && docker compose version &> /dev/null; then
    echo "[+] Launching via Docker Compose with NVIDIA GPU..."
    docker compose --profile gpu up -d --build
    echo "[+] Services started!"
    echo "    - External Gateway API: http://localhost:${PROXY_PORT:-8091}"
    echo "    - Upstream vLLM Engine : http://localhost:8000"
    echo "    - Check health: curl -s http://localhost:${PROXY_PORT:-8091}/health"
else
    echo "[!] Docker not detected or running bare-metal."
    echo "[+] Launching vLLM directly via Python..."
    
    LORA_FLAG=""
    if [ "$ENABLE_LORA" = "true" ] && [ -n "$LORA_ADAPTER_PATH" ]; then
        LORA_FLAG="--enable-lora --lora-modules ${LORA_ADAPTER_NAME:-automotive-call-lora}=${LORA_ADAPTER_PATH}"
    fi

    # Launch vLLM in background
    python3 -m vllm.entrypoints.openai.api_server \
        --model "${MODEL_PATH:-openai/gpt-oss-20b}" \
        --port 8000 \
        --host 127.0.0.1 \
        --max-model-len "${MAX_MODEL_LEN:-8192}" \
        --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION:-0.90}" \
        --enable-prefix-caching \
        $LORA_FLAG &
    
    VLLM_PID=$!
    echo "[+] vLLM engine started with PID $VLLM_PID."

    echo "[+] Launching Reverse Proxy on port ${PROXY_PORT:-8091}..."
    UPSTREAM_ENGINE_URL="http://127.0.0.1:8000" python3 proxy/main.py
fi
