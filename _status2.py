from vastai.api.client import VastClient
import os, sys, json
c = VastClient(api_key=os.environ.get("VAST_API_KEY"))
iid = sys.argv[1] if len(sys.argv) > 1 else "45108861"
r = c.get('/api/v0/instances/', query_args={'client_id': 'me', 'id': iid})
print("STATUS", r.status_code)
print(str(r.json())[:800])
