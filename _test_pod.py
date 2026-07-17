import asyncio, os
from vastai.api.client import VastClient
from vastai.api import instances as inst
from vastai.api import offers as off

async def main():
    client = VastClient(api_key=os.environ.get("VAST_API_KEY"))

    # Find cheapest RTX 4090 rentable offer
    offers = off.search_offers(client, query={"gpu_name": {"eq": "RTX 4090"}}, order=[["dph_total", "asc"]], limit=3)
    if not offers:
        print("NO OFFERS FOUND")
        return
    o = offers[0]
    print(f"Chosen offer id={o['id']} {o['gpu_name']} {o['gpu_ram']}GB ${o['dph_total']}/hr")

    # Create pod (interruptible/on-demand). Use our pytorch image + bundle pull onstart.
    try:
        res = inst.create_instance(
            client,
            id=o["id"],
            image="vastai/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04",
            disk=20,
            label="qwen3-tts-test",
            onstart_cmd="echo POD_STARTED_OK; sleep 30",
            price=o.get("dph_total"),
        )
        print("CREATE RESPONSE:", str(res)[:400])
        inst_id = res.get("new_contract") or res.get("id")
        print(f"INSTANCE ID: {inst_id}")
    except Exception as e:
        print("CREATE FAILED:", str(e)[:400])
        return

    # Stop it immediately to avoid billing
    try:
        inst.stop_instance(client, id=inst_id)
        print(f"STOPPED instance {inst_id} (no billing accrued beyond startup)")
    except Exception as e:
        print("STOP FAILED (manual stop needed):", str(e)[:200])

asyncio.run(main())
