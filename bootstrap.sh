#!/bin/bash
set -e

echo "=== Qwen3-TTS RunPod Serverless Bootstrap ==="

# Create Qwen3-TTS directory structure on network volume
echo "Creating directory structure on network volume..."
mkdir -p /runpod-volume/Qwen3-TTS/{hf_home,hf_cache,models,output,audio_prompts}

# Set environment variables for HuggingFace cache
export HF_HOME="/runpod-volume/Qwen3-TTS/hf_home"
export HF_HUB_CACHE="/runpod-volume/Qwen3-TTS/hf_cache"

# Virtual Environment Path on Network Volume
VENV_PATH="/runpod-volume/Qwen3-TTS/venv"

# Check if this is the first run
FIRST_RUN_FLAG="/runpod-volume/Qwen3-TTS/.first_run_complete"

if [ ! -f "$FIRST_RUN_FLAG" ]; then
    echo "=== First Run Detected - Setting up Environment ==="

    # Create Virtual Environment
    echo "Creating virtual environment at $VENV_PATH..."
    python3 -m venv "$VENV_PATH"

    # Activate Virtual Environment
    source "$VENV_PATH/bin/activate"

    # Install PyTorch with CUDA support
    echo "Installing PyTorch..."
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121

    # Copy Qwen3-TTS source files to network volume
    echo "Copying Qwen3-TTS source to network volume..."
    mkdir -p /runpod-volume/Qwen3-TTS/src
    cp -r /opt/docker/Qwen3-TTS/* /runpod-volume/Qwen3-TTS/src/ 2>/dev/null || true

    # Install qwen-tts package
    echo "Installing qwen-tts package..."
    cd /runpod-volume/Qwen3-TTS/src
    pip install -e .

    # Install additional dependencies
    echo "Installing additional dependencies..."
    pip install runpod>=1.6.0 boto3>=1.26.0 librosa soundfile

    # Install ffmpeg for audio encoding
    apt-get update && apt-get install -y ffmpeg

    # Create first run flag
    touch "$FIRST_RUN_FLAG"
    echo "=== First Run Setup Complete ==="

else
    echo "=== Existing Installation Found - Skipping Setup ==="
    # Activate Virtual Environment
    source "$VENV_PATH/bin/activate"
fi

# Start the handler
echo "Starting Qwen3-TTS handler..."
exec python /workspace/handler.py
