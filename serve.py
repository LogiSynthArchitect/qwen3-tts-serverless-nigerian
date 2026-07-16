#!/usr/bin/env python3
"""
Vast.ai HTTP server for Qwen3-TTS.

Wraps the existing RunPod-style handler (handler.py) behind a plain FastAPI
endpoint so the container can run on Vast.ai (which has no RunPod serverless
runtime). The handler module is imported as-is; we just adapt the
`{"input": {...}}` job contract to HTTP.

Endpoints:
  POST /tts
    Body (JSON): same schema as handler input
      {
        "text": "...",
        "mode": "voice_design" | "custom_voice" | "voice_clone",
        "voice": "<preset id from GET /voices>"  // voice_design only: selects a named preset
        "instruct": "Nigerian male, deep warm voice, speak cheerfully",
        "voice_instruct": "...", "speaker": "...", "language": "Auto",
        "output_format": "mp3" | "pcm_16", "stream": false,
        ...generation params
      }
    Response: the handler's batch result dict (status, audio_base64/audio_url,
              sample_rate, duration_sec) or {"error": "..."}.

  GET /voices
    Returns the curated VoiceDesign preset catalog (id, name, region, gender,
    age, language, accent, emotion). Use an id as the `voice` field in POST /tts.

  GET /health  -> {"status": "ok"}
"""
import json
import logging
import os
import traceback

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("vast-serve")

# Ensure /workspace is importable (handler.py lives there)
import sys
sys.path.insert(0, "/workspace")

import handler as rp_handler  # reuse existing logic
from inference import get_preset_voices  # VoiceDesign preset catalog

app = FastAPI(title="Qwen3-TTS Vast Serve", version="1.0")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/log")
async def log_endpoint():
    """Return the onstart + serve.py log for remote diagnosis (no SSH needed)."""
    try:
        with open("/workspace/onstart.log") as f:
            tail = f.read()[-8000:]
    except Exception as e:
        tail = f"(no log: {e})"
    return JSONResponse({"log": tail})


@app.get("/voices")
async def voices():
    """List the curated VoiceDesign preset catalog (African + global, by gender/age)."""
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
    return JSONResponse({"count": len(catalog), "voices": catalog})


@app.get("/ps")
async def ps():
    """Return running python processes for diagnosis."""
    import subprocess
    try:
        out = subprocess.run(
            ["ps", "-eo", "pid,etimes,cmd"], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception as e:
        out = str(e)
    return JSONResponse({"ps": out})


@app.post("/tts")
async def tts(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    # The handler expects job = {"input": {...}} and is a generator.
    job = {"input": data}
    try:
        result = None
        for chunk in rp_handler.handler(job):
            result = chunk
        if result is None:
            return JSONResponse({"error": "No result from handler"}, status_code=500)
        return JSONResponse(result)
    except Exception as e:  # surface errors clearly
        log.error("handler error: %s\n%s", e, traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    log.info("Starting Qwen3-TTS Vast HTTP server on :%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
