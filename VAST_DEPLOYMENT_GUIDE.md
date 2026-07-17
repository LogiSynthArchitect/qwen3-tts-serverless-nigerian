# Qwen3-TTS VoiceDesign — Vast.ai Deployment Guide

**Project:** Qwen3-TTS (Nigerian VoiceDesign, 24-voice catalog)
**Stack:** GitHub → Cloud Build → Docker Hub → Vast.ai `args` runtype
**Last updated:** 2026-07-17

---

## 1. Architecture (v4 — single failure point)

```
GitHub (main) ──push──▶ Google Cloud Build ──▶ Docker Hub (public)
                                                    │
                                                    ▼
                                            Vast.ai instance
                                       (runtype: args, no wrapper)
                                            │
                                            ▼
                                    FastAPI serve.py :8000
```

- **1 failure point** (Docker pull) vs old approach (4: pull + curl + extract + pip).
- Base image `vastai/pytorch:cuda-12.6.3-auto` (~9GB) is cached on most Vast hosts → only our ~3GB custom layers pull at boot.

---

## 2. Dockerfile — Critical Rules

```dockerfile
FROM vastai/pytorch:cuda-12.6.3-auto
ENTRYPOINT []          # MUST clear base image ENTRYPOINT, else CMD is swallowed as args
CMD ["python3", "serve.py"]   # base image has python3, NOT python
EXPOSE 8000
```

**Two hard-won fixes:**

| Bug | Symptom | Fix |
|-----|---------|-----|
| Missing `ENTRYPOINT []` | Vast wrapper runs; `python serve.py` passed as flags → "Unknown flag" → server never starts | Add `ENTRYPOINT []` after FROM |
| `python` not `python3` | `exec: "python": executable file not found in $PATH` | Use `CMD ["python3", "serve.py"]` |

**Validation steps in Dockerfile use `python3` — keep them consistent with CMD.**

---

## 3. Vast.ai Runtype System

| Runtype | Entrypoint behavior | SSH/Jupyter | Use when |
|---------|---------------------|-------------|----------|
| `args` | **Preserves** image ENTRYPOINT. `args_str` replaces CMD. | None | Headless server (our case) |
| `ssh_direct` | Replaced by Vast entrypoint | Port 22 | Need terminal |
| `jupyter_direct` | Replaced by Vast entrypoint | 8080 + 22 | Need notebooks |

**We use `args`** because we want the container to run `serve.py` exactly as built.
No `--ssh`/`--jupyter` flag → defaults to `args` mode.

---

## 4. Port Mapping

- Internal port 8000 is exposed via `EXPOSE 8000` in Dockerfile → auto-requested.
- Additional mapping via `--env '-p 8000:8000'` (Docker `-p` syntax).
- After instance loads, internal 8000 maps to a **random external port** on the shared public IP.
- Find it via: `VAST_TCP_PORT_8000` env var, or `ports` field in `vastai show instance`, or Vast console "IP Port Info" button.
- Format: `PUBLIC_IP:EXTERNAL_PORT -> 8000/tcp`

---

## 5. Host Selection — Check BEFORE Creating

Query offers and inspect these fields:

```bash
source /tmp/vastcli/bin/activate
vastai search offers 'reliability>0.98 num_gpus=1 gpu_name=RTX_4090 cpu_ram>=24 disk_space>=40 inet_down>=2000 dph_total<=0.40 verified=True' --raw --order inet_down-
```

| Field | Min | Why |
|-------|-----|-----|
| `inet_down` | 2000 Mbps | Pull speed. <1000 = stall risk |
| `reliability` | 0.98 | Avoid flaky hosts |
| `cuda_max_good` | 12.x | Match base image CUDA 12.6 |
| `geolocation` | US/EU | Latency |

**KNOWN BAD HOSTS (avoid):**
- `467312` — slow docker pull, stalls
- `34031` (Sweden) — kernel blocks `net.ipv4.ping_group_range` sysctl → container init fails

---

## 6. Deploy Procedure

### Step 1: Build & push (on code change)
```bash
cd /home/cybocrime/runpod/qwen3-tts-serverless-nigerian
git add -A && git commit -m "fix: ..." && git push origin main
# Cloud Build auto-triggers → pushes cybocrime/qwen3-tts:latest to Docker Hub (~6 min)
```

### Step 2: Verify build succeeded
```bash
TOKEN=$(cat /home/cybocrime/.gcp_token)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://cloudbuild.googleapis.com/v1/projects/qwen3-tts-builder/builds?pageSize=1" \
  | python3 -c "import json,sys; b=json.load(sys.stdin)['builds'][0]; print(b['status'])"
# Expect: SUCCESS
```

### Step 3: Pick a host (avoid known-bad, check inet_down)
```bash
source /tmp/vastcli/bin/activate
vastai search offers 'reliability>0.98 num_gpus=1 gpu_name=RTX_4090 cpu_ram>=24 disk_space>=40 inet_down>=2000 dph_total<=0.40 verified=True' --raw --order inet_down- | python3 -c "
import json,sys
offers = json.load(sys.stdin)
offers.sort(key=lambda x: x.get('inet_down',0), reverse=True)
for o in offers[:5]:
    print(f\"offer={o['id']} host={o['host_id']} geo={o['geolocation']} down={o['inet_down']}Mbps rel={o['reliability']} \${o['dph_total']}\")
"
```

### Step 4: Create instance
```bash
source /tmp/vastcli/bin/activate
vastai create instance <OFFER_ID> \
  --image cybocrime/qwen3-tts:latest \
  --env '-p 8000:8000' \
  --disk 40
# No --ssh/--jupyter → defaults to args runtype → runs CMD python3 serve.py
```

### Step 5: Wait for running (poll status)
```bash
vastai show instance <INSTANCE_ID> --raw | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('status:', d['actual_status'])
print('msg:', repr(d['status_msg']))
print('ports:', d.get('ports'))
"
# Expect: actual_status=running, ports shows mapping
```

### Step 6: Get external port & test
```bash
# External port from Vast console OR:
vastai show instance <INSTANCE_ID> --raw | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('IP:', d['public_ipaddr'])
print('ports:', d.get('ports'))
"
# Test:
curl -s http://<PUBLIC_IP>:<EXTERNAL_PORT>/health
# Expect: {"status":"ok",...}
```

---

## 7. Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `Unknown flag: python` | Missing `ENTRYPOINT []` | Add `ENTRYPOINT []` to Dockerfile, rebuild |
| `exec: "python": not found` | Base image has `python3` only | `CMD ["python3", "serve.py"]` |
| `ping_group_range` sysctl fail | Host kernel incompat | Destroy, pick different host |
| `loading` > 5 min, no progress | Slow/stalled docker pull | Destroy, pick host with `inet_down` > 2000 |
| `ports: None` after running | Port not requested | Add `--env '-p 8000:8000'` at create |
| Zombie instances appearing | CLI auto-retries failed creates | Destroy all, verify no template auto-deploys |

---

## 8. Cleanup

```bash
vastai show instances --raw | python3 -c "
import json,sys
for i in json.load(sys.stdin):
    print(i['id'], i['actual_status'], i['host_id'])
"
# Destroy each:
yes | vastai destroy instance <ID>
```

---

## 9. Secrets & Paths

| Item | Location |
|------|----------|
| Vast CLI venv | `/tmp/vastcli` (activate: `source /tmp/vastcli/bin/activate`) |
| Vast API key | `/home/cybocrime/.secrets/vast_api_key` |
| Docker Hub token | `/home/cybocrime/.secrets/docker_hub_token` |
| GCP token | `/home/cybocrime/.gcp_token` (`gcloud auth print-access-token`) |
| GCP project | `qwen3-tts-builder` |
| Docker image | `cybocrime/qwen3-tts:latest` (public) |
| Repo | `LogiSynthArchitect/qwen3-tts-serverless-nigerian` |
