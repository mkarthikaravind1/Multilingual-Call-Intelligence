#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=========================================================="
echo "Starting Call Analysis LLM Server (CPU / llama.cpp Stack)"
echo "=========================================================="

if [ ! -f .env ]; then
    echo "[!] .env not found. Copying .env.example to .env..."
    cp .env.example .env
fi

set -a
source .env
set +a

if command -v docker &> /dev/null && docker compose version &> /dev/null; then
    echo "[+] Launching CPU profile with Docker Compose..."
    docker compose --profile cpu up -d --build
    echo "[+] CPU Service running on port ${PROXY_PORT:-8091}"
else
    echo "[!] Docker not found. Starting Gateway Proxy in development mode..."
    ALLOW_MOCK_FALLBACK=true python3 proxy/main.py
fi
