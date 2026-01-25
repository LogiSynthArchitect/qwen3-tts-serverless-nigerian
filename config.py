# coding=utf-8
# Copyright 2026 The Alibaba Qwen team.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

# Environment Variables
HF_TOKEN = os.environ.get("HF_TOKEN")

# S3 Configuration (optional, for audio output storage)
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")
S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID")
S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY")
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
S3_REGION = os.environ.get("S3_REGION", "us-east-1")

# RunPod volume structure
RUNPOD_VOLUME = "/runpod-volume"
QWEN3TTS_DIR = f"{RUNPOD_VOLUME}/Qwen3-TTS"
MODEL_CACHE_DIR = f"{QWEN3TTS_DIR}/models"
OUTPUT_DIR = f"{QWEN3TTS_DIR}/output"
AUDIO_PROMPTS_DIR = f"{QWEN3TTS_DIR}/audio_prompts"  # For voice cloning reference audio

# Model Configuration
DEFAULT_MODEL_TYPE = os.environ.get("MODEL_TYPE", "Base")  # Base, CustomVoice, VoiceDesign
DEFAULT_MODEL_PATH = os.environ.get(
    "MODEL_PATH",
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base"  # Will be overridden based on model_type
)
TOKENIZER_MODEL_PATH = os.environ.get("TOKENIZER_PATH", "Qwen/Qwen3-TTS-Tokenizer-12Hz")

# Application Configuration
MAX_TEXT_LENGTH = int(os.environ.get("MAX_TEXT_LENGTH", "5000"))
DEFAULT_SAMPLE_RATE = int(os.environ.get("DEFAULT_SAMPLE_RATE", "24000"))
MAX_CHUNK_CHARS = int(os.environ.get("MAX_CHUNK_CHARS", "500"))  # Qwen3-TTS can handle longer chunks

# Audio configuration
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm", ".aac", ".opus"}
MIN_AUDIO_DURATION = 3.0  # seconds (Qwen3-TTS recommends 3 seconds for voice cloning)
MAX_AUDIO_DURATION = 30.0  # seconds

# Voice configuration file path (maps voice names to audio files)
# Transcript files are expected to have same base name as audio with .txt extension
VOICES_CONFIG_PATH = os.environ.get("VOICES_CONFIG_PATH", f"{AUDIO_PROMPTS_DIR}/voices.json")

# Qwen3-TTS CustomVoice supported speakers (built-in, not from audio_prompts)
CUSTOM_VOICE_SPEAKERS = [
    "Vivian",      # Bright, slightly edgy young female (Chinese)
    "Serena",      # Warm, gentle young female (Chinese)
    "Uncle_Fu",    # Seasoned male, low/mellow timbre (Chinese)
    "Dylan",       # Youthful Beijing male, clear/natural (Chinese)
    "Eric",        # Lively Chengdu male, husky/bright (Chinese)
    "Ryan",        # Dynamic male, strong rhythmic drive (English)
    "Aiden",       # Sunny American male, clear midrange (English)
    "Ono_Anna",    # Playful Japanese female, light/nimble (Japanese)
    "Sohee",       # Warm Korean female, rich emotion (Korean)
]

# Supported languages
SUPPORTED_LANGUAGES = [
    "Auto",        # Auto-detect
    "Chinese",
    "English",
    "Japanese",
    "Korean",
    "German",
    "French",
    "Russian",
    "Portuguese",
    "Spanish",
    "Italian",
]

# Qwen3-TTS generation parameters
DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 0.80
DEFAULT_TOP_K = 20
DEFAULT_REPETITION_PENALTY = 1.05

# Streaming parameters
DEFAULT_SUBTALKER_DOSAMPLE = True
DEFAULT_SUBTALKER_TOP_K = 20
DEFAULT_SUBTALKER_TOP_P = 0.80
DEFAULT_SUBTALKER_TEMPERATURE = 1.0

# Default generation parameters
DEFAULT_MAX_NEW_TOKENS = 2048
DEFAULT_DO_SAMPLE = True

# Parameter validation ranges
MIN_TEMPERATURE = 0.05
MAX_TEMPERATURE = 2.0
MIN_TOP_P = 0.0
MAX_TOP_P = 1.0
MIN_TOP_K = 0
MAX_TOP_K = 1000
MIN_REPETITION_PENALTY = 1.0
MAX_REPETITION_PENALTY = 2.0

# Model type to model path mapping
MODEL_PATHS = {
    "Base": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    "0.6B-Base": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    "CustomVoice": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    "0.6B-CustomVoice": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
    "VoiceDesign": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
}

# OpenAI voice to Qwen3-TTS speaker mapping (for CustomVoice)
OPENAI_VOICE_TO_SPEAKER = {
    "alloy": "Ryan",      # Neutral male
    "echo": "Aiden",      # Male
    "fable": "Vivian",    # Female
    "onyx": "Uncle_Fu",   # Deep male
    "nova": "Serena",     # Female
    "shimmer": "Ono_Anna", # Female
}
