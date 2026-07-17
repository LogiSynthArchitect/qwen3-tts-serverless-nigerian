import asyncio
from vastai import Serverless
from vastai.data import DeploymentConfig
import os

async def main():
    cfg = DeploymentConfig(
        name="qwen3-tts-nigerian",
        image="vastai/pytorch:@vastai-automatic-tag",
        file_hash="0" * 64,
        file_size=100,
        tag="default",
    )
    c = Serverless(api_key=os.environ.get("VAST_API_KEY"))
    try:
        m = await c.put_deployment(cfg)
        print("OK minimal:", m.id, m._put_response.action, "needs_upload=", m.needs_upload)
    except Exception as e:
        print("ERR minimal:", e)

asyncio.run(main())
