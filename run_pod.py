"""
Launch a Vast.ai POD (not serverless) running Qwen3-TTS Nigerian VoiceDesign.

Model:
  - Bundle (tarball) already pushed to GitHub repo main branch.
  - Pod boots, onstart_cmd pulls the tarball, extracts to /workspace/qwen3-tts,
    installs deps, and runs serve.py (FastAPI REST: /tts, /voices, /health).
  - User does TTS work, then runs stop_pod.py to halt billing.

Run:  python3 run_pod.py      (reads VAST_API_KEY from env)
Cost: RTX 4090 ~$0.39/hr. Turn off between uses -> pennies per session.
"""
import os
import sys
from vastai.api.client import VastClient
from vastai.api import instances as inst
from vastai.api import offers as off

BUNDLE_URL = "https://raw.githubusercontent.com/LogiSynthArchitect/qwen3-tts-serverless-nigerian/main/.deploy_bundle.tar.gz"
APP_DIR = "/workspace/qwen3-tts"

ONSTART = f"""set -e
echo "[onstart] pulling bundle..."
mkdir -p {APP_DIR}
cd {APP_DIR}
curl -fsSL "{BUNDLE_URL}" -o /tmp/bundle.tar.gz
tar -xzf /tmp/bundle.tar.gz -C {APP_DIR}
echo "[onstart] installing deps (this can take a few min)..."
pip install --quiet qwen-tts transformers==4.57.3 accelerate==1.12.0 onnxruntime fastapi uvicorn librosa soundfile numpy 2>&1 | tail -5
echo "[onstart] starting server..."
cd {APP_DIR}
nohup python3 serve.py > /workspace/onstart.log 2>&1 &
echo "[onstart] server launching on :8000"
"""

def main():
    client = VastClient(api_key=os.environ.get("VAST_API_KEY"))

    # Cheapest rentable RTX 4090
    offers = off.search_offers(client, query={"gpu_name": {"eq": "RTX 4090"}}, order=[["dph_total", "asc"]], limit=3)
    if not offers:
        print("NO RTX 4090 OFFERS AVAILABLE")
        sys.exit(1)
    o = offers[0]
    print(f"Offer id={o['id']} {o['gpu_name']} {o['gpu_ram']}GB ${o['dph_total']}/hr")

    res = inst.create_instance(
        client,
        id=o["id"],
        image="vastai/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04",
        disk=40,
        label="qwen3-tts-pod",
        onstart_cmd=ONSTART,
        price=o.get("dph_total"),
    )
    print("CREATE:", str(res)[:300])
    inst_id = res.get("new_contract") or res.get("id")
    print(f"POD INSTANCE ID: {inst_id}")
    print(f"Poll status: vastai show instance {inst_id}")
    print("When done, run: python3 stop_pod.py " + str(inst_id))


if __name__ == "__main__":
    main()
