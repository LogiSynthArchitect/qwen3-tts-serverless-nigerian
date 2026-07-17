"""
Quick test: create a pod on a new host, wait for it to run, then stop.
"""
from vastai.api.client import VastClient
from vastai.api import instances as inst
import os, time

ONSTART_SIMPLE = """set -e
mkdir -p /workspace/qwen3-tts
cd /workspace/qwen3-tts
curl -fsSL "https://raw.githubusercontent.com/LogiSynthArchitect/qwen3-tts-serverless-nigerian/main/.deploy_bundle.tar.gz" -o /tmp/bundle.tar.gz && tar -xzf /tmp/bundle.tar.gz -C /workspace/qwen3-tts
echo "POD_BOOT_COMPLETE" > /workspace/startup_ok.txt
python3 -c "import sys; sys.path.insert(0,'/workspace/qwen3-tts'); from inference import get_preset_voices; v=get_preset_voices(); print('VOICES_LOADED: %d' % len(v))" >> /workspace/startup_ok.txt
cat /workspace/startup_ok.txt
"""

c = VastClient(api_key=os.environ.get("VAST_API_KEY"))

# Cheapest 4090 on a different host
OFFER_ID = 43120382
HOST_ID = 34031
PRICE = 0.3090

print(f"Creating pod on host {HOST_ID} at ${PRICE}/hr...")
res = inst.create_instance(
    c, id=OFFER_ID,
    image="vastai/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04",
    disk=30,
    label="qwen3-boot-test",
    onstart_cmd=ONSTART_SIMPLE,
    price=PRICE,
)
print("CREATE:", str(res)[:200])
iid = res.get("new_contract") or res.get("id")
print("INSTANCE ID:", iid)

# Start it
inst.start_instance(c, iid)
print("Started. Waiting up to 5 min for boot...")
for attempt in range(20):
    time.sleep(15)
    row = inst.show_instance(c, iid)
    s = row.get("actual_status") if row else "?unknown?"
    print(f"  [{attempt*15+15}s] status={s} ip={row.get('public_ip','?')}", end="\r")
    if s == "running":
        print(f"\nRUNNING! public_ip={row.get('public_ip')} ports={row.get('ports')}")
        print("SUCCESS - host boots within time.")
        break
else:
    print(f"\nStill {s} after 5 min. Failing.")

# If running, stop and destroy
if s == "running":
    inst.stop_instance(c, iid)
    print("Stopped.")
    inst.destroy_instance(c, iid)
    print("Destroyed.")
