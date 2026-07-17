from vastai.api.client import VastClient
import os
c = VastClient(api_key=os.environ.get("VAST_API_KEY"))
r = c.get('/api/v0/network_volumes/', query_args={})
print(r.status_code, str(r.json())[:500])
