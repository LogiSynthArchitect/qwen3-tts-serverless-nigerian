# ---------------------------------------------------------------------------
# Qwen3-TTS VoiceDesign — Custom Docker Image
#
# Base: vastai/pytorch (cached on most Vast hosts → fast cold start)
# Build: Google Cloud Build (free, 120 min/day, triggered on push to main)
# Push: Docker Hub (free, unlimited public pulls)
# Run: Vast AI template referencing docker.io/cybocrime/qwen3-tts:latest
#
# Cold start: 5-60 sec (layer cache hit) vs 0-7 min (old tarball approach)
# Failure points: 1 (Docker pull) vs 4 (old: pull + curl + extract + pip)
# ---------------------------------------------------------------------------
FROM vastai/pytorch:cuda-12.6.3-auto
# Clear base image ENTRYPOINT so our CMD runs directly (not passed as args)
ENTRYPOINT []

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    APP_DIR=/workspace/qwen3-tts \
    MODEL_TYPE=VoiceDesign \
    PORT=8000

# System dependencies (libsox/ffmpeg for torchaudio backend)
RUN apt-get update -qq && apt-get install -y -qq ffmpeg libsox-dev sox \
    && rm -rf /var/lib/apt/lists/*

# Copy the entire application code (replaces old tarball fetch at boot)
COPY . "$APP_DIR"
WORKDIR "$APP_DIR"

# Install Python dependencies
# qwen-tts 0.1.1 requires pinned versions of transformers/accelerate
# torchaudio + einops are runtime deps (not --no-deps from qwen-tts)
# torchaudio installed with --no-deps to avoid torch version conflicts
# (base image already has torch with CUDA 12.6)
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps qwen-tts torchaudio \
    && pip install --no-cache-dir \
        "transformers==4.57.3" "accelerate==1.12.0" \
        "einops" onnxruntime sox

# Validate critical imports
RUN python3 -c "import torch; print('torch', torch.__version__, 'CUDA available:', torch.cuda.is_available())" \
    && python3 -c "import torchaudio; print('torchaudio', torchaudio.__version__)" \
    && python3 -c "import qwen_tts; print('qwen-tts OK:', qwen_tts.__file__)"

# Expose TTS API port
EXPOSE 8000

# Serve (no git pull, no pip install at boot — everything is baked in)
# Base image vastai/pytorch provides python3 (no bare "python" symlink)
CMD ["python3", "serve.py"]
