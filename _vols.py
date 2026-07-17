from vastai.api.client import VastClient
from vastai.api import offers as off
import os, json

c = VastClient(api_key=os.environ.get("VAST_API_KEY"))

# List network volumes belonging to user
try:
    r = c.get("/api/v0/volume/list/", query_args={"owner": "me"})
    data = r.json()
    vols = data.get("volumes", data.get("data", []))
    print("VOLUME COUNT:", len(vols))
    for v in vols[:5]:
        print(f"  id={v.get('id')} name={v.get('name')} size={v.get('size')}GB status={v.get('status')}")
except Exception as e:
    print("VOL ERR:", str(e)[:200])
