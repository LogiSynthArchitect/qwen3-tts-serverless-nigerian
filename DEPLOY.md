# Qwen3-TTS VoiceDesign — Deployment Reference

## Architecture

```
GitHub push → Cloud Build (free tier) → Docker Hub (cybocrime/qwen3-tts:latest)
                                                      ↓
                                              Vast AI instance
                                          (docker pull at boot)
```

**Design principle:** One failure point (Docker pull on Vast host) instead of 4
(old: pull tarball + extract + pip install + config).

## Quick Deploy

### 1. Update code & rebuild image

```bash
git push origin main   # triggers Cloud Build (auto)
# Or manually:
gcloud builds submit --config=cloudbuild.yaml --project=qwen3-tts-builder
```

### 2. Create Vast instance

```bash
vastai create instance <OFFER_ID> \
  --image cybocrime/qwen3-tts:latest \
  --disk 40 \
  --ssh \
  --direct \
  --env '-p 8000:8000:8000' \
  --env 'HF_HOME=/workspace/hf_cache' \
  --onstart ./scripts/onstart.sh
```

The `--ssh --direct` mode keeps the container alive via SSH daemon.
Port mapping format: `-p <container_port>:<host_port>:<host_port>`.

### 3. Verify

```bash
# Check health
curl http://<INSTANCE_IP>:<MAPPED_PORT>/health

# List voices
curl http://<INSTANCE_IP>:<MAPPED_PORT>/voices

# Generate speech
curl -X POST http://<INSTANCE_IP>:<MAPPED_PORT>/tts \
  -H "Content-Type: application/json" \
  -d '{"voice":"ng_male_lagos_warm","text":"Hello world"}'
```

## Onstart Script

Path: `scripts/onstart.sh`

```bash
#!/bin/bash
cd /workspace/qwen3-tts
nohup python3 serve.py > /tmp/server.log 2>&1 &
```

This runs in the background when the container starts (SSH daemon keeps the
container alive). Server log is at `/tmp/server.log` inside the container.

## SSH Access

```bash
ssh -p <SSH_PORT> root@ssh<N>.vast.ai
```

Credentials: SSH key must be uploaded to Vast dashboard.

## Key Files

| File | Purpose |
|------|---------|
| `serve.py` | FastAPI server (routes: /tts, /voices, /health) |
| `handler.py` | TTS logic — default mode is `voice_design` |
| `inference.py` | Qwen3-TTS engine, 24-voice catalog |
| `Dockerfile` | FROM vastai/pytorch:cuda-12.6.3-auto, ENTRYPOINT [], CMD python3 serve.py |
| `cloudbuild.yaml` | GCP Cloud Build config — push to Docker Hub |
| `requirements.txt` | Python deps |

## Key Image Details

- **Base:** `vastai/pytorch:cuda-12.6.3-auto` (~9GB, cached on most Vast hosts)
- **CUDA:** `torch==2.6.0+cu124` (compatible with Vast driver 565.77 / CUDA 12.7)
- **ENTRYPOINT []:** Required — base image has its own ENTRYPOINT that
  swallows CMD without this
- **CMD:** `python3 serve.py` — auto-starts server when container runs
- **Workdir:** `/workspace/qwen3-tts`

## Troubleshooting

### CRITICAL: Default mode must be "voice_design"
The VoiceDesign model (`MODEL_TYPE=VoiceDesign`) only supports
`generate_voice_design()`. If `/tts` returns `"model does not support
generate_custom_voice"`, the default mode is wrong. Fix in `handler.py`:
```python
mode = data.get("mode", "voice_design")  # NOT "custom_voice"
```

### ENTRYPOINT must be cleared
Without `ENTRYPOINT []` in Dockerfile, the base image's ENTRYPOINT treats
our CMD as arguments → `python3 serve.py` is never executed.

### CUDA driver mismatch
Vast hosts run driver 565.77 / CUDA 12.7. The image pins
`torch==2.6.0+cu124` from PyTorch's cu124 channel. If building for a
different CUDA version, change the `--index-url`.

### Instance exits immediately
- In `args` mode (no `--ssh`): the CMD runs directly. If it crashes,
  the container exits with no logs visible. Use `--ssh --direct` + onstart
  to keep container alive for debugging.
- In `ssh` mode: the SSH daemon keeps the container alive. Onstart script
  starts the server in background. Check `/tmp/server.log` via SSH.

## Port Mapping (`--direct` mode)

With `--direct`, each container port gets a unique host port in the
`direct_port_start`–`direct_port_end` range. Find the mapping:

```bash
vastai show instance <ID> --raw | python3 -c "import json,sys; inst=json.load(sys.stdin); print(inst.get('ports'))"
```

The public IP for direct HTTP access is in `public_ipaddr`.
Your proxy hostname for SSH is in `ssh_host` with port in `ssh_port`.
