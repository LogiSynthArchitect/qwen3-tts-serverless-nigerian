#!/bin/bash
# Vast.ai instance start script (run via onstart).
# Base image: vastai/pytorch:cuda-12.8.1-auto (CUDA 12.8 + torch pre-installed).
# This script clones our app code, installs app-level deps (NOT torch - already
# present in base), downloads Qwen3-TTS models on first run, and launches the
# HTTP server (serve.py) on port 8000.
set -e

export DEBIAN_FRONTEND=noninteractive
export PIP_NO_CACHE_DIR=1
export PYTHONUNBUFFERED=1
export MODEL_TYPE="${MODEL_TYPE:-VoiceDesign}"
export PORT="${PORT:-8000}"

APP_DIR=/workspace/qwen3-tts
REPO=https://github.com/LogiSynthArchitect/qwen3-tts-serverless-nigerian.git

echo "=== Vast start: cloning app code ==="
rm -rf "$APP_DIR"
git clone "$REPO" "$APP_DIR"
cd "$APP_DIR"

echo "=== Creating venv ==="
python3 -m venv "$APP_DIR/venv"
source "$APP_DIR/venv/bin/activate"

echo "=== Installing app deps (torch already in base; skip reinstall) ==="
# Install everything except torch/flash-attn/torchaudio (provided by base image).
pip install --no-cache-dir fastapi uvicorn runpod boto3 librosa soundfile numpy hf_transfer
pip install --no-cache-dir -e . 2>/dev/null || pip install --no-cache-dir -r requirements.txt || true

echo "=== Launching HTTP server (serve.py) on :$PORT ==="
exec python "$APP_DIR/serve.py"
