# Qwen3-TTS Vast.ai Deployment — Mesh Sheet

> Durable deployment record for Qwen3-TTS (Nigerian VoiceDesign, 24-voice catalog)
> on Vast.ai via custom Docker image. Last verified: 2026-07-17.

## 1. Architecture (v4 — single failure point)
```
GitHub push
  → Cloud Build (project: qwen3-tts-builder)
  → Docker Hub: cybocrime/qwen3-tts:latest  (public, ~12GB)
  → Vast instance (ssh_direct runtype)
  → docker pull (ONLY failure point) + FastAPI serve.py:8000
```
- Base image: `FROM vastai/pytorch:cuda-12.6.3-auto` (~9GB, cached on most hosts)
- Custom layers add ~3GB at boot.

## 2. Dockerfile (CRITICAL — both fixes required)
```dockerfile
FROM vastai/pytorch:cuda-12.6.3-auto
# ... install deps, copy code ...
ENTRYPOINT []                          # MUST clear base entrypoint (base swallows CMD)
CMD ["python3", "serve.py"]            # base has python3, NOT python
EXPOSE 8000
```
**Bugs found + fixes:**
1. Base wrapper swallowed CMD → `Unknown flag: python / serve.py` → add `ENTRYPOINT []`.
2. `exec: "python": executable file not found` → use `python3` in CMD.
3. `args` runtype → `ports: None` → server unreachable → use `ssh_direct` (see §3).

## 3. Deploy command (PROVEN WORKING)
```bash
vastai create instance <OFFER_ID> \
  --image cybocrime/qwen3-tts:latest \
  --ssh --direct \
  --env '-p 8000:8000' \
  --disk 40 \
  --onstart-cmd "cd /workspace/qwen3-tts && python3 serve.py"
```
- Vast CLI venv: `source /tmp/vastcli/bin/activate`
- API key: `/home/cybocrime/.secrets/vast_api_key`

## 4. Host selection
- Filter: `inet_down>=2000`, `reliability>=0.98`.
- AVOID host `467312` (pulls stall).
- AVOID host `34031` (Sweden — kernel blocks `net.ipv4.ping_group_range` sysctl → init fails).
- Working host: `453772` (New York) via `ssh_direct`.

## 5. Cold-start timing
- ~4-6 min after instance RUNNING → `GET /health` returns `{"status":"ok"}`.
- ~5-7 min to first audio (model lazy-loads on first `/tts` call).
- TOTAL from create → first audio: ~10 min. Plan accordingly.

## 6. API usage
```bash
# Health
curl http://<IP>:<PORT>/health
# Voice list (24 voices)
curl http://<IP>:<PORT>/voices
# TTS (voice_design mode)
curl -X POST http://<IP>:<PORT>/tts \
  -H "Content-Type: application/json" \
  -d '{"text":"...","mode":"voice_design","voice":"<preset_id>","language":"Auto","output_format":"wav"}'
# Returns JSON with base64 audio field.
```
**Model limitation (code, not infra):** `generate_custom_voice` NOT supported by the 1.7B
VoiceDesign model. Use `mode:"voice_design"` + `voice:"<preset_id>"` (from `/voices`).
- WRONG: `mode:"custom_voice"` → rejected.
- WRONG: `voice_id` key → wrong field name.

## 7. Example run (verified)
- 107-word story → 3 voices:
  - `ng_male_lagos_warm` → 39.9s audio
  - `ng_female_lagos_bright` → 43.8s audio
  - `us_female_general` → 43.0s audio
- Output: 24kHz MP3/WAV, decoded to local `/tmp/story_*_final.wav` (now copied to
  `/home/cybocrime/runpod/generated_audio/` for access).

## 8. Next-time checklist
- [ ] Dockerfile has `ENTRYPOINT []` + `CMD ["python3","serve.py"]`
- [ ] Use `ssh_direct` runtype (never `args`)
- [ ] Filter hosts: inet_down>=2000, reliability>=0.98, skip 467312 & 34031
- [ ] Wait ~10 min before first TTS test
- [ ] TTS body uses `mode:"voice_design"` + `voice` (preset id), NOT `custom_voice`/`voice_id`
- [ ] Kill zombie instances after testing (CLI auto-retries create → extra instances)

## 9. Known zombies destroyed
45156415, 45156984, 45157388, 45158199, 45158246, 45158783, 45158890,
45159108, 45159180, 45160821.

## 10. Live instance (as of 2026-07-17)
- ID 45160836 — New York host 453772, ssh_direct, port 8000→40051.
- Endpoint: `http://108.27.154.161:40051` (destroy when done to stop billing).

## 11. Blocker: memtree
- VPS memtree DB (localhost:5433) unreachable from this VM — Hetzner SSH tunnel
  returns `Permission denied (publickey)`. Knowledge preserved here + in repo
  (`VAST_DEPLOYMENT_GUIDE.md`, `DEPLOYMENT_LESSONS.md`) instead.
