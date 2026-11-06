# Agent generation integration — 2026-11-06

Status: implemented and actual native/cloud integration passed with both a deterministic language provider and one bounded live `gpt-5-mini` probe. This document does not claim music quality, physical playback or ASIO performance.

## Working principle

The language model describes music through a typed generation tool. The Agent freezes the current project, tempo, meter, selection and insertion position, then the native host starts a separate background helper that talks to the cloud service. The helper downloads and verifies the real audio; the Agent receives only bounded candidate metadata and identifiers. The sidebar offers Preview/Stop and a review of the new audio track. Only Apply submits the reviewed candidate hash to the existing revision-checked command interface. The Agent checks the resulting track and clip, and one Undo removes this import. Cloud inference, downloading and language-model calls do not run in the audio callback.

## Implemented scope

- `scripts/music_agent/generation.py`: start, read, cancel, preview and propose-import tools; bounded prompt/lyrics/duration/seed; empty-project support; frozen playhead/time-range scope; immutable candidate identity; format and capacity checks; private path/endpoint stripping.
- `bridge.py` and `runtime.py`: capability discovery, locally polled progress, one compute request per Agent task, cancellation, guarded import, receipt/readback checks, no automatic re-submit of an uncertain commit. Repeating the identical start tool within a task reuses its original job.
- `server.py` and `web/*`: authenticated manual Preview/Stop, bilingual generated-audio review, live job phase labels, music-generation capability and useful empty-selection hint. “Configured” does not claim cloud reachability; connection is checked when starting a job.
- `audit.py`: job/result/request hashes may enter metadata audit. No prompt, lyrics, keys or audio are added to this audit.
- `tests/MusicAgentTempoIntegration.py`: capability assertions now verify required IDs instead of a fixed total of ten groups.

Start accepts 10–120 seconds. Actual output may differ, so candidates are accepted up to the native validation ceiling of 150 seconds and the review shows actual duration. Generation timing is a model condition, not a guarantee of perfect bar alignment. Inserting beyond an explicitly selected time range is refused. A new track does not overwrite existing music.

Cancellation distinguishes local stopping from remote acknowledgement. `cancel_completed` is true only when the local job is cancelled and the cloud confirms cancellation. A lost connection or an acknowledgement still marked cancelling is displayed as unconfirmed/pending; it is never described as the GPU having stopped.

## Evidence

All commands below use `scripts.dev.Recorder`; linked records preserve commands, source fingerprints, start/end timestamps and raw ignored log paths. No application build was performed by the Agent subtask.

| Check | Result | Record |
| --- | --- | --- |
| Final full Agent regression including generation/cancellation | 319/319 passed | [record](../../builds/20261106T073305.725362Z-f9560ed200.json) |
| Existing runtime/audit regression after audit fields | 37/37 passed | [record](../../builds/20261106T072443.292098Z-d44c12a972.json) |
| Generation contracts/runtime including remote cancellation | 19/19 passed | [record](../../builds/20261106T072852.126796Z-3197014547.json) |
| Actual sidebar HTML in owned headless Edge, final rerun | English 340×800 and 1000×800; Chinese 400×800 passed | [record](../../builds/20261106T073421.621622Z-08e86a3c46.json) |

The 19 generation tests cover empty projects, playhead/time-range boundaries, invalid/NaN/boolean inputs, output format limits, wrong/stale project/tempo/meter, changing revision/selection, private metadata stripping, immutable hashes, readback mismatch, explicit review, single Undo, duplicate compute prevention and cancellation truth.

Sidebar artifacts are under `build/generation-agent-web/`: three PNGs, the captured DOM and `results.json`. The 340px English and 400px Chinese PNGs were visually inspected. Automated checks cover visible review, enabled Preview/Stop, exact preview API requests, new-track language, empty-selection guidance, expected viewport/language and no horizontal overflow. These fixtures contain explicitly synthetic candidate data and do not prove inference.

### Follow-up: asynchronous audition feedback

The first review found that accepting a preview request did not expose a later preparation/device failure. The Agent now retains the preview job ID, polls `get_job` through preparation, and then reads the existing preview-stream status. No-output, decoder failure and DAW disconnection appear in the candidate card; they do not silently become “playing” or remove the still-valid import review. Stop wins a concurrent status refresh. Active-preview polling is 1 Hz and never waits for the language model. Candidate sample rates now match the native 16–96 kHz contract.

- [Focused generation tests](../../builds/20261106T075203.406242Z-5fc1080954.json): 24/24 passed, including preparation/stream outcomes, no output device, disconnection, stop race and sample-rate boundaries.
- [First UI attempt](../../builds/20261106T075210.973150Z-e8e7652805.json): failed because the fixture inspected the label before the prior idle polling interval. The observation is retained.
- [Actual bilingual sidebar rerun](../../builds/20261106T075309.682606Z-23b53d7f8e.json): all three viewports passed, including a simulated async device failure visibly replacing “Preparing preview” and a following Stop. The updated 340px screenshot was visually inspected.

The subsequent [full Agent regression](../../builds/20261106T075553.928270Z-4561a6821a.json) passed **324/324** in 60.997 seconds. Agent source and Agent test fingerprints were unchanged throughout this run. Other agents changed non-Agent source, so the recorder correctly flags the whole repository as changed; this is not a frozen application-build claim.

## Integration runner and remaining validation

`tests/MusicAgentGenerationIntegration.py --exe <0.12.0 exe> --duration 12` uses a deterministic language provider but the actual native process and configured generation service. It verified one real cloud result, review without editing, preview preparation/device status, explicit import/readback, Undo/Redo, save/reopen and reopening the saved local asset with generation disabled. It never opens user projects or physical audio devices and compares protected user files/settings before and after.

An explicit `--live` option uses the existing configured language provider unchanged, with at most four language requests and one generation request bounded by `--duration`. One authorized probe has passed. A failure stops that probe instead of retrying a paid model request. Reports contain model name and token usage, never key or preference contents. `--fixture-service` is a separate evidence label for deterministic generation-service tests and cannot be combined with `--live`.

### Actual native/cloud results

Both successful runs used the owned `0.12.0` Release EXE SHA-256 `017ced8ef2309da0bc2d4228466369cab4b35b5b41e6df55ad270cd9601b3641`, an offline test audio host, the configured SSH gateway and real `ace-step-1.5-xl-turbo`. The request was 12 seconds at 120 BPM, 4/4; output was 12 seconds, 48 kHz stereo. Timings below are single request-to-review observations, not a performance benchmark or quality score.

| Run | Actual result | Evidence |
| --- | --- | --- |
| Deterministic language provider + actual ACE/native | All seven checks passed; candidate review after 6.472 s | [record](../../builds/20261106T080221.669747Z-1e3d01724b.json), [result](AGENT-REAL-INTEGRATION.json) |
| Existing live `gpt-5-mini` + actual ACE/native | All seven checks passed; candidate review after 40.639 s; two language requests, 17,922 input / 2,590 output tokens | [record](../../builds/20261106T080309.327868Z-495121e1d1.json), [result](AGENT-LIVE-INTEGRATION.json) |

Both reports confirmed no project edit before explicit Apply, one imported audio track with exact candidate/start/duration readback, Undo/Redo, save/reopen, and reopening with the generation registry unavailable. Preview returned `unavailable` with the explicit no-audio-output message, correctly reflecting the offline test host. No physical playback is inferred. User settings, encrypted key files and test projects were unchanged; only transient cache/render/temp and the Agent's own audit are excluded from the protection comparison.

Two failed attempts are retained: [initial baseline scan](../../builds/20261106T075906.404327Z-db365dc65f.json) stopped before a DAW/GPU request when the older shared guard read a concurrently written render-job file; the owned guard now excludes only transient locations and protects the actual LOCALAPPDATA key/preferences files. [First actual candidate](../../builds/20261106T080046.736426Z-6492f4fd33.json) reached review but exposed a missing project/revision envelope on the preview command. That bridge bug was fixed, covered by a meaningful regression, and the full real sequence was rerun successfully. [Focused contracts](../../builds/20261106T080214.705009Z-33bf1e6b2e.json) then passed 25/25.

The final [full Agent regression after that native-envelope fix](../../builds/20261106T080413.231293Z-8f2678c9da.json) passed **325/325** in 58.701 seconds. No further music-generation or language-model calls are needed for this subtask.

Manual validation after the parent delivers the native build:

1. Open an empty project, open Agent, and request 12 seconds of instrumental music at the current tempo. The music-generation capability should be configured and the request should work without choosing a source clip.
2. Confirm progress updates while ordinary DAW interaction remains available. No track should appear before Apply.
3. Preview and Stop from the candidate card. Check the actual duration, then Apply once; verify one new audio track. Undo once, Redo, save and reopen.
4. Change tempo or project after reviewing a candidate; the old plan must refuse to apply. Disable the cloud service and reopen the saved project; its accepted audio must remain available locally.
5. Cancel a running generation. Read whether cloud cancellation is confirmed or still pending/unconfirmed; do not infer remote stop merely because the local task ended.

Physical audition, music quality and playback-under-cloud-load remain manual acceptance items.
