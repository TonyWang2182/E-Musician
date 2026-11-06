# Cloud compute protocol 2

Bind only `127.0.0.1:18082`; the existing authenticated SSH boundary transports requests. No public listener or credentials in request bodies. All analysis seconds refer to the uploaded frozen selection, with zero at its start; project offset/warp mapping stays on the desktop.

- `GET /health`: service/version/queue metadata.
- `GET /capabilities`: `providers` with `kind`, `model_id`, `execution:"cloud"`, `available`, `default`, `detail`, `max_duration_seconds`.
- `HEAD /assets/<sha256>`: 200 if verified immutable WAV exists, otherwise 404.
- `PUT /assets/<sha256>`: raw WAV with exact `Content-Length` (no chunked transfer). Streams to a unique partial, checks SHA and WAV geometry, then atomically publishes. Limit 512 MiB; mono/stereo, PCM16 or FLOAT32, 8–96 kHz, duration >0 and <=600 s. Response contains `sha256` and audio metadata. Same content is idempotent.
- `POST /jobs`: JSON <=32768 bytes. `{request_id,kind,model_id,input:{sha256},parameters:{}}` for MIR. `kind` is `separate`, `transcribe`, `chords` or singular `score`. Exact task mapping is in `protocol.py`. MIR parameters are initially empty: no silent acceptance of unsupported legacy model knobs.
- Generation request: `{request_id,kind:"generate",model_id,parameters:{prompt,lyrics,instrumental,duration_seconds,bpm,time_signature,seed}}`; no input. ACE and YuE2 accept requested 10–120 s. YuE2 uses a semantic-token budget and reports actual duration and truncation; a duration request is not a promise of a natural ending or musical adherence.
- `GET /jobs/<id>` and `POST /jobs/<id>/cancel`: states `queued`, `loading`, `running`, `postprocessing`, `cancelling`, `ready`, `failed`, `cancelled`, `interrupted`. Ready response includes `result`. Same ID/same canonical request returns existing state, changed request returns 409. Queue is bounded to 16.
- `GET /jobs/<id>/artifacts/<artifact-id>`: only ready-job, allowlisted result artifacts. No filesystem path accepted. Downloads use Content-Length and SHA metadata; client verifies before accepting.

Result schema version 2: `kind`, `model` (ID and revisions), `duration_seconds`, `time_basis:"input_relative_seconds"` (generation uses `output_relative_seconds`), `artifacts`, `stems`, `notes`, `controllers`, `midi_tracks`, `chord_regions`, `beat_events`, `structure_regions`, `annotations`, `summary`, `metrics`, `warnings`.

Artifact: `id` (safe filename), `role`, `bytes`, `sha256`; audio adds sample rate/channels/frames/duration/sample format. Generated deliverable is `audio.wav` PCM16. Original score/annotation evidence can be additional artifacts. SCNet stems remain FLOAT32 to preserve legitimate >1 peaks; the DAW must not clip or normalize them silently.

MIDI track: `{id,name,instrument,program,is_drum,channel,notes,controllers}`. Notes use `{pitch,start_seconds,duration_seconds,velocity,channel}`, controllers use `{time_seconds,controller,value,channel}`; MIDI channels are 1–16. Flat preview notes/controllers additionally carry `track_id`. Chords preserve `label` and `raw_label`; `score:null` and `uncertain:true` denote uncalibrated predictions. Beat events use `{time_seconds,is_downbeat}`; structure uses `{label,start_seconds,end_seconds}`. Model-absent fields are empty, never invented. Summary contains track/note/controller/chord/beat/annotation counts.

The HTTP service is not the project authority. Downloaded results remain candidates until the existing explicit acceptance command succeeds. Integration/accuracy/listening are distinct from service and inference validation.
