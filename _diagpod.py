from vastai.api.client import VastClient
from vastai.api import instances as inst
import os, json
c = VastClient(api_key=os.environ.get("VAST_API_KEY"))
row = inst.show_instance(c, 45108861)
for k in ['id','actual_status','intended_status','error','error_message','is_bid','price','gpu_name','machine_id','host_id','gpu_util']:
    print(f"{k}: {row.get(k)}")
print("---")
if row.get('intended_status') == 'stopped' and row.get('actual_status') != 'running':
    print("Pod is stopped. Need to start.")
