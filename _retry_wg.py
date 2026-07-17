import asyncio, os
from vastai import Serverless
from vastai.data import WorkergroupConfig

async def main():
    c = Serverless(api_key=os.environ.get("VAST_API_KEY"))
    wg = WorkergroupConfig(
        endpoint_id=30860,
        search_params="gpu_name=RTX 4090",
        cold_workers=0,
        max_workers=3,
        target_util=0.9,
    )
    try:
        wid = await c.create_workergroup(wg)
        print("WG OK:", wid)
    except Exception as e:
        print("FULL ERR:", repr(e))

asyncio.run(main())
