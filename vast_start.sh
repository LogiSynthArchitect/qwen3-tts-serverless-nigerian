#!/bin/bash
# Vast.ai instance start script (run via onstart).
# Base image: vastai/pytorch:cuda-12.8.1-auto (CUDA 12.8 + torch + torchaudio
# pre-installed in SYSTEM python and pre-validated together). We AVOID creating a
# venv and reinstalling torch (which caused a torchaudio ABI mismatch). Instead we
# use the base system python (already has working torch/torchaudio) and only add
# the pure-python deps + the upstream qwen_tts package.
set -e

export DEBIAN_FRONTEND=noninteractive
export PIP_NO_CACHE_DIR=1
export PYTHONUNBUFFERED=1
export MODEL_TYPE="${MODEL_TYPE:-VoiceDesign}"
export PORT="${PORT:-8000}"
export HF_HUB_ENABLE_HF_TRANSFER=1

APP_DIR=/workspace/qwen3-tts
REPO=https://github.com/LogiSynthArchitect/qwen3-tts-serverless-nigerian.git
PY=python3

echo "=== Vast start: python ==="
$PY --version
$PY -c "import torch, torchaudio; print('torch', torch.__version__, 'torchaudio', torchaudio.__version__, 'cuda', torch.cuda.is_available())"

echo "=== cloning app code ==="
rm -rf "$APP_DIR"
git clone "$REPO" "$APP_DIR"
cd "$APP_DIR"

echo "=== cloning upstream Qwen3-TTS (provides qwen_tts) ==="
rm -rf /opt/docker/Qwen3-TTS
git clone https://github.com/QwenLM/Qwen3-TTS.git /opt/docker/Qwen3-TTS

echo "=== installing deps into SYSTEM python (torch already present) ==="
pip install --break-system-packages --no-cache-dir fastapi uvicorn runpod boto3 librosa soundfile numpy hf_transfer
pip install --break-system-packages --no-cache-dir -e /opt/docker/Qwen3-TTS

echo "=== ffmpeg/sox (torchaudio backend) ==="
apt-get update -qq && apt-get install -y -qq ffmpeg libsox-dev sox 2>/dev/null || true

echo "=== Launching HTTP server (serve.py) on :$PORT via system python ==="
cd "$APP_DIR"
exec $PY "$APP_DIR/serve.py"
