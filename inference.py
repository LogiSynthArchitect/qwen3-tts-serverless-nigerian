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

"""
Qwen3-TTS Inference Engine for RunPod Serverless

Supports three model types:
- Base: Voice cloning with reference audio + transcript
- CustomVoice: Pre-defined speakers with optional instruction control
- VoiceDesign: Natural language voice description for custom voice creation
"""

import sys
import os
import random
import torch
import numpy as np
import logging
import soundfile as sf
import tempfile
import base64
import time
import subprocess
import io
import uuid
from pathlib import Path
from typing import Generator, Dict, Any, Tuple, Optional, Union, List
from urllib.parse import urlparse
from urllib import request as urllib_request

import config

log = logging.getLogger(__name__)


# Add qwen_tts to path from the reference project
sys.path.insert(0, '/opt/docker/Qwen3-TTS')


def load_audio(
    audio_input: Union[str, np.ndarray, Tuple[np.ndarray, int]],
    sample_rate: int = 24000
) -> Tuple[np.ndarray, int]:
    """
    Load audio from various input formats.

    Args:
        audio_input: Audio as path (str), URL (str), base64 (str), numpy array, or (array, sr) tuple
        sample_rate: Target sample rate for resampling (default: 24000)

    Returns:
        Tuple of (audio_array, sample_rate)
    """
    # If already a tuple with sample rate
    if isinstance(audio_input, tuple):
        audio, sr = audio_input
        if sr != sample_rate:
            import librosa
            audio = librosa.resample(audio, orig_sr=sr, target_sr=sample_rate)
        return audio, sample_rate

    # If numpy array, assume correct sample rate
    if isinstance(audio_input, np.ndarray):
        return audio_input, sample_rate

    # String input - could be path, URL, or base64
    if isinstance(audio_input, str):
        # Check if base64
        if audio_input.startswith('data:audio/') or ';' in audio_input:
            # Handle base64 data URL
            if ',' in audio_input:
                header, b64_data = audio_input.split(',', 1)
            else:
                b64_data = audio_input
            audio_bytes = base64.b64decode(b64_data)
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            try:
                audio, sr = sf.read(tmp_path)
                if sr != sample_rate:
                    import librosa
                    audio = librosa.resample(audio, orig_sr=sr, target_sr=sample_rate)
                return audio, sample_rate
            finally:
                os.unlink(tmp_path)

        # Check if URL
        parsed = urlparse(audio_input)
        if parsed.scheme in ('http', 'https'):
            # Download to temp file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp_path = tmp.name
            try:
                urllib_request.urlretrieve(audio_input, tmp_path)
                audio, sr = sf.read(tmp_path)
                if sr != sample_rate:
                    import librosa
                    audio = librosa.resample(audio, orig_sr=sr, target_sr=sample_rate)
                return audio, sample_rate
            finally:
                os.unlink(tmp_path)

        # Otherwise, treat as file path
        audio, sr = sf.read(audio_input)
        if sr != sample_rate:
            import librosa
            audio = librosa.resample(audio, orig_sr=sr, target_sr=sample_rate)
        return audio, sample_rate

    raise ValueError(f"Unsupported audio input type: {type(audio_input)}")


# =============================================================================
# PRE-CONFIGURED VOICES MANAGEMENT
# =============================================================================

# Global cache for voices configuration
_voices_config_cache = None
_voices_config_mtime = None


def load_voices_config() -> Dict[str, Dict[str, Any]]:
    """
    Load voices configuration from JSON file.

    The configuration maps voice names to audio files with optional metadata.
    Transcript files are auto-loaded from .txt files with the same base name.

    Expected JSON format:
    {
      "voice_name": {
        "audio_file": "path/to/audio.wav",
        "description": "Voice description",
        "language": "English",
        "gender": "male",
        "transcript": "Optional transcript (overrides .txt file)"
      }
    }

    Returns:
        Dictionary mapping voice names to voice configuration
    """
    global _voices_config_cache, _voices_config_mtime

    config_path = Path(config.VOICES_CONFIG_PATH)

    # Check if config file exists
    if not config_path.exists():
        log.warning(f"Voices config file not found: {config_path}")
        return {}

    # Check if we need to reload (file modification time)
    try:
        mtime = config_path.stat().st_mtime
        if _voices_config_cache is not None and _voices_config_mtime == mtime:
            return _voices_config_cache
    except Exception as e:
        log.warning(f"Could not check file mtime: {e}")

    try:
        import json
        with open(config_path, 'r') as f:
            voices_config = json.load(f)

        # Validate and add transcript information
        for voice_name, voice_data in voices_config.items():
            audio_file = voice_data.get("audio_file")
            if not audio_file:
                log.warning(f"Voice '{voice_name}' missing audio_file, skipping")
                continue

            # Resolve path relative to audio_prompts directory if not absolute
            audio_path = Path(audio_file)
            if not audio_path.is_absolute():
                audio_path = Path(config.AUDIO_PROMPTS_DIR) / audio_file

            # Check if audio file exists
            if not audio_path.exists():
                log.warning(f"Audio file not found for voice '{voice_name}': {audio_path}")
                continue

            # Store resolved path
            voice_data["audio_path"] = str(audio_path)

            # Load transcript from .txt file if not explicitly provided
            if "transcript" not in voice_data:
                txt_path = audio_path.with_suffix('.txt')
                if txt_path.exists():
                    try:
                        with open(txt_path, 'r', encoding='utf-8') as f:
                            voice_data["transcript"] = f.read().strip()
                        log.debug(f"Loaded transcript for '{voice_name}' from {txt_path}")
                    except Exception as e:
                        log.warning(f"Could not read transcript file {txt_path}: {e}")
                else:
                    log.warning(f"No transcript found for voice '{voice_name}' (expected {txt_path})")

        # Cache the result
        _voices_config_cache = voices_config
        _voices_config_mtime = mtime

        log.info(f"Loaded {len(voices_config)} voices from {config_path}")
        return voices_config

    except json.JSONDecodeError as e:
        log.error(f"Failed to parse voices config JSON: {e}")
        return {}
    except Exception as e:
        log.error(f"Failed to load voices config: {e}")
        return {}


def get_available_voices() -> Dict[str, Dict[str, Any]]:
    """
    Get list of available pre-configured voices.

    Returns:
        Dictionary mapping voice names to voice metadata
    """
    return load_voices_config()


def get_voice_info(voice_name: str) -> Optional[Dict[str, Any]]:
    """
    Get information about a specific voice.

    Args:
        voice_name: Name of the voice

    Returns:
        Voice configuration dict or None if not found
    """
    voices = load_voices_config()
    return voices.get(voice_name)


def resolve_voice_params(voice_name: str) -> Optional[Tuple[str, str]]:
    """
    Resolve voice name to audio file path and transcript.

    Args:
        voice_name: Name of the pre-configured voice

    Returns:
        Tuple of (audio_path, transcript) or None if voice not found
    """
    voice_info = get_voice_info(voice_name)
    if not voice_info:
        return None

    audio_path = voice_info.get("audio_path")
    transcript = voice_info.get("transcript", "")

    if not audio_path:
        return None

    return audio_path, transcript


class Qwen3TTSInference:
    """
    Qwen3-TTS Inference Engine

    Supports three model types:
    - Base: Voice cloning (requires ref_audio + ref_text)
    - CustomVoice: Pre-defined speakers with optional instruction
    - VoiceDesign: Natural language voice control
    """

    def __init__(
        self,
        model_type: str = None,
        model_path: str = None,
        device: str = None,
        dtype: torch.dtype = None
    ):
        """
        Initialize Qwen3-TTS inference engine.

        Args:
            model_type: Model type - "Base", "CustomVoice", or "VoiceDesign"
            model_path: Custom model path (overrides default for model_type)
            device: Device to load model on (default: cuda if available)
            dtype: Data type for model (default: bfloat16)
        """
        self.model = None
        self.processor = None
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.dtype = dtype or torch.bfloat16

        # Set model type and path
        self.model_type = model_type or config.DEFAULT_MODEL_TYPE
        self.model_path = model_path or config.MODEL_PATHS.get(
            self.model_type,
            config.MODEL_PATHS["Base"]
        )

        # Validate model type
        if self.model_type not in config.MODEL_PATHS:
            raise ValueError(
                f"Invalid model_type: {self.model_type}. "
                f"Must be one of: {list(config.MODEL_PATHS.keys())}"
            )

        log.info(f"Qwen3TTSInference initialized: model_type={self.model_type}, model_path={self.model_path}")

    def load_model(self):
        """Load Qwen3-TTS model and processor"""
        if self.model is not None:
            return self.model, self.processor

        log.info(f"Loading Qwen3-TTS model: {self.model_path} on {self.device}...")

        # Apply torch performance optimizations
        if config.ENABLE_TF32:
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            log.info("TF32 matmul enabled")

        if config.CUDNN_BENCHMARK:
            torch.backends.cudnn.benchmark = True
            log.info("cuDNN benchmark mode enabled")

        try:
            from qwen_tts import Qwen3TTSModel

            # Check if flash_attn is available
            try:
                import flash_attn
                attn_implementation = "flash_attention_2"
                log.info("FlashAttention 2 is available")
            except ImportError:
                attn_implementation = None
                log.warning("FlashAttention 2 not available, using default attention")

            # Create model wrapper
            self.model = Qwen3TTSModel.from_pretrained(
                self.model_path,
                device_map=self.device,
                dtype=self.dtype,
                attn_implementation=attn_implementation,
            )
            self.processor = self.model.processor

            # Optionally compile model for faster inference
            if config.TORCH_COMPILE:
                try:
                    self.model = torch.compile(self.model, mode="reduce-overhead")
                    log.info("Model compiled with torch.compile (reduce-overhead mode)")
                except Exception as e:
                    log.warning(f"torch.compile failed (non-fatal): {e}")

            # Log model parameter count
            param_count = sum(p.numel() for p in self.model.parameters())
            log.info(f"Model loaded successfully: {param_count/1e9:.2f}B params (model_type: {self.model_type})")

            # Verify supported languages and speakers after load
            try:
                langs = self.model.get_supported_languages()
                log.info(f"Supported languages: {langs}")
                if self.model_type == "CustomVoice":
                    speakers = self.model.get_supported_speakers()
                    log.info(f"Supported speakers: {speakers}")
            except Exception:
                pass

            return self.model, self.processor

        except Exception as e:
            log.error(f"Failed to load model: {e}")
            raise

    def get_supported_languages(self) -> List[str]:
        """Get list of supported languages for current model"""
        if self.model is None:
            self.load_model()
        return self.model.get_supported_languages()

    def get_supported_speakers(self) -> List[str]:
        """Get list of supported speakers for CustomVoice model"""
        if self.model is None:
            self.load_model()
        return self.model.get_supported_speakers()

    def _validate_parameters(
        self,
        text: str,
        language: str = None,
        speaker: str = None,
        model_type: str = None
    ):
        """Validate input parameters"""

        # Validate text
        if not text or not text.strip():
            raise ValueError("text parameter is required and cannot be empty")

        if len(text) > config.MAX_TEXT_LENGTH:
            raise ValueError(
                f"Text length exceeds maximum of {config.MAX_TEXT_LENGTH} characters"
            )

        # Validate language
        if language:
            supported_langs = self.get_supported_languages()
            # Normalize to lowercase for comparison, as the model returns lowercase
            lang_lower = language.lower()
            supported_lower = [l.lower() for l in supported_langs]
            
            if lang_lower not in supported_lower:
                raise ValueError(
                    f"Invalid language: {language}. "
                    f"Supported: {supported_langs}"
                )

        # Validate speaker for CustomVoice
        if model_type == "CustomVoice" or self.model_type == "CustomVoice":
            if speaker:
                supported_speakers = config.CUSTOM_VOICE_SPEAKERS
                if speaker not in supported_speakers:
                    raise ValueError(
                        f"Invalid speaker: {speaker}. "
                        f"Supported: {supported_speakers}"
                    )

    def _split_text(self, text: str, max_chars: int = None, min_chars: int = 50) -> List[str]:
        """
        Split text at natural speech boundaries for optimal TTS quality.
        
        Uses a hierarchical approach:
        1. First split by sentence boundaries (multi-language)
        2. If sentences too long, split by clause boundaries
        3. If still too long, split by phrase boundaries
        4. Last resort: split at word boundaries
        
        Args:
            text: Text to split
            max_chars: Maximum characters per chunk (default: config.MAX_CHUNK_CHARS)
            min_chars: Minimum characters for a chunk to avoid tiny fragments (default: 50)
            
        Returns:
            List of text chunks optimized for TTS generation
        """
        max_chars = max_chars or config.MAX_CHUNK_CHARS
        
        # No splitting needed for short text
        if len(text) <= max_chars:
            return [text]

        import re
        
        # Multi-language sentence boundaries
        # English: . ! ?
        # Chinese/Japanese: 。！？
        # Also treat newlines as boundaries
        sentence_pattern = r'(?<=[.!?。！？\n])\s*'
        
        # Clause boundaries (semicolons, colons, dashes)
        # English: ; : — – -
        # Chinese/Japanese: ；：
        clause_pattern = r'(?<=[;:；：—–\-])\s*'
        
        # Phrase boundaries (commas and similar)
        # English: ,
        # Chinese: ，、
        phrase_pattern = r'(?<=[,，、])\s*'
        
        def split_by_pattern(txt: str, pattern: str) -> List[str]:
            """Split text by regex pattern, filtering empty results."""
            parts = re.split(pattern, txt)
            return [p.strip() for p in parts if p.strip()]
        
        def merge_chunks(parts: List[str], max_len: int, min_len: int) -> List[str]:
            """
            Merge text parts into chunks respecting max length.
            Recursively handles parts that exceed max length.
            """
            chunks = []
            current = ""
            
            for part in parts:
                if not part:
                    continue
                
                # Test if adding this part would exceed max length
                test_chunk = (current + " " + part).strip() if current else part
                
                if len(test_chunk) <= max_len:
                    current = test_chunk
                else:
                    # Save current chunk if it has content
                    if current:
                        chunks.append(current)
                    
                    # Handle part that exceeds max length on its own
                    if len(part) > max_len:
                        # Try clause boundaries first
                        sub_parts = split_by_pattern(part, clause_pattern)
                        if len(sub_parts) > 1:
                            sub_chunks = merge_chunks(sub_parts, max_len, min_len)
                            if sub_chunks:
                                chunks.extend(sub_chunks[:-1])
                                current = sub_chunks[-1]
                            else:
                                current = ""
                        else:
                            # Try phrase boundaries
                            sub_parts = split_by_pattern(part, phrase_pattern)
                            if len(sub_parts) > 1:
                                sub_chunks = merge_chunks(sub_parts, max_len, min_len)
                                if sub_chunks:
                                    chunks.extend(sub_chunks[:-1])
                                    current = sub_chunks[-1]
                                else:
                                    current = ""
                            else:
                                # Last resort: split at word/character boundaries
                                # For CJK text, we can split between any characters
                                # For other text, split at word boundaries
                                cjk_pattern = re.compile(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]')
                                if cjk_pattern.search(part):
                                    # CJK text: split by characters
                                    current = ""
                                    for char in part:
                                        test = current + char
                                        if len(test) <= max_len:
                                            current = test
                                        else:
                                            if current:
                                                chunks.append(current)
                                            current = char
                                else:
                                    # Non-CJK: split at word boundaries
                                    words = part.split()
                                    current = ""
                                    for word in words:
                                        test = (current + " " + word).strip() if current else word
                                        if len(test) <= max_len:
                                            current = test
                                        else:
                                            if current:
                                                chunks.append(current)
                                            current = word
                    else:
                        current = part
            
            # Don't forget the last chunk
            if current:
                chunks.append(current)
            
            # Merge tiny trailing chunks with previous chunk
            # This avoids awkward short audio segments at the end
            if len(chunks) > 1 and len(chunks[-1]) < min_len:
                last = chunks.pop()
                # Allow 20% overflow for natural sentence endings
                if len(chunks[-1]) + len(last) + 1 <= max_len * 1.2:
                    chunks[-1] = chunks[-1] + " " + last
                else:
                    # Can't merge, put it back
                    chunks.append(last)
            
            return chunks
        
        # First split by sentence boundaries
        sentences = split_by_pattern(text, sentence_pattern)
        
        # Merge sentences into appropriately sized chunks
        chunks = merge_chunks(sentences, max_chars, min_chars)
        
        log.info(f"Split text of {len(text)} chars into {len(chunks)} chunks: {[len(c) for c in chunks]}")
        return chunks

    def generate_custom_voice(
        self,
        text: str,
        language: str = "Auto",
        speaker: str = "Ryan",
        instruct: str = None,
        max_new_tokens: int = None,
        do_sample: bool = None,
        temperature: float = None,
        top_p: float = None,
        top_k: int = None,
        repetition_penalty: float = None,
        streaming_mode: bool = False,
    ) -> Union[Tuple[List[np.ndarray], int], Generator[Tuple[np.ndarray, int], None, None]]:
        """
        Generate audio using CustomVoice model (pre-defined speakers).
        """
        if self.model is None:
            self.load_model()

        # Split text into chunks
        text_chunks = self._split_text(text)

        # Set defaults
        max_new_tokens = max_new_tokens or config.DEFAULT_MAX_NEW_TOKENS
        do_sample = do_sample if do_sample is not None else config.DEFAULT_DO_SAMPLE
        temperature = temperature if temperature is not None else config.DEFAULT_TEMPERATURE
        top_p = top_p if top_p is not None else config.DEFAULT_TOP_P
        top_k = top_k if top_k is not None else config.DEFAULT_TOP_K
        repetition_penalty = repetition_penalty if repetition_penalty is not None else config.DEFAULT_REPETITION_PENALTY

        # Normalize language
        lang_normalized = language.title() if language.lower() != "auto" else "Auto"

        # Build generation kwargs
        gen_kwargs = {
            "max_new_tokens": max_new_tokens,
            "do_sample": do_sample,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "repetition_penalty": repetition_penalty,
        }

        # Set random seed for reproducibility across all chunks
        seed = random.randint(0, 2**32 - 1)
        random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        log.info(f"Using random seed: {seed}")

        # For batch mode, collect all chunks
        all_wavs = []
        sample_rate = 24000 # Default

        for i, chunk in enumerate(text_chunks, 1):
            log.info(f"Generating chunk {i}/{len(text_chunks)}: {len(chunk)} chars")
            
            # Validate parameters for this chunk
            self._validate_parameters(chunk, language, speaker, "CustomVoice")
            
            try:
                wavs, sr = self.model.generate_custom_voice(
                    text=chunk,
                    language=lang_normalized,
                    speaker=speaker,
                    instruct=instruct or "",
                    **gen_kwargs
                )
                all_wavs.extend(wavs)
                sample_rate = sr
            except Exception as e:
                log.error(f"Chunk {i} generation failed: {e}")
                if not all_wavs: raise
                break # Return what we have so far

        log.info(f"Generated {len(all_wavs)} audio chunks total, sample_rate={sample_rate}")
        return all_wavs, sample_rate

    def generate_voice_design(
        self,
        text: str,
        language: str = "Auto",
        instruct: str = None,
        voice_instruct: str = None,
        max_new_tokens: int = None,
        do_sample: bool = None,
        temperature: float = None,
        top_p: float = None,
        top_k: int = None,
        repetition_penalty: float = None,
        streaming_mode: bool = False,
    ) -> Union[Tuple[List[np.ndarray], int], Generator[Tuple[np.ndarray, int], None, None]]:
        """
        Generate audio using VoiceDesign model (natural language voice control).

        Args:
            text: Text to synthesize
            language: Language code (default: "Auto" for auto-detection)
            instruct: Natural language voice description + emotion/style control.
                      For VoiceDesign, this describes BOTH the voice characteristics
                      (accent, gender, age, timbre) AND the speaking style/emotion.
                      Example: "Nigerian male, deep warm voice, speak cheerfully"
            voice_instruct: Alias for instruct (DashScope API compatibility).
                            If both instruct and voice_instruct are provided, they
                            are combined. Use this for DashScope-style API calls
                            where voice_instruct describes the voice and instruct
                            describes emotion for this utterance.
            ...generation parameters

        Returns:
            (wavs, sample_rate) tuple
        """
        if self.model is None:
            self.load_model()

        # Merge voice_instruct alias with instruct (DashScope API compatibility)
        if voice_instruct is not None:
            if instruct is not None:
                # Both provided: combine for comprehensive voice design
                instruct = f"{voice_instruct}. {instruct}"
            else:
                instruct = voice_instruct

        # Validate parameters
        if not instruct:
            raise ValueError("instruct (or voice_instruct) parameter is required for VoiceDesign model")

        # Split text into chunks
        text_chunks = self._split_text(text)

        # Set defaults
        max_new_tokens = max_new_tokens or config.DEFAULT_MAX_NEW_TOKENS
        do_sample = do_sample if do_sample is not None else config.DEFAULT_DO_SAMPLE
        temperature = temperature if temperature is not None else config.DEFAULT_TEMPERATURE
        top_p = top_p if top_p is not None else config.DEFAULT_TOP_P
        top_k = top_k if top_k is not None else config.DEFAULT_TOP_K
        repetition_penalty = repetition_penalty if repetition_penalty is not None else config.DEFAULT_REPETITION_PENALTY

        # Normalize language
        lang_normalized = language.title() if language.lower() != "auto" else "Auto"

        # Build generation kwargs
        gen_kwargs = {
            "max_new_tokens": max_new_tokens,
            "do_sample": do_sample,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "repetition_penalty": repetition_penalty,
        }

        # Set random seed for reproducibility across all chunks
        seed = random.randint(0, 2**32 - 1)
        random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        log.info(f"Using random seed: {seed}")

        all_wavs = []
        sample_rate = 24000

        for i, chunk in enumerate(text_chunks, 1):
            log.info(f"Generating chunk {i}/{len(text_chunks)}: {len(chunk)} chars")
            self._validate_parameters(chunk, language, None, "VoiceDesign")
            
            try:
                wavs, sr = self.model.generate_voice_design(
                    text=chunk,
                    language=lang_normalized,
                    instruct=instruct,
                    **gen_kwargs
                )
                all_wavs.extend(wavs)
                sample_rate = sr
            except Exception as e:
                log.error(f"Chunk {i} generation failed: {e}")
                if not all_wavs: raise
                break

        log.info(f"Generated {len(all_wavs)} audio chunks total, sample_rate={sample_rate}")
        return all_wavs, sample_rate

    def create_voice_clone_prompt(
        self,
        ref_audio: Union[str, np.ndarray, Tuple[np.ndarray, int]],
        ref_text: str,
        x_vector_only_mode: bool = False,
    ):
        """
        Create a reusable voice clone prompt for batch processing.

        Args:
            ref_audio: Reference audio (path, URL, base64, or numpy array)
            ref_text: Transcript of reference audio (required for Qwen3-TTS)
            x_vector_only_mode: Use only speaker embedding (faster but lower quality)

        Returns:
            VoiceClonePromptItem for use with generate_voice_clone()
        """
        if self.model is None:
            self.load_model()

        log.info(f"Creating voice clone prompt: ref_text_len={len(ref_text)}, x_vector_only={x_vector_only_mode}")

        try:
            prompt_items = self.model.create_voice_clone_prompt(
                ref_audio=ref_audio,
                ref_text=ref_text,
                x_vector_only_mode=x_vector_only_mode,
            )

            log.info("Voice clone prompt created successfully")
            return prompt_items

        except Exception as e:
            log.error(f"Failed to create voice clone prompt: {e}")
            raise

    def generate_voice_clone(
        self,
        text: str,
        ref_audio: Union[str, np.ndarray, Tuple[np.ndarray, int], List] = None,
        ref_text: str = None,
        language: str = "Auto",
        voice_clone_prompt = None,
        x_vector_only_mode: bool = False,
        max_new_tokens: int = None,
        do_sample: bool = None,
        temperature: float = None,
        top_p: float = None,
        top_k: int = None,
        repetition_penalty: float = None,
        streaming_mode: bool = False,
    ) -> Union[Tuple[List[np.ndarray], int], Generator[Tuple[np.ndarray, int], None, None]]:
        """
        Generate audio using Base model (voice cloning).

        Args:
            text: Text to synthesize
            ref_audio: Reference audio (path, URL, base64, numpy array, or list for batch)
            ref_text: Transcript of reference audio (required for Qwen3-TTS)
            language: Language code (default: "Auto" for auto-detection)
            voice_clone_prompt: Pre-created prompt (from create_voice_clone_prompt)
            x_vector_only_mode: Use only speaker embedding
            max_new_tokens: Maximum tokens to generate
            do_sample: Whether to use sampling
            temperature: Sampling temperature
            top_p: Top-p sampling
            top_k: Top-k sampling
            repetition_penalty: Repetition penalty
            streaming_mode: Enable streaming generation

        Returns:
            (wavs, sample_rate) or generator yielding (wav_chunk, sample_rate)
        """
        if self.model is None:
            self.load_model()

        # Validate parameters
        self._validate_parameters(text, language, None, "Base")

        # Check that either ref_audio+ref_text or voice_clone_prompt is provided
        if voice_clone_prompt is None:
            if ref_audio is None:
                raise ValueError("Either ref_audio or voice_clone_prompt must be provided")
            if ref_text is None and not x_vector_only_mode:
                raise ValueError("ref_text is required for voice cloning (unless x_vector_only_mode=True)")

        # Set defaults
        max_new_tokens = max_new_tokens or config.DEFAULT_MAX_NEW_TOKENS
        do_sample = do_sample if do_sample is not None else config.DEFAULT_DO_SAMPLE
        temperature = temperature if temperature is not None else config.DEFAULT_TEMPERATURE
        top_p = top_p if top_p is not None else config.DEFAULT_TOP_P
        top_k = top_k if top_k is not None else config.DEFAULT_TOP_K
        repetition_penalty = repetition_penalty if repetition_penalty is not None else config.DEFAULT_REPETITION_PENALTY

        # Normalize language
        lang_normalized = language.title() if language != "Auto" else language

        log.info(
            f"Voice clone generation: language={lang_normalized}, "
            f"text_len={len(text)}, has_prompt={voice_clone_prompt is not None}, "
            f"streaming={streaming_mode}"
        )

        # Build generation kwargs
        gen_kwargs = {
            "max_new_tokens": max_new_tokens,
            "do_sample": do_sample,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "repetition_penalty": repetition_penalty,
        }

        # Add subtalker parameters for streaming
        if streaming_mode:
            gen_kwargs.update({
                "subtalker_dosample": config.DEFAULT_SUBTALKER_DOSAMPLE,
                "subtalker_top_k": config.DEFAULT_SUBTALKER_TOP_K,
                "subtalker_top_p": config.DEFAULT_SUBTALKER_TOP_P,
                "subtalker_temperature": config.DEFAULT_SUBTALKER_TEMPERATURE,
            })

        # Set random seed for reproducibility within this generation
        seed = random.randint(0, 2**32 - 1)
        random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        log.info(f"Using random seed: {seed}")

        try:
            wavs, sr = self.model.generate_voice_clone(
                text=text,
                language=lang_normalized,
                ref_audio=ref_audio,
                ref_text=ref_text,
                voice_clone_prompt=voice_clone_prompt,
                x_vector_only_mode=x_vector_only_mode,
                **gen_kwargs
            )

            log.info(f"Generated {len(wavs)} audio chunks, sample_rate={sr}")
            return wavs, sr

        except Exception as e:
            log.error(f"Voice clone generation failed: {e}")
            raise

    def encode_mp3(self, audio_array: np.ndarray, sample_rate: int) -> bytes:
        """Encode PCM numpy array to MP3 bytes using ffmpeg"""
        # Ensure int16
        if audio_array.dtype != np.int16:
            audio_int16 = (audio_array * 32767).astype(np.int16)
        else:
            audio_int16 = audio_array

        raw_bytes = audio_int16.tobytes()

        try:
            process = subprocess.Popen(
                ['ffmpeg', '-y', '-f', 's16le', '-ar', str(sample_rate),
                 '-ac', '1', '-i', 'pipe:0', '-f', 'mp3', '-b:a', '192k', 'pipe:1'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            mp3_bytes, _ = process.communicate(input=raw_bytes)
            return mp3_bytes
        except Exception as e:
            log.error(f"FFmpeg encoding failed: {e}")
            return b""

    # =============================================================================
    # STREAMING GENERATORS
    # =============================================================================

    def generate_audio_stream_decoded(
        self,
        text: str,
        mode: str = "custom_voice",  # custom_voice, voice_design, voice_clone
        language: str = "Auto",
        speaker: str = None,
        instruct: str = None,
        voice_instruct: str = None,
        ref_audio: Union[str, np.ndarray, Tuple[np.ndarray, int]] = None,
        ref_text: str = None,
        voice_clone_prompt = None,
        output_format: str = "mp3",
        max_new_tokens: int = None,
        do_sample: bool = None,
        temperature: float = None,
        top_p: float = None,
        top_k: int = None,
        repetition_penalty: float = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Generate streaming audio with MP3/PCM encoding.

        Yields dictionaries with streaming chunk data.

        Args:
            text: Text to synthesize
            mode: Generation mode - "custom_voice", "voice_design", or "voice_clone"
            language: Language code
            speaker: Speaker name (for custom_voice)
            instruct: Voice instruction (for voice_design)
            ref_audio: Reference audio (for voice_clone)
            ref_text: Reference transcript (for voice_clone)
            voice_clone_prompt: Pre-created clone prompt
            output_format: "mp3" or "pcm_16"
            ...generation parameters

        Yields:
            Dict with keys: status, chunk, format, audio_chunk, sample_rate
        """
        start_time = time.time()

        # Route to appropriate generation method
        try:
            if mode == "custom_voice":
                wavs, sr = self.generate_custom_voice(
                    text=text,
                    language=language,
                    speaker=speaker or "Ryan",
                    instruct=instruct,
                    max_new_tokens=max_new_tokens,
                    do_sample=do_sample,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    repetition_penalty=repetition_penalty,
                    streaming_mode=False,  # Generate complete audio first
                )
            elif mode == "voice_design":
                if not instruct and not voice_instruct:
                    raise ValueError("instruct or voice_instruct is required for voice_design mode")
                wavs, sr = self.generate_voice_design(
                    text=text,
                    language=language,
                    instruct=instruct,
                    voice_instruct=voice_instruct,
                    max_new_tokens=max_new_tokens,
                    do_sample=do_sample,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    repetition_penalty=repetition_penalty,
                    streaming_mode=False,
                )
            elif mode == "voice_clone":
                wavs, sr = self.generate_voice_clone(
                    text=text,
                    ref_audio=ref_audio,
                    ref_text=ref_text,
                    language=language,
                    voice_clone_prompt=voice_clone_prompt,
                    max_new_tokens=max_new_tokens,
                    do_sample=do_sample,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    repetition_penalty=repetition_penalty,
                    streaming_mode=False,
                )
            else:
                yield {
                    "status": "error",
                    "error": f"Unknown mode: {mode}"
                }
                return

        except Exception as e:
            log.error(f"Generation failed: {e}")
            yield {
                "status": "error",
                "error": str(e)
            }
            return

        # Process and yield chunks
        for chunk_num, wav in enumerate(wavs, 1):
            # Convert to base64 for transmission
            if output_format == "mp3":
                audio_bytes = self.encode_mp3(wav, sr)
                fmt = "mp3"
            else:  # pcm_16
                if wav.dtype != np.int16:
                    wav_int16 = (wav * 32767).astype(np.int16)
                else:
                    wav_int16 = wav
                audio_bytes = wav_int16.tobytes()
                fmt = "pcm_16"

            audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

            yield {
                'status': 'streaming',
                'chunk': chunk_num,
                'format': fmt,
                'audio_chunk': audio_b64,
                'sample_rate': sr
            }

        elapsed = time.time() - start_time
        log.info(f"[Streaming] Complete: {len(wavs)} chunks, {elapsed:.2f}s")

        # Small delay to ensure all chunks are delivered
        time.sleep(0.1)

        yield {
            'status': 'complete',
            'format': output_format,
            'total_chunks': len(wavs),
            'elapsed_time_seconds': elapsed
        }


# Singleton instance for RunPod serverless
_inference_engine = None


def get_inference_engine(
    model_type: str = None,
    model_path: str = None,
    device: str = None,
) -> Qwen3TTSInference:
    """Get or create singleton inference engine"""
    global _inference_engine

    if _inference_engine is None:
        _inference_engine = Qwen3TTSInference(
            model_type=model_type,
            model_path=model_path,
            device=device,
        )

    return _inference_engine
