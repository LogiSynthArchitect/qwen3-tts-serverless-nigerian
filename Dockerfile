# ---------------------------------------------------------------------------
# Baked Qwen3-TTS VoiceDesign image for Vast.ai
#
# Extends vastai/pytorch (which already ships torch + CUDA 12.8) so we do NOT
# re-download the ~3GB pip CUDA stack at instance start. All heavy install
# happens at BUILD time here. Result: instance cold-start drops from ~7 min
# (pip install onstart) to ~1 min (small layer pull + boot).
#
# Built & pushed to GHCR by .github/workflows/build-image.yml (GitHub Actions,
# no local docker needed). Vast pulls ghcr.io/<owner>/<name>:latest.
# ---------------------------------------------------------------------------
FROM vastai/pytorch:cuda-12.8.1-auto

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    APP_DIR=/workspace/qwen3-tts \
    MODEL_TYPE=VoiceDesign \
    PORT=8000

# System deps (libsox/ffmpeg for torchaudio backend) baked in.
RUN apt-get update -qq && apt-get install -y -qq ffmpeg libsox-dev sox \
    && rm -rf /var/lib/apt/lists/*

# Python deps baked in. Base image already has torch/torchaudio/CUDA12.8,
# so install qwen-tts --no-deps + only the bounded pure-Python deps it needs.
RUN pip install --no-cache-dir --no-deps qwen-tts \
    && pip install --no-cache-dir --no-cache-dir \
        "transformers==4.57.3" "accelerate==1.12.0" onnxruntime \
        fastapi uvicorn runpod boto3 librosa soundfile numpy hf_transfer

# Clone app code into the image so onstart is instant (no git pull at boot).
RUN rm -rf "$APP_DIR" \
    && git clone https://github.com/LogiSynthArchitect/qwen3-tts-serverless-nigerian.git "$APP_DIR" \
    && python3 -c "import qwen_tts; print('qwen_tts OK', qwen_tts.__file__)"

WORKDIR /workspace

# onstart entrypoint: just launch serve.py (env already set, deps baked).
COPY vast_start.sh /workspace/vast_start.sh
RUN chmod +x /workspace/vast_start.sh

CMD ["bash", "/workspace/vast_start.sh"]
