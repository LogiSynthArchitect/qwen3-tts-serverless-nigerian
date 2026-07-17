#!/usr/bin/env python3
"""
Vast.ai Serverless entrypoint for Qwen3-TTS (Nigerian VoiceDesign).

Vast Serverless is function-based: the worker does `import deployment`,
looks up a Deployment by name, and serves its @remote functions as HTTP
routes (/remote/<func_name>). This module registers those functions and
reuses the existing TTS engine in handler.py -- no RunPod runtime, no
separate HTTP server. The 24-voice catalog is preserved.

Handler contract (per vastai.serverless.remote source):
  - @remote async fn receives **kwargs from the JSON request body.
  - It must return a JSON-serializable object.
  - The worker wraps results as {"ok": ...} / {"err": ...}.

Client call (from the SDK or any HTTP client):
  POST /remote/tts   body = {"kwargs": {"text": "...", "mode": "voice_design", ...}}
  POST /remote/voices body = {"kwargs": {}}

Note: Vast's worker serializes/deserializes args via its own (de)serialize,
so the function should accept plain JSON-friendly kwargs and return a
plain dict/list. We keep the return shape identical to the old /tts response
(status, audio_base64/audio_url, sample_rate, duration_sec) so clients
adapt trivially.
"""
import logging
import os

from vastai.serverless.remote.serve import Deployment

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("qwen3-tts-deployment")

# Ensure our app modules are importable when the worker runs this file.
import sys

APP_DIR = os.environ.get("APP_DIR", "/workspace/qwen3-tts")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import handler as rp_handler  # reuses handler_batch / get_inference_engine
from inference import get_preset_voices  # 24-voice catalog

# The deployment the worker will look up by name.
app = Deployment(name="qwen3-tts-nigerian", tag="default")


@app.remote
async def tts(
    text: str,
    mode: str = "voice_design",
    voice: str = None,
    instruct: str = None,
    voice_instruct: str = None,
    speaker: str = None,
    language: str = "Auto",
    output_format: str = "mp3",
    stream: bool = False,
    # generation params (optional, forwarded as-is)
    speed: float = None,
    top_p: float = None,
    temperature: float = None,
    repetition_penalty: float = None,
    max_tokens: int = None,
):
    """Generate speech. Mirrors the old POST /tts input schema."""
    job_input = {
        "text": text,
        "mode": mode,
        "voice": voice,
        "instruct": instruct,
        "voice_instruct": voice_instruct,
        "speaker": speaker,
        "language": language,
        "output_format": output_format,
        "stream": stream,
    }
    # Forward any optional generation knobs that were provided.
    for k, v in (
        ("speed", speed),
        ("top_p", top_p),
        ("temperature", temperature),
        ("repetition_penalty", repetition_penalty),
        ("max_tokens", max_tokens),
    ):
        if v is not None:
            job_input[k] = v

    # handler_batch returns the result dict directly (no generator).
    result = rp_handler.handler_batch({"input": job_input})
    return result


@app.remote
async def voices():
    """Return the curated VoiceDesign preset catalog (id -> metadata)."""
    presets = get_preset_voices()
    catalog = [
        {
            "id": pid,
            "name": p.get("name"),
            "region": p.get("region"),
            "gender": p.get("gender"),
            "age": p.get("age"),
            "language": p.get("language"),
            "accent": p.get("accent"),
            "emotion": p.get("emotion"),
        }
        for pid, p in presets.items()
    ]
    return {"count": len(catalog), "voices": catalog}


@app.remote
async def health():
    """Lightweight liveness probe."""
    return {"status": "ok"}
