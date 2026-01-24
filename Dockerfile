FROM runpod/base:cuda12.1.0-runtime-ubuntu22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    python3.10-venv \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /workspace

# Copy source files
COPY handler.py /workspace/handler.py
COPY inference.py /workspace/inference.py
COPY config.py /workspace/config.py
COPY bootstrap.sh /workspace/bootstrap.sh

# Copy Qwen3-TTS source (for reference, will be installed from PyPI)
# The actual qwen_tts package will be installed during bootstrap
RUN mkdir -p /opt/docker/Qwen3-TTS

# Make bootstrap executable
RUN chmod +x /workspace/bootstrap.sh

# Set the bootstrap script as the entrypoint
ENTRYPOINT ["/workspace/bootstrap.sh"]
