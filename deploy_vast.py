#!/usr/bin/env python3
"""
Vast.ai Serverless deployment for Qwen3-TTS (Nigerian VoiceDesign).

Strategy (user-approved option A): function-based @remote deployment.
Vast Serverless is NOT a generic HTTP-container platform -- the worker
imports a `deployment` module and serves its @remote functions. So we wrap
our existing TTS engine (handler.py) in deployment.py and register it.

What this script does (no registry, no PC Docker build):
  1. Builds a gzipped tarball containing:
       - deployment.py          (the @remote entrypoint)
       - the app code (handler.py, inference.py, config.py, diag.py, ...)
       - config.json            (envs/apt/pip/runs the worker consumes)
  2. Computes sha256 (file_hash) + size (file_size).
  3. Serverless.put_deployment(DeploymentConfig(...)) -> ManagedDeployment.
  4. await managed.upload(tarball) -> pushes to Vast cloud storage (S3).

Scaling: scale-to-zero (cold_workers=0, inactivity_timeout=300). GPU billed
only while handling requests; ~3-5 min cold start on first-after-idle.
ttl=3600 auto-tears-down the endpoint 1h after last use (zero billing).

Run:  python3 deploy_vast.py   (reads VAST_API_KEY from env)
"""
import asyncio
import hashlib
import io
import json
import os
import tarfile

from vastai import Serverless
from vastai.data import DeploymentConfig, WorkergroupConfig

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = "/workspace/qwen3-tts"  # destination of bundled files on worker

# App files/folders to bundle (besides deployment.py + config.json).
BUNDLE = [
    "handler.py",
    "inference.py",
    "config.py",
    "diag.py",
    "vast_start.sh",
    "requirements.txt",
    "bridge/voices_presets.json",
]

# NOTE: DeploymentConfig.search_params triggers an HTTP 500 on Vast's server
# (confirmed via SDK). GPU selection is done at the Workergroup level instead
# (see create_workergroup below). Left empty here.

# Worker config.json (consumed by Vast's serve_deployment.py).
CONFIG = {
    "name": "qwen3-tts-nigerian",
    "pip_installs": [
        "qwen-tts",
        "transformers==4.57.3",
        "accelerate==1.12.0",
        "onnxruntime",
        "fastapi",
        "uvicorn",
        "librosa",
        "soundfile",
        "numpy",
        "hf_transfer",
    ],
    "apt_gets": ["ffmpeg", "libsox-dev", "sox"],
    "envs": [
        ["MODEL_TYPE", "VoiceDesign"],
        ["PORT", "8000"],
        ["PYTHONUNBUFFERED", "1"],
        ["HF_HUB_ENABLE_HF_TRANSFER", "1"],
        ["APP_DIR", APP_DIR],
    ],
    # runs = setup scripts (sh -c). Keep empty; worker auto-imports deployment.py.
    # Optional: pre-download the model to shrink cold start:
    # "runs": ["python3 -c \"from inference import get_inference_engine; get_inference_engine()\""],
    "runs": [],
}


def build_tarball() -> tuple[bytes, str, int]:
    """Tar config.json + deployment.py + app code -> (bytes, sha256, size)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        # config.json at tarball root (worker reads ./config.json).
        cfg_bytes = json.dumps(CONFIG, indent=2).encode()
        info = tarfile.TarInfo(name="config.json")
        info.size = len(cfg_bytes)
        tf.addfile(info, io.BytesIO(cfg_bytes))

        # deployment.py at root (worker does `import deployment`).
        tf.add(os.path.join(HERE, "deployment.py"), arcname="deployment.py")

        # app code under APP_DIR.
        for rel in BUNDLE:
            src = os.path.join(HERE, rel)
            if not os.path.exists(src):
                print(f"[WARN] bundle path missing, skipping: {rel}")
                continue
            tf.add(src, arcname=os.path.join(APP_DIR, rel))
    data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest(), len(data)


async def main() -> None:
    data, file_hash, file_size = build_tarball()
    print(f"[*] Tarball built: {file_size} bytes, sha256={file_hash[:12]}...")

    tar_path = os.path.join(HERE, ".deploy_bundle.tar.gz")
    with open(tar_path, "wb") as f:
        f.write(data)

    config = DeploymentConfig(
        name="qwen3-tts-nigerian",
        image="vastai/pytorch:@vastai-automatic-tag",
        file_hash=file_hash,
        file_size=file_size,
        storage=50,             # GB; billed continuously while endpoint exists
        ttl=3600,               # auto-teardown 1h after last use -> zero billing
        cold_workers=0,         # scale to zero: no 24/7 reserved workers
        max_workers=3,
        inactivity_timeout=300,  # scale down 5 min after last request
        target_util=0.9,
        tag="default",
    )

    client = Serverless(api_key=os.environ.get("VAST_API_KEY"))

    print("[*] Registering deployment with Vast (PUT /api/v0/deployments/)...")
    managed = await client.put_deployment(config)
    print(f"[*] Deployment {managed.id} | endpoint {managed.endpoint_id} "
          f"| action={managed._put_response.action}")

    if managed.needs_upload:
        print("[*] Uploading tarball to Vast cloud storage (presigned S3)...")
        await managed.upload(tar_path)
        print("[*] Upload complete.")
    else:
        print("[*] No upload required (deployment already current).")

    # Create a workergroup pinned to RTX 4090 (GPU selection lives here, not
    # in DeploymentConfig which 500s on search_params). If the server rejects
    # search_params at this level too, we fall back to a default workergroup.
    try:
        wg = WorkergroupConfig(
            endpoint_id=managed.endpoint_id,
            search_params="gpu_name=RTX 4090",
            cold_workers=0,
            max_workers=3,
            target_util=0.9,
        )
        wg_id = await client.create_workergroup(wg)
        print(f"[*] Workergroup {wg_id} created (RTX 4090).")
    except Exception as e:
        print(f"[!] Workergroup creation failed (non-fatal): {e}")
        print("[!] Endpoint may need a workergroup via the Vast dashboard.")

    print("[*] Done. Workers initialize in ~3-5 min on first request.")
    print(f"[*] Endpoint id: {managed.endpoint_id}")
    print("[*] Call: POST /remote/tts  body={'kwargs': {...}}")
    print("[*] Voices: POST /remote/voices body={'kwargs': {}}")


if __name__ == "__main__":
    asyncio.run(main())
