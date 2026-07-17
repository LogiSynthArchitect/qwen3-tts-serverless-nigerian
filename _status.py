from vastai.api.client import VastClient
import os, sys
c = VastClient(api_key=os.environ.get("VAST_API_KEY"))
iid = sys.argv[1] if len(sys.argv) > 1 else "45108861"
r = c.get('/api/v0/instances/', query_args={'id': iid})
data = r.json()
insts = data.get('instances', data.get('data', []))
for it in insts:
    print("id=%s status=%s actual_status=%s ssh_host=%s ssh_port=%s gpu=%s" % (
        it.get('id'), it.get('status'), it.get('actual_status'),
        it.get('ssh_host'), it.get('ssh_port'), it.get('gpu_name')))
    print("  public_ip=", it.get('public_ip'), "ports=", it.get('ports'))
