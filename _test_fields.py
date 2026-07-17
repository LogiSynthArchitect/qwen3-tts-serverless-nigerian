import asyncio
from vastai import Serverless
from vastai.data import DeploymentConfig
import os

SEARCH = "gpu_name=RTX 4090,ram>=20,rentable=true,order=score/-dph_total"

async def try_cfg(label, **kw):
    cfg = DeploymentConfig(
        name="qwen3-tts-nigerian",
        image="vastai/pytorch:@vastai-automatic-tag",
        file_hash="0" * 64,
        file_size=100,
        tag="default",
        **kw,
    )
    c = Serverless(api_key=os.environ.get("VAST_API_KEY"))
    try:
        m = await c.put_deployment(cfg)
        print(f"OK  [{label}] id={m.id} action={m._put_response.action}")
    except Exception as e:
        print(f"ERR [{label}] {e}")

async def main():
    await try_cfg("+storage", storage=50)
    await try_cfg("+ttl", ttl=3600)
    await try_cfg("+search_params", search_params=SEARCH)
    await try_cfg("+cold0", cold_workers=0)
    await try_cfg("+max3", max_workers=3)
    await try_cfg("+inact300", inactivity_timeout=300)
    await try_cfg("+target", target_util=0.9)
    await try_cfg("ALL", storage=50, ttl=3600, search_params=SEARCH,
                  cold_workers=0, max_workers=3, inactivity_timeout=300, target_util=0.9)

asyncio.run(main())
