FROM runpod/base:1.0.3-cuda1281-ubuntu2404

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies
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
COPY requirements.txt /workspace/requirements.txt

# Make bootstrap executable
RUN chmod +x /workspace/bootstrap.sh

# Pre-install dependencies to image's python environment
# These will also be installed to the venv during bootstrap for persistence
RUN pip install --no-cache-dir -r /workspace/requirements.txt

# Set the bootstrap script as the command
CMD ["bash", "/workspace/bootstrap.sh"]
