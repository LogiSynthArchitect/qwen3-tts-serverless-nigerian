# Qwen3-TTS Vast.ai Deployment — Mesh Sheet

> Durable deployment record for Qwen3-TTS (Nigerian VoiceDesign, 20-voice catalog)
> on Vast.ai via custom Docker image. Cloning infra added 2026-07-17.
> Last verified: 2026-07-17.

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
# Voice list (20 VoiceDesign presets)
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

## 12. Cloning (v5 — real voice cloning, Base model)
**Why:** VoiceDesign presets (the 20 voices above) are text-described and drift
between generations — NOT brand-consistent. For real, reproducible brand voices we
use the **1.7B-Base** model's voice-cloning: extract a speaker embedding from a real
actor's reference clip ONCE, reuse it for every TTS call.

**Files added/changed:**
- `bridge/voices_cloned.json` — registry: voice_id → {ref_audio, ref_text, metadata}.
- `bridge/voices_cloned/*.wav` — real CC0 Nigerian-English speech extracted from
  Common Voice corpus (public domain). URLs extracted via `crw_search` from
  `benjaminogbonna/nigerian_common_voice_dataset` on HuggingFace; MP3 bytes
  decoded to 24kHz mono WAV + verbatim transcript preserved.
- `inference.py`:
  - `preload_clone_voices()` — at startup (Base only) extracts+caches embeddings
    via `create_voice_clone_prompt(ref_audio, ref_text)` into `self._clone_cache[vid]`.
  - `get_clone_prompt(vid)`, `resolve_cloned_voice(vid)`, `get_cloned_voices()`.
  - `get_inference_engine()` calls `preload_clone_voices()` after engine creation.
- `handler.py`: voice_clone mode resolves cloned voice_id first (from registry),
  then falls back to CustomVoice `voices.json`. Uses cached `voice_clone_prompt`
  when available (no per-request re-extraction).
- `serve.py`: new `GET /clone-voices` endpoint (mirrors `/voices`).
- `Dockerfile.base` — Base model variant (`MODEL_TYPE=Base`, pulls 1.7B-Base).

**API (cloning):**
```bash
# List cloned brand voices
curl http://<IP>:<PORT>/clone-voices
# TTS using a cloned voice (embedding reused from cache)
curl -X POST http://<IP>:<PORT>/tts \
  -H "Content-Type: application/json" \
  -d '{"text":"...","mode":"voice_clone","voice":"brand_narrator_ng_male","language":"Auto"}'
```
**Deploy (cloning):**
```bash
docker build -f Dockerfile.base -t cybocrime/qwen3-tts:base . && docker push cybocrime/qwen3-tts:base
vastai create instance <OFFER_ID> --image cybocrime/qwen3-tts:base --ssh --direct \
  --env '-p 8000:8000' --disk 40 --onstart-cmd "cd /workspace/qwen3-tts && python3 serve.py"
```
**Ref audio requirements:** WAV/MP3, 24kHz, 20-60s clean single-speaker speech.
`ref_text` MUST be verbatim transcript (Qwen3-TTS requires it).

**Voice catalog (as of 2026-07-17):**

| voice_id | Real voice | Accent | Duration | Source |
|---|---|---|---|---|
| `brand_narrator_ng_male` | Nigerian male, deep conversational | Nigerian English | 78s | CC0 Common Voice |

Ghanaian and Kenyan entries removed — no CC0 English speech datasets found
for those accents via CRW. Add them when real voice-actor recordings are sourced.

**Status:** Infra built (2026-07-17). NOT yet E2E-proven on a live Base instance —
needs a GPU Vast instance running `:base` image. Real CC0 audio in place.
