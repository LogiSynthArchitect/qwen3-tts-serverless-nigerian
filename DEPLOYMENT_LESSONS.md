# Qwen3-TTS Deployment — Complete Reference & Lessons Learned

**Project:** Qwen3-TTS VoiceDesign (Nigerian + African + global 24-voice catalog)
**Infra:** GitHub → Cloud Build → Docker Hub → Vast.ai
**Date established:** 2026-07-17
**Status:** PROVEN WORKING (instance 45160836, New York)

---

## 1. What Is In The Repo

| File | Lines | Purpose |
|------|-------|---------|
| `Dockerfile` | 54 | Base `vastai/pytorch:cuda-12.6.3-auto` + our app. **MUST have `ENTRYPOINT []`** + `CMD ["python3","serve.py"]` |
| `serve.py` | 126 | FastAPI wrapper. Exposes `/health`, `/voices`, `/tts`. Imports `handler.py` (RunPod-style) and adapts it |
| `handler.py` | ~450 | RunPod serverless handler. Routes `voice_design` / `custom_voice` / `voice_clone` modes |
| `inference.py` | 1177 | `Qwen3TTSInference` class. Model load + `generate_voice_design`, `generate_custom_voice`, `generate_voice_clone` |
| `requirements.txt` | 26 | Python deps (qwen-tts, torchaudio, transformers pinned, etc.) |
| `cloudbuild.yaml` | 55 | Cloud Build: docker build → Docker Hub login (Secret Manager) → push `cybocrime/qwen3-tts:latest` |
| `VOICES_CONFIG_PATH` | — | JSON of 24 curated voices (id, name, region, gender, age, language, accent, emotion) |
| `VAST_DEPLOYMENT_GUIDE.md` | 197 | Step-by-step deploy procedure |

---

## 2. Cold Start Timeline (measured on instance 45160836)

| Phase | Time | Notes |
|-------|------|-------|
| Instance create → `loading` | 0s | API returns instance ID instantly |
| Docker pull (base 9GB + custom 3GB) | ~3-5 min | On 17 Gbps host (California 366851). Slower hosts (≤574 Mbps) stall >8 min |
| Container init → `running` | +10-30s | After pull complete |
| Model lazy-load on first `/tts` | +20-40s | `load_model()` called on first request, NOT at boot |
| **Total to health OK** | **~4-6 min** | Health endpoint responds as soon as container runs (model not yet loaded) |
| **Total to first audio** | **~5-7 min** | Includes model load on first TTS call |

**Key insight:** `/health` returns OK immediately after container start (model loads lazily on first TTS). Don't wait for model load before testing health.

---

## 3. The Three Bugs We Hit (and fixes)

### Bug 1: Vast wrapper swallowed CMD
- **Symptom:** Container "running" but port 8000 refused. Logs: `Unknown flag: python / serve.py`
- **Root cause:** Base image `vastai/pytorch` has its own ENTRYPOINT. With `args` runtype, our CMD was passed as args to that entrypoint.
- **Fix:** `ENTRYPOINT []` in Dockerfile (clears base entrypoint, CMD runs directly).

### Bug 2: `python` not found
- **Symptom:** `exec: "python": executable file not found in $PATH`
- **Root cause:** Base image only has `python3`, not `python`.
- **Fix:** `CMD ["python3", "serve.py"]`.

### Bug 3: `args` runtype → no port mapping
- **Symptom:** Instance "running" but `ports: None`, server unreachable.
- **Root cause:** `args` runtype preserves ENTRYPOINT but does NOT map `-p` ports to external interfaces reliably.
- **Fix:** Use `ssh_direct` runtype + `--env '-p 8000:8000'` + `--onstart-cmd "cd /workspace/qwen3-tts && python3 serve.py"`.

### Host-level issues (not our code):
- Host `467312` — docker pull stalls (slow link). Avoid.
- Host `34031` (Sweden) — kernel blocks `net.ipv4.ping_group_range` sysctl → container init fails. Avoid.

### Model capability (code, not infra):
- `generate_custom_voice` is NOT supported by the 1.7B VoiceDesign model. Use `mode: "voice_design"` with a named `voice` preset instead.

---

## 4. Correct Deploy Command (PROVEN)

```bash
source /tmp/vastcli/bin/activate
vastai create instance <OFFER_ID> \
  --image cybocrime/qwen3-tts:latest \
  --ssh --direct \
  --env '-p 8000:8000' \
  --disk 40 \
  --onstart-cmd "cd /workspace/qwen3-tts && python3 serve.py"
```

**Host selection:** `inet_down >= 2000`, `reliability >= 0.98`, avoid 467312 & 34031.

---

## 5. API Usage (from live instance)

Base URL: `http://<PUBLIC_IP>:<EXTERNAL_PORT>` (current: `http://108.27.154.161:40051`)

### GET /health
```bash
curl http://108.27.154.161:40051/health
# → {"status":"ok"}
```

### GET /voices
```bash
curl http://108.27.154.161:40051/voices
# → {"count":24,"voices":[...]}
```

### POST /tts — CORRECT (voice_design mode with preset)
```bash
curl -X POST http://108.27.154.161:40051/tts \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Your story text here",
    "mode": "voice_design",
    "voice": "ng_male_lagos_warm",
    "language": "Auto",
    "output_format": "wav"
  }' -o output.wav
```
- `voice` must be a preset ID from `/voices` (e.g. `ng_male_lagos_warm`, `ng_female_lagos_bright`).
- Response: `{"status":"success","sample_rate":...,"duration_sec":...,"audio_base64":"..."}` OR raw audio file if streaming.
- **DO NOT** use `voice_id` (wrong key) or `mode: "custom_voice"` (unsupported by 1.7B model).

---

## 6. Secrets & Paths

| Item | Location |
|------|----------|
| Vast CLI venv | `/tmp/vastcli` → `source /tmp/vastcli/bin/activate` |
| Vast API key | `/home/cybocrime/.secrets/vast_api_key` |
| Docker Hub token | `/home/cybocrime/.secrets/docker_hub_token` |
| GCP token | `/home/cybocrime/.gcp_token` (`gcloud auth print-access-token`) |
| GCP project | `qwen3-tts-builder` |
| Docker image | `cybocrime/qwen3-tts:latest` (public, ~12GB) |
| Repo | `LogiSynthArchitect/qwen3-tts-serverless-nigerian` |
| Cloud Build logs | GCS `888355923393-global-cloudbuild-logs` |

---

## 7. Next-Time Checklist (do this, in order)

1. Code change? → `git push origin main` → Cloud Build auto-triggers (~6 min) → verify `SUCCESS`
2. `vastai search offers ... --order inet_down-` → pick host with `inet_down>=2000`, avoid 467312/34031
3. `vastai create instance <OFFER_ID> --image cybocrime/qwen3-tts:latest --ssh --direct --env '-p 8000:8000' --disk 40 --onstart-cmd "cd /workspace/qwen3-tts && python3 serve.py"`
4. Poll `vastai show instance <ID>` until `actual_status=running` and `ports` shows 8000→external
5. `curl http://<IP>:<EXT_PORT>/health` → expect `{"status":"ok"}`
6. Test TTS with `mode:"voice_design"` + valid `voice` preset
7. Destroy old/zombie instances: `vastai show instances` → `yes | vastai destroy instance <ID>`
