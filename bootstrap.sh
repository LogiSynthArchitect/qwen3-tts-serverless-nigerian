#!/bin/bash
set -e

echo "=== Qwen3-TTS RunPod Serverless Bootstrap ==="

# =============================================================================
# PATH CONFIGURATION
# =============================================================================
# Network volume mount point (Runpod default: /workspace)
VOLUME_BASE="${RUNPOD_VOLUME:-/workspace}"
QWEN3TTS_DIR="${VOLUME_BASE}/Qwen3-TTS"
MODEL_DIR="${QWEN3TTS_DIR}/models"
VENV_PATH="${QWEN3TTS_DIR}/venv"
FIRST_RUN_FLAG="${QWEN3TTS_DIR}/.first_run_complete"

echo "Volume base: ${VOLUME_BASE}"
echo "Qwen3-TTS dir: ${QWEN3TTS_DIR}"

# Create directory structure
mkdir -p "${QWEN3TTS_DIR}"/{models,output,audio_prompts}

# =============================================================================
# CHECK FOR PRE-EXISTING MODELS ON VOLUME
# =============================================================================
echo "=== Checking for pre-downloaded models ==="
if [ -d "${MODEL_DIR}/VoiceDesign" ] && [ -d "${MODEL_DIR}/CustomVoice" ] && [ -d "${MODEL_DIR}/Base" ] && [ -d "${MODEL_DIR}/Tokenizer" ]; then
    echo "All models found on volume at ${MODEL_DIR}"
    ls -lh "${MODEL_DIR}"/
    # Set MODEL_PATH so inference.py uses local volume path
    export MODEL_PATH="${MODEL_DIR}/VoiceDesign"
    echo "MODEL_PATH set to ${MODEL_PATH}"
else
    echo "Pre-downloaded models not found at ${MODEL_DIR}"
    echo "Models in volume:"
    ls -la "${MODEL_DIR}"/ 2>/dev/null || echo "  (empty or missing)"
    echo "Models will be auto-downloaded by HuggingFace at first inference."
fi

# =============================================================================
# VIRTUAL ENVIRONMENT SETUP (first run only)
# =============================================================================
if [ ! -f "${FIRST_RUN_FLAG}" ]; then
    echo "=== First Run Detected - Setting up Environment ==="

    # Create Virtual Environment
    echo "Creating virtual environment at ${VENV_PATH}..."
    python3 -m venv "${VENV_PATH}"

    # Activate Virtual Environment
    source "${VENV_PATH}/bin/activate"

    # Install PyTorch with CUDA 12.8 support
    echo "Installing PyTorch 2.9.1 with CUDA 12.8 support..."
    pip install torch==2.9.1 torchvision==0.24.1 torchaudio==2.9.1 --index-url https://download.pytorch.org/whl/cu128

    # Install Flash Attention 2
    echo "Installing Flash Attention v2.8.3..."
    pip install https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.3/flash_attn-2.8.3+cu12torch2.9cxx11abiTRUE-cp312-cp312-linux_x86_64.whl

    # Clone Qwen3-TTS upstream repository
    echo "Cloning Qwen3-TTS upstream repository..."
    rm -rf "${QWEN3TTS_DIR}/src"
    git clone https://github.com/QwenLM/Qwen3-TTS.git "${QWEN3TTS_DIR}/src"

    # Install qwen-tts package in editable mode
    echo "Installing qwen-tts package..."
    cd "${QWEN3TTS_DIR}/src"
    pip install -e .

    # Install additional dependencies
    echo "Installing additional dependencies..."
    pip install runpod>=1.6.0 boto3>=1.26.0 librosa soundfile hf_transfer

    # Install ffmpeg and sox for audio processing
    apt-get update && apt-get install -y ffmpeg sox

    # Create first run flag
    touch "${FIRST_RUN_FLAG}"
    echo "=== First Run Setup Complete ==="
else
    echo "=== Existing Installation Found - Skipping Setup ==="
    # Activate Virtual Environment
    source "${VENV_PATH}/bin/activate"
fi

# =============================================================================
# START HANDLER
# =============================================================================
echo "=== Starting Qwen3-TTS handler (model_type: ${MODEL_TYPE:-VoiceDesign}) ==="
echo "Optimization flags: TORCH_COMPILE=${TORCH_COMPILE:-0}, ENABLE_TF32=${ENABLE_TF32:-1}, CUDNN_BENCHMARK=${CUDNN_BENCHMARK:-1}"
exec python /workspace/handler.py
