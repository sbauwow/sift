#!/usr/bin/env bash
# Serve NVIDIA Nemotron as an OpenAI-compatible endpoint via vLLM.
#
# Run on the GPU box. sift's local rung points at http://<host>:8000 by default
# (override with SIFT_LOCAL_ENDPOINT). This is the vLLM + Nemotron bounty surface.
#
#   NEMOTRON_MODEL=nvidia/Nemotron-Mini-4B-Instruct ./scripts/serve_nemotron.sh
#
# Flags map to the README's committed vLLM surfaces:
#   --enable-prefix-caching   reuse the shared triage/RAG preamble KV across requests
#   --guided-decoding-backend schema/grammar-constrained outputs (triage/judge/answers)
# Add --quantization fp8 on Hopper/Ada, or an AWQ/INT4 checkpoint, for the quant tier.
set -euo pipefail

MODEL="${NEMOTRON_MODEL:-nvidia/Nemotron-Mini-4B-Instruct}"
PORT="${SIFT_LOCAL_PORT:-8000}"
EXTRA_ARGS=("$@")

echo "[sift] serving ${MODEL} on :${PORT} via vLLM"

if command -v vllm >/dev/null 2>&1; then
  exec vllm serve "${MODEL}" \
    --port "${PORT}" \
    --served-model-name "${MODEL}" \
    --enable-prefix-caching \
    --guided-decoding-backend xgrammar \
    "${EXTRA_ARGS[@]}"
fi

echo "[sift] vllm not on PATH — falling back to the official Docker image (needs --gpus all)."
exec docker run --rm --gpus all -p "${PORT}:8000" \
  -v "${HOME}/.cache/huggingface:/root/.cache/huggingface" \
  --env "HUGGING_FACE_HUB_TOKEN=${HUGGING_FACE_HUB_TOKEN:-}" \
  vllm/vllm-openai:latest \
  --model "${MODEL}" \
  --served-model-name "${MODEL}" \
  --enable-prefix-caching \
  --guided-decoding-backend xgrammar \
  "${EXTRA_ARGS[@]}"

# Optional second instance for hidden-state features (deferred in the MVP):
#   vllm serve "${MODEL}" --task embed --port 8001
