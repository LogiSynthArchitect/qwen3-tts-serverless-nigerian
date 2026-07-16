#!/bin/bash
# Vast.ai instance start script.
#
# When run from the BAKED image (Dockerfile), all deps + app code are already
# present in the image layers, so this just launches serve.py -> cold-start
# is ~1 min (small layer pull + boot), not ~7 min (pip install at boot).
#
# For safety it re-pulls the app repo if missing/stale, but does NOT re-run pip
# (that's baked in). A diagnostic server on :8001 serves /log and /ps.
LOG=/workspace/onstart.log
exec > >(tee -a "$LOG") 2>&1

export DEBIAN_FRONTEND=noninteractive
export PYTHONUNBUFFERED=1
export MODEL_TYPE="${MODEL_TYPE:-VoiceDesign}"
export PORT="${PORT:-8000}"
export HF_HUB_ENABLE_HF_TRANSFER=1

APP_DIR=/workspace/qwen3-tts
REPO=https://github.com/LogiSynthArchitect/qwen3-tts-serverless-nigerian.git
PY=python3

echo "=== [$(date)] Vast start begin (baked image) ==="
$PY --version
$PY -c "import torch, torchaudio, qwen_tts; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), 'qwen_tts OK')" || echo "IMPORT CHECK FAILED"

# --- diagnostic server (always reachable for remote debugging) ---
if [ -f "$APP_DIR/diag.py" ]; then
  nohup $PY "$APP_DIR/diag.py" >/workspace/diag.log 2>&1 &
else
  cat > /workspace/diag_stub.py <<'EOF'
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type","application/json")
        try: log=open("/workspace/onstart.log").read()[-8000:]
        except Exception as e: log=f"(no log: {e})"
        body=json.dumps({"log":log}).encode()
        self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self,*a): pass
ThreadingHTTPServer(("0.0.0.0",8001),H).serve_forever()
EOF
  nohup $PY /workspace/diag_stub.py >/workspace/diag_stub.log 2>&1 &
fi

# --- ensure app code is present / fresh (no pip, deps are baked) ---
if [ ! -d "$APP_DIR/.git" ]; then
  echo "=== cloning app code (not in image) ==="
  git clone "$REPO" "$APP_DIR"
else
  echo "=== pulling latest app code ==="
  (cd "$APP_DIR" && git pull --ff-only) || echo "git pull skipped"
fi
cd "$APP_DIR"

echo "=== Launching HTTP server (serve.py) on :$PORT (auto-restart) ==="
set +e
while true; do
  echo "--- serve.py start $(date) ---"
  $PY "$APP_DIR/serve.py" >> "$LOG" 2>&1
  echo "--- serve.py exited $(date), restart in 5s ---"
  sleep 5
done
