from vastai.api.client import VastClient
import os

c = VastClient(api_key=os.environ.get("VAST_API_KEY"))
# Check host 366851 status for provisioning issues
r = c.get('/api/v0/machines/', query_args={'host_id': 366851})
print("HOST STATUS:", r.status_code)
print(str(r.text)[:500])
