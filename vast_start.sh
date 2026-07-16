#!/bin/bash
# Vast.ai instance start script (run via onstart).
# Base image: vastai/pytorch:cuda-12.8.1-auto (CUDA 12.8 + torch + torchaudio
# pre-installed in SYSTEM python and pre-validated together). We use the base
# system python (already has working torch/torchaudio) and add:
#   - qwen-tts (PyPI) -> provides the `qwen_tts` module our handler needs
#   - our app repo (FastAPI serve wrapper)
# A diagnostic HTTP server on :8001 serves /log and /ps so we can debug without
# SSH (Vast SSH key is also configured for direct access).
LOG=/workspace/onstart.log
exec > >(tee -a "$LOG") 2>&1

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

# --- start diagnostic server immediately (so /log is always reachable) ---
nohup $PY "$APP_DIR/diag.py" >/workspace/diag.log 2>&1 &
echo "diag pid $!"

# If APP_DIR not yet cloned (defensive), still serve a minimal log at /workspace
if [ ! -f "$APP_DIR/diag.py" ]; then
  cat > /workspace/diag_stub.py <<'EOF'
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type","application/json")
        try:
            log=open("/workspace/onstart.log").read()[-8000:]
        except Exception as e:
            log=f"(no log: {e})"
        body=json.dumps({"log":log}).encode()
        self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self,*a): pass
ThreadingHTTPServer(("0.0.0.0",8001),H).serve_forever()
EOF
  nohup $PY /workspace/diag_stub.py >/workspace/diag_stub.log 2>&1 &
fi

echo "=== installing qwen-tts (PyPI) into system python ==="
pip install --break-system-packages --no-cache-dir qwen-tts
$PY -c "import qwen_tts; print('qwen_tts OK', qwen_tts.__file__)" || echo "QWEN_TTS IMPORT FAILED"

echo "=== cloning app code ==="
rm -rf "$APP_DIR"
git clone "$REPO" "$APP_DIR"
cd "$APP_DIR"

echo "=== installing app deps ==="
pip install --break-system-packages --no-cache-dir fastapi uvicorn runpod boto3 librosa soundfile numpy hf_transfer

echo "=== ffmpeg/sox (torchaudio backend) ==="
apt-get update -qq && apt-get install -y -qq ffmpeg libsox-dev sox 2>/dev/null || echo "apt install skipped"

echo "=== Launching HTTP server (serve.py) on :$PORT (auto-restart) ==="
cd "$APP_DIR"
set +e
while true; do
  echo "--- serve.py start $(date) ---"
  $PY "$APP_DIR/serve.py" >> "$LOG" 2>&1
  echo "--- serve.py exited $(date), restart in 5s ---"
  sleep 5
done
