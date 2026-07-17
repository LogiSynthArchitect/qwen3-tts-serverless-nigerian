from vastai.api.client import VastClient
from vastai.api import instances as inst
import os
c = VastClient(api_key=os.environ.get("VAST_API_KEY"))
try:
    r = inst.start_instance(c, 45108861)
    print("start result:", str(r)[:300])
except Exception as e:
    print("start error:", str(e)[:300])
