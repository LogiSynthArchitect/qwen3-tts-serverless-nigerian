from vastai.api.client import VastClient
from vastai.api import instances as inst
import os

c = VastClient(api_key=os.environ.get("VAST_API_KEY"))
# Check status of first test pod too
for iid in [45108660, 45108861]:
    try:
        row = inst.show_instance(c, iid)
        if row:
            print(f"Pod {iid}: actual={row.get('actual_status')} intent={row.get('intended_status')} "
                  f"image={row.get('image_uuid')} host={row.get('host_id')} "
                  f"machine={row.get('machine_id')} "
                  f"duration={row.get('duration',0):.0f}s "
                  f"error={row.get('error')}/{row.get('error_message')}")
        else:
            print(f"Pod {iid}: NOT FOUND")
    except Exception as e:
        print(f"Pod {iid}: ERR {str(e)[:150]}")
