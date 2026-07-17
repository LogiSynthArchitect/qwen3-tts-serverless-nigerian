from vastai.api.client import VastClient
from vastai.api import offers as off
import os

c = VastClient(api_key=os.environ.get("VAST_API_KEY"))
vols = off.search_volumes(c)
print("VOLUMES:", vols if isinstance(vols, list) else str(vols)[:400])
