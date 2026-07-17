from vastai.api.client import VastClient
import os, sys, json
c = VastClient(api_key=os.environ.get("VAST_API_KEY"))
iid = int(sys.argv[1]) if len(sys.argv) > 1 else 45108861
row = None
try:
    r = c.get(f"/instances/{iid}/", query_args={"owner": "me"})
    row = r.json().get("instances")
except Exception as e:
    print("ERR", str(e)[:200])
print(json.dumps(row, indent=1, default=str)[:2000])
