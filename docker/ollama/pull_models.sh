#!/bin/sh
# docker/ollama/pull_models.sh
# Ollama 模型预加载脚本（init 容器）
set -e

OLLAMA_HOST="${OLLAMA_HOST:-http://ollama:11434}"
LLM_MODEL="${OLLAMA_MODEL:-qwen2.5:14b}"
EMBED_MODEL="${EMBEDDING_MODEL:-bge-m3}"

echo "[ollama-init] Waiting for Ollama to be ready..."
for i in $(seq 1 30); do
    if curl -sf "${OLLAMA_HOST}/" > /dev/null 2>&1; then
        echo "[ollama-init] Ollama is ready."
        break
    fi
    echo "[ollama-init] Attempt $i/30 — retrying in 5s..."
    sleep 5
done

echo "[ollama-init] Pulling LLM model: ${LLM_MODEL}"
OLLAMA_HOST="${OLLAMA_HOST}" ollama pull "${LLM_MODEL}" || echo "[WARN] Failed to pull ${LLM_MODEL}"

echo "[ollama-init] Pulling embedding model: ${EMBED_MODEL}"
OLLAMA_HOST="${OLLAMA_HOST}" ollama pull "${EMBED_MODEL}" || echo "[WARN] Failed to pull ${EMBED_MODEL}"

echo "[ollama-init] Model preload complete."
