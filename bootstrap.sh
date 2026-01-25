#!/bin/bash
set -e

echo "=== Qwen3-TTS RunPod Serverless Bootstrap ==="

# Create Qwen3-TTS directory structure on network volume
echo "Creating directory structure on network volume..."
mkdir -p /runpod-volume/Qwen3-TTS/{models,output,audio_prompts}

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
    echo "Installing PyTorch 2.9.1 with CUDA 12.8 support..."
    pip install torch==2.9.1 torchvision==0.24.1 torchaudio==2.9.1 --index-url https://download.pytorch.org/whl/cu128

    # Install Flash Attention
    echo "Installing Flash Attention v2.8.3..."
    pip install https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.3/flash_attn-2.8.3+cu12torch2.9cxx11abiTRUE-cp312-cp312-linux_x86_64.whl

    # Clone Qwen3-TTS upstream repository
    echo "Cloning Qwen3-TTS upstream repository..."
    # We clone into 'src' directory on the volume
    rm -rf /runpod-volume/Qwen3-TTS/src
    git clone https://github.com/QwenLM/Qwen3-TTS.git /runpod-volume/Qwen3-TTS/src

    # Install qwen-tts package in editable mode
    echo "Installing qwen-tts package..."
    cd /runpod-volume/Qwen3-TTS/src
    pip install -e .

    # Install additional dependencies
    echo "Installing additional dependencies..."
    pip install runpod>=1.6.0 boto3>=1.26.0 librosa soundfile hf_transfer

    # Install ffmpeg and sox for audio processing
    apt-get update && apt-get install -y ffmpeg sox

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
