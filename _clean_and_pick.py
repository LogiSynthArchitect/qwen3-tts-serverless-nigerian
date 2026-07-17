from vastai.api.client import VastClient
from vastai.api import instances as inst
from vastai.api import offers as off
import os

c = VastClient(api_key=os.environ.get("VAST_API_KEY"))

# Stop both stuck pods
for iid in [45108660, 45108861]:
    try:
        inst.stop_instance(c, iid)
        print(f"Stopped {iid}")
    except Exception as e:
        print(f"Stop {iid}: {str(e)[:100]}")

# Destroy (delete) them
for iid in [45108660, 45108861]:
    try:
        inst.destroy_instance(c, iid)
        print(f"Destroyed {iid}")
    except Exception as e:
        print(f"Destroy {iid}: {str(e)[:100]}")

# Find RTX 4090 offers on DIFFERENT hosts (not 366851)
offers = off.search_offers(c, query={"gpu_name": {"eq": "RTX 4090"}, "verified": {"eq": True}, "rentable": {"eq": True}},
                           order=[["dph_total", "asc"]], limit=10)
print(f"\nCheapest RTX 4090 offers (different hosts):")
seen_hosts = set()
for o in offers:
    h = o.get('host_id')
    if h not in seen_hosts:
        seen_hosts.add(h)
        print(f"  offer id={o['id']} host={h} ${o.get('dph_total','?'):.4f}/hr gpu_ram={o.get('gpu_ram')}GB")
        if len(seen_hosts) >= 5:
            break
