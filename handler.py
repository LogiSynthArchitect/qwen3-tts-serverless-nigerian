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
RunPod Serverless Handler for Qwen3-TTS

Supports three model types:
- Base: Voice cloning with reference audio + transcript
- CustomVoice: Pre-defined speakers with optional instruction control
- VoiceDesign: Natural language voice description for custom voice creation
"""

import runpod
import os
import logging
import base64
import io
import uuid
import subprocess
import time
import numpy as np
import soundfile as sf
from pathlib import Path

from inference import get_inference_engine, resolve_voice_params, get_available_voices
import config

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def cleanup_old_files(directory, days=2):
    """Delete files older than specified days from directory"""
    try:
        output_dir = Path(directory)
        if not output_dir.exists():
            return

        current_time = time.time()
        cutoff_time = current_time - (days * 24 * 60 * 60)

        deleted_count = 0
        for file_path in output_dir.glob('*'):
            if file_path.is_file():
                file_age = file_path.stat().st_mtime
                if file_age < cutoff_time:
                    file_path.unlink()
                    deleted_count += 1

        if deleted_count > 0:
            log.info(f"Cleaned up {deleted_count} files older than {days} days from {directory}")
    except Exception as e:
        log.error(f"Cleanup failed: {e}")


def upload_to_s3(audio_buffer, filename):
    """Upload generated audio to S3 and return URL"""
    if not config.S3_BUCKET_NAME:
        log.warning("S3_BUCKET_NAME not set, returning base64 audio")
        return None

    try:
        import boto3
        from botocore.config import Config
        
        s3 = boto3.client(
            's3',
            endpoint_url=config.S3_ENDPOINT_URL,
            aws_access_key_id=config.S3_ACCESS_KEY_ID,
            aws_secret_access_key=config.S3_SECRET_ACCESS_KEY,
            region_name=config.S3_REGION,
            config=Config(signature_version='s3v4')
        )

        s3.upload_fileobj(
            audio_buffer,
            config.S3_BUCKET_NAME,
            filename,
            ExtraArgs={'ContentType': 'audio/mpeg'}
        )

        # Generate presigned URL
        url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': config.S3_BUCKET_NAME, 'Key': filename},
            ExpiresIn=3600  # 1 hour
        )
        return url
    except Exception as e:
        log.error(f"S3 upload failed: {e}")
        return None


def encode_wav_to_mp3(wav_array: np.ndarray, sample_rate: int) -> bytes:
    """Encode WAV numpy array to MP3 bytes using ffmpeg"""
    # Convert to int16 if float
    if wav_array.dtype == np.float32 or wav_array.dtype == np.float64:
        audio_int16 = (wav_array * 32767).astype(np.int16)
    else:
        audio_int16 = wav_array.astype(np.int16)

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
        log.info(f"Encoded {len(wav_array)} samples to {len(mp3_bytes)} bytes MP3")
        return mp3_bytes
    except Exception as e:
        log.error(f"FFmpeg MP3 encoding failed: {e}")
        raise


def handler(job):
    """
    RunPod serverless handler

    Expected input format:
    {
        "text": str (required) - Text to synthesize
        "mode": str (optional) - Generation mode: "custom_voice", "voice_design", "voice_clone" (default: "custom_voice")
        "language": str (optional) - Language code (default: "Auto")
        "stream": bool (optional) - Enable streaming mode (default: false)
        "output_format": str (optional) - Output format: "mp3" or "pcm_16" (default: "mp3")

        // For custom_voice mode:
        "speaker": str (optional) - Speaker name (default: "Ryan")
        "instruct": str (optional) - Voice instruction

        // For voice_design mode:
        "instruct": str (required) - Natural language voice description

        // For voice_clone mode:
        "voice": str (optional) - Pre-configured voice name (looks up audio + transcript from voices.json)
        "ref_audio": str (optional) - Reference audio (path, URL, base64) - overrides voice if both provided
        "ref_text": str (optional) - Transcript of reference audio (overrides voice transcript if both provided)
        "x_vector_only_mode": bool (optional) - Use only speaker embedding (default: false)

        // Generation parameters:
        "max_new_tokens": int (optional) - Maximum tokens to generate (default: 2048)
        "do_sample": bool (optional) - Use sampling (default: true)
        "temperature": float (optional) - Sampling temperature (default: 0.9)
        "top_p": float (optional) - Top-p sampling (default: 1.0)
        "top_k": int (optional) - Top-k sampling (default: 50)
        "repetition_penalty": float (optional) - Repetition penalty (default: 1.05)
    }

    Batch mode Returns:
    {
        "status": "success",
        "sample_rate": int,
        "duration_sec": float,
        "audio_url": str (if S3 configured) OR "audio_base64": str (fallback)
    }

    Streaming mode Yields:
    {
        "status": "streaming",
        "chunk": int,
        "format": "mp3" or "pcm_16",
        "audio_chunk": str (base64 encoded),
        "sample_rate": int
    }
    {
        "status": "complete",
        "format": "mp3" or "pcm_16",
        "total_chunks": int,
        "elapsed_time_seconds": float
    }
    """
    job_input = job.get("input", {})

    # Extract streaming parameters first
    stream = job_input.get("stream", False)
    output_format = job_input.get("output_format", "mp3")

    # For streaming mode, use generator
    if stream:
        log.info(f"[Handler] Streaming mode requested: format={output_format}")
        yield from handler_stream(job_input, output_format)
        return

    # For batch mode, yield result (handler must be generator for RunPod compatibility)
    result = handler_batch(job)
    log.info(f"[Handler] Batch mode result: {result}")
    yield result


def _extract_and_validate_params(job_input: dict) -> tuple:
    """Extract and validate parameters from job input.

    Returns:
        tuple: (params_dict, error_dict) - error_dict is None if validation passes
    """
    # Extract required parameters
    text = job_input.get("text")
    if not text:
        return None, {"error": "Missing 'text' parameter"}

    mode = job_input.get("mode", "custom_voice")
    language = job_input.get("language", "Auto")
    session_id = job_input.get("session_id", str(uuid.uuid4()))

    # Mode-specific parameters
    speaker = job_input.get("speaker")
    instruct = job_input.get("instruct")
    voice = job_input.get("voice")  # For pre-configured voices
    ref_audio = job_input.get("ref_audio")
    ref_text = job_input.get("ref_text")
    x_vector_only_mode = job_input.get("x_vector_only_mode", False)

    # Resolve voice name to audio path and transcript for voice_clone mode
    if mode == "voice_clone" and voice and not ref_audio:
        resolved = resolve_voice_params(voice)
        if resolved:
            ref_audio, ref_text = resolved
            log.info(f"Resolved voice '{voice}' to audio: {ref_audio}, transcript: {len(ref_text)} chars")
        else:
            available = list(get_available_voices().keys())
            return None, {
                "error": f"Voice '{voice}' not found in voices.json. Available: {available}"
            }

    # Generation parameters
    max_new_tokens = job_input.get("max_new_tokens")
    do_sample = job_input.get("do_sample")
    temperature = job_input.get("temperature")
    top_p = job_input.get("top_p")
    top_k = job_input.get("top_k")
    repetition_penalty = job_input.get("repetition_penalty")

    # Validate mode
    if mode not in ["custom_voice", "voice_design", "voice_clone"]:
        return None, {"error": f"Invalid mode: {mode}. Must be one of: custom_voice, voice_design, voice_clone"}

    # Validate text length
    if len(text) > config.MAX_TEXT_LENGTH:
        return None, {"error": f"Text length exceeds maximum of {config.MAX_TEXT_LENGTH}"}

    # Validate mode-specific requirements
    if mode == "voice_design" and not instruct:
        return None, {"error": "instruct parameter is required for voice_design mode"}

    if mode == "voice_clone" and not ref_audio and not ref_text:
        if not voice:
            return None, {
                "error": "voice_clone mode requires either 'voice' (pre-configured) or 'ref_audio' and 'ref_text'"
            }

    params = {
        "text": text,
        "mode": mode,
        "language": language,
        "session_id": session_id,
        "speaker": speaker,
        "instruct": instruct,
        "voice": voice,
        "ref_audio": ref_audio,
        "ref_text": ref_text,
        "x_vector_only_mode": x_vector_only_mode,
        "max_new_tokens": max_new_tokens,
        "do_sample": do_sample,
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "repetition_penalty": repetition_penalty,
    }

    return params, None


def handler_batch(job):
    """Batch mode handler - generates complete audio and returns URL/base64"""
    # Clean up old output files
    cleanup_old_files(config.OUTPUT_DIR, days=2)

    job_input = job.get("input", {})

    # Extract and validate parameters
    params, error = _extract_and_validate_params(job_input)
    if error:
        return error

    text = params["text"]
    mode = params["mode"]
    language = params["language"]
    speaker = params["speaker"]
    instruct = params["instruct"]

    try:
        # Get inference engine
        inference_engine = get_inference_engine()

        # Route based on mode
        if mode == "custom_voice":
            wavs, sr = inference_engine.generate_custom_voice(
                text=text,
                language=language,
                speaker=speaker or "Ryan",
                instruct=instruct,
                max_new_tokens=params["max_new_tokens"],
                do_sample=params["do_sample"],
                temperature=params["temperature"],
                top_p=params["top_p"],
                top_k=params["top_k"],
                repetition_penalty=params["repetition_penalty"],
            )
        elif mode == "voice_design":
            wavs, sr = inference_engine.generate_voice_design(
                text=text,
                language=language,
                instruct=instruct,
                max_new_tokens=params["max_new_tokens"],
                do_sample=params["do_sample"],
                temperature=params["temperature"],
                top_p=params["top_p"],
                top_k=params["top_k"],
                repetition_penalty=params["repetition_penalty"],
            )
        elif mode == "voice_clone":
            wavs, sr = inference_engine.generate_voice_clone(
                text=text,
                ref_audio=params["ref_audio"],
                ref_text=params["ref_text"],
                language=language,
                x_vector_only_mode=params["x_vector_only_mode"],
                max_new_tokens=params["max_new_tokens"],
                do_sample=params["do_sample"],
                temperature=params["temperature"],
                top_p=params["top_p"],
                top_k=params["top_k"],
                repetition_penalty=params["repetition_penalty"],
            )
        else:
            return {"error": f"Unknown mode: {mode}"}

        # Combine all audio chunks (usually just one)
        if len(wavs) == 1:
            wav = wavs[0]
        else:
            # Concatenate if multiple chunks
            wav = np.concatenate(wavs, axis=0)

        # Encode to MP3
        log.info(f"Encoding audio to MP3 (samples: {len(wav)}, sample_rate: {sr})...")
        mp3_bytes = encode_wav_to_mp3(wav, sr)
        audio_buffer = io.BytesIO(mp3_bytes)

        # Save locally
        filename = f"{params['session_id']}_{uuid.uuid4()}.mp3"
        output_path = os.path.join(config.OUTPUT_DIR, filename)
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)

        log.info(f"Saving audio locally to {output_path}...")
        with open(output_path, "wb") as f:
            f.write(audio_buffer.getbuffer())

        # Reset buffer for S3 upload
        audio_buffer.seek(0)

        log.info("Uploading to S3 (if configured)...")
        s3_url = upload_to_s3(audio_buffer, filename)

        response = {
            "status": "success",
            "sample_rate": sr,
            "duration_sec": len(wav) / sr
        }

        if s3_url:
            response["audio_url"] = s3_url
        else:
            # Fallback to base64
            audio_buffer.seek(0)
            b64_audio = base64.b64encode(audio_buffer.read()).decode("utf-8")
            response["audio_base64"] = b64_audio

        log.info("Handler completed successfully.")
        return response

    except Exception as e:
        log.error(f"Inference failed: {e}")
        return {"error": str(e)}


def handler_stream(job_input: dict, output_format: str):
    """Streaming mode handler - yields audio chunks as they're generated"""
    # Extract and validate parameters
    params, error = _extract_and_validate_params(job_input)
    if error:
        yield error
        return

    try:
        # Get inference engine
        inference_engine = get_inference_engine()

        # Stream audio chunks
        yield from inference_engine.generate_audio_stream_decoded(
            text=params["text"],
            mode=params["mode"],
            language=params["language"],
            speaker=params["speaker"],
            instruct=params["instruct"],
            ref_audio=params["ref_audio"],
            ref_text=params["ref_text"],
            output_format=output_format,
            max_new_tokens=params["max_new_tokens"],
            do_sample=params["do_sample"],
            temperature=params["temperature"],
            top_p=params["top_p"],
            top_k=params["top_k"],
            repetition_penalty=params["repetition_penalty"],
        )

    except Exception as e:
        log.error(f"Streaming inference failed: {e}")
        yield {"error": str(e)}


if __name__ == "__main__":
    runpod.serverless.start({
        "handler": handler,
        "return_aggregate_stream": True  # True required for /runsync to capture generator yields
    })
