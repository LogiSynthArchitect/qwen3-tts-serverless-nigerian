FROM runpod/base:1.0.3-cuda1281-ubuntu2404

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PYTHONUNBUFFERED=1

# =============================================================================
# DEFAULT MODEL & OPTIMIZATION CONFIGURATION
# =============================================================================
# Model defaults (overridable via environment at pod/endpoint creation)
ENV MODEL_TYPE=VoiceDesign \
    MODEL_PATH="" \
    RUNPOD_VOLUME=/workspace

# Torch optimization flags (from twolven/Qwen3-TTS-Openai-Fastapi)
ENV TORCH_COMPILE=0 \
    ENABLE_TF32=1 \
    CUDNN_BENCHMARK=1

# =============================================================================
# SYSTEM DEPENDENCIES
# =============================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    sox \
    python3-venv \
    python3-dev \
    python3-pip \
    curl \
    libsndfile1 \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /workspace

# Copy entrypoint/handler files to /workspace
COPY handler.py /workspace/handler.py
COPY inference.py /workspace/inference.py
COPY config.py /workspace/config.py
COPY bootstrap.sh /workspace/bootstrap.sh
COPY serve.py /workspace/serve.py
COPY requirements.txt /workspace/requirements.txt

# Make bootstrap executable
RUN chmod +x /workspace/bootstrap.sh

# Pre-install dependencies to image's python environment
# These will also be installed to the venv during bootstrap for persistence
# --ignore-installed: base image ships a deb-managed cryptography 41.x with no
# RECORD file; pip cannot uninstall it when runpod pulls cryptography>=48.
# This keeps the deb copy but shadows it with the newer version on sys.path.
RUN pip install --no-cache-dir --ignore-installed -r /workspace/requirements.txt

# Set the bootstrap script as the command
CMD ["bash", "/workspace/bootstrap.sh"]
