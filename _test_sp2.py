import asyncio
from vastai import Serverless
from vastai.data import DeploymentConfig
import os

async def try_sp(label, sp):
    cfg = DeploymentConfig(
        name="qwen3-tts-nigerian",
        image="vastai/pytorch:@vastai-automatic-tag",
        file_hash="0" * 64, file_size=100, tag="default",
        search_params=sp,
    )
    c = Serverless(api_key=os.environ.get("VAST_API_KEY"))
    try:
        m = await c.put_deployment(cfg)
        print(f"OK  [{label}] id={m.id} action={m._put_response.action}")
    except Exception as e:
        print(f"ERR [{label}] {e}")

async def main():
    await try_sp("space-syntax", "gpu_name=RTX 4090 gpu_ram>=20 rentable=true")
    await try_sp("min-vals", "gpu_name=RTX 4090")

asyncio.run(main())
