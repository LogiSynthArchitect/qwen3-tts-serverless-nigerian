"""Stop a Vast.ai pod to halt billing. Usage: python3 stop_pod.py <instance_id>"""
import os
import sys
from vastai.api.client import VastClient
from vastai.api import instances as inst

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 stop_pod.py <instance_id>")
        sys.exit(1)
    inst_id = int(sys.argv[1])
    client = VastClient(api_key=os.environ.get("VAST_API_KEY"))
    inst.stop_instance(client, id=inst_id)
    print(f"Stopped pod {inst_id}. Billing halted.")

if __name__ == "__main__":
    main()
