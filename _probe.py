from vastai.api.client import VastClient
import os
c = VastClient(api_key=os.environ.get("VAST_API_KEY"))
r = c.get('/api/v0/bundles/', query_args={'q': '{}'})
print("STATUS:", r.status_code)
print("BODY[:300]:", r.text[:300])
