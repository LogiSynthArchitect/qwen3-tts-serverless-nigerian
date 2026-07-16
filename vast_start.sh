#!/bin/bash
# Vast.ai instance start script (run via onstart).
# Base image: vastai/pytorch:cuda-12.8.1-auto (CUDA 12.8 + torch + torchaudio
# pre-installed in SYSTEM python and pre-validated together). We use the base
# system python (already has working torch/torchaudio) and only add pure-python
# deps + the upstream qwen_tts package.
#
# ALL output is teed to /workspace/onstart.log so it can be inspected over HTTP
# via the diagnostic server started at the end (even if serve.py fails to import).
LOG=/workspace/onstart.log
exec > >(tee -a "$LOG") 2>&1
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

echo "=== [$(date)] Vast start begin ==="
$PY --version
$PY -c "import torch, torchaudio; print('torch', torch.__version__, 'torchaudio', torchaudio.__version__, 'cuda', torch.cuda.is_available())" || echo "TORCH IMPORT FAILED"

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
apt-get update -qq && apt-get install -y -qq ffmpeg libsox-dev sox 2>/dev/null || echo "apt install skipped"

echo "=== Launching HTTP server (serve.py) on :$PORT ==="
cd "$APP_DIR"
# Use a small wrapper that restarts serve.py on crash and logs to the same file.
set +e
while true; do
  echo "--- serve.py start $(date) ---"
  $PY "$APP_DIR/serve.py" >> "$LOG" 2>&1
  echo "--- serve.py exited $(date), restart in 5s ---"
  sleep 5
done
