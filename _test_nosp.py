import asyncio
from vastai import Serverless
from vastai.data import DeploymentConfig
import os

async def main():
    cfg = DeploymentConfig(
        name="qwen3-tts-nigerian",
        image="vastai/pytorch:@vastai-automatic-tag",
        file_hash="0" * 64, file_size=100, tag="default",
        storage=50, ttl=3600, cold_workers=0, max_workers=3,
        inactivity_timeout=300, target_util=0.9,
    )
    c = Serverless(api_key=os.environ.get("VAST_API_KEY"))
    try:
        m = await c.put_deployment(cfg)
        print(f"OK no-search_params: id={m.id} action={m._put_response.action} needs_upload={m.needs_upload}")
    except Exception as e:
        print("ERR:", e)

asyncio.run(main())
