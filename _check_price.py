import asyncio, os
from vastai import Serverless

async def main():
    c = Serverless(api_key=os.environ.get("VAST_API_KEY"))
    offers = await c.search_offers(query="gpu_name=RTX 4090 rentable=true", order="dph_total")
    for o in offers[:5]:
        print(f"${o.get('dph_total'):.4f}/hr  {o.get('gpu_name')}  {o.get('gpu_ram')}GB  id={o.get('id')}")

asyncio.run(main())
