from vastai.api.client import VastClient
from vastai.api import instances as inst
import os, sys
c = VastClient(api_key=os.environ.get("VAST_API_KEY"))
iid = int(sys.argv[1]) if len(sys.argv) > 1 else 45108861
row = inst.show_instance(c, iid)
if not row:
    print("NOT FOUND")
else:
    print("id=%s status=%s actual_status=%s" % (row.get('id'), row.get('status'), row.get('actual_status')))
    print("ssh_host=%s ssh_port=%s public_ip=%s" % (row.get('ssh_host'), row.get('ssh_port'), row.get('public_ip')))
    print("ports=%s gpu=%s" % (row.get('ports'), row.get('gpu_name')))
