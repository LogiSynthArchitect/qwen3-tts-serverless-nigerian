from vastai.api.client import VastClient
from vastai.api import offers as off
from vastai.api import storage as st
import os

c = VastClient(api_key=os.environ.get("VAST_API_KEY"))

# Find cheapest network volume offer
vols = off.search_network_volumes(c, query={}, order=[["dph_total", "asc"]], limit=3)
print("NVOL OFFERS:")
for v in vols[:3]:
    print(f"  id={v.get('id')} size={v.get('size')}GB ${v.get('dph_total')}/hr loc={v.get('geolocation')}")

if vols:
    try:
        vid = vols[0]["id"]
        res = st.create_network_volume(c, id=vid, size=15, name="qwen3-tts-bundle")
        print("CREATE VOL RESP:", str(res)[:300])
    except Exception as e:
        print("VOL CREATE FAILED:", str(e)[:300])
