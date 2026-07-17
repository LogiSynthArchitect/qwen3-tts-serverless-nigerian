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
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("vast-serve")

# Ensure /workspace is importable (handler.py lives there)
import sys
sys.path.insert(0, "/workspace")

import config  # path/registry config
import handler as rp_handler  # reuse existing logic
from inference import get_preset_voices, get_cloned_voices  # VoiceDesign + cloned catalogs

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


@app.get("/diag")
async def diag():
    """Diagnostic: check file paths, env, and registries (no model load)."""
    import sys

    info = {
        "cwd": os.getcwd(),
        "app_dir": config.APP_DIR,
        "voice_cloned_path": config.VOICE_CLONED_PATH,
        "voice_presets_path": config.VOICE_PRESETS_PATH,
        "config.__file__": config.__file__,
        "handler.__file__": rp_handler.__file__,
        "sys.path": sys.path,
    }
    for key in ("voice_cloned_path", "voice_presets_path"):
        p = Path(info[key])
        info[f"{key}_exists"] = p.exists()
        info[f"{key}_parent_exists"] = p.parent.exists()
        if p.parent.exists():
            info[f"{key}_parent_ls"] = [str(x.name) for x in p.parent.iterdir()]
    # Check the actual bridge/ contents
    for guess in ["bridge", "../bridge", f"{config.APP_DIR}/bridge", "/workspace/qwen3-tts/bridge"]:
        p = Path(guess).resolve()
        info[f"bridge_at_{guess}"] = str(p)
        info[f"bridge_at_{guess}_exists"] = p.exists()
        info[f"bridge_at_{guess}_isdir"] = p.is_dir()
        if p.is_dir():
            try:
                info[f"bridge_at_{guess}_ls"] = [str(x.name) for x in p.iterdir()]
            except Exception as e:
                info[f"bridge_at_{guess}_ls_err"] = str(e)
    # cloned voices from file (does NOT load the model)
    cloned = get_cloned_voices()
    info["cloned_voice_count"] = len(cloned)
    info["cloned_voice_ids"] = list(cloned.keys())
    # Env vars (non-sensitive keys only)
    safe_keys = ["MODEL_TYPE", "APP_DIR", "PORT", "RUNPOD_VOLUME", "HOME"]
    for k in safe_keys:
        info[k] = os.environ.get(k, "(not set)")
    info["PATH_truncated"] = os.environ.get("PATH", "")[:100]
    return info


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


@app.get("/clone-voices")
async def clone_voices():
    """List registered cloned brand voices (Base model only).
    Use an id as the `voice` field in POST /tts with mode=voice_clone."""
    voices = get_cloned_voices()
    catalog = [
        {
            "id": vid,
            "name": v.get("name"),
            "region": v.get("region"),
            "country": v.get("country"),
            "gender": v.get("gender"),
            "status": v.get("status", "registered"),
        }
        for vid, v in voices.items()
    ]
    return JSONResponse({"count": len(catalog), "voices": catalog})


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
