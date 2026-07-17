import asyncio, os
from vastai import Serverless
from vastai.data import WorkergroupConfig

async def attempt(label, **kw):
    c = Serverless(api_key=os.environ.get("VAST_API_KEY"))
    wg = WorkergroupConfig(endpoint_id=30860, **kw)
    try:
        wid = await c.create_workergroup(wg)
        print(f"OK  [{label}] wg_id={wid}")
    except Exception as e:
        msg = str(e)
        print(f"ERR [{label}] {msg[msg.find('HTTP'):msg.find('HTTP')+120] if 'HTTP' in msg else msg[:160]}")

async def main():
    # scale-to-zero single worker, no explicit GPU pin
    await attempt("min-no-pin", cold_workers=0, max_workers=1, target_util=0.9)
    # with gpu pin
    await attempt("min-pin4090", search_params="gpu_name=RTX 4090", cold_workers=0, max_workers=1, target_util=0.9)

asyncio.run(main())
