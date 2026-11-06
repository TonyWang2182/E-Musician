# Agent generation defaults and context — 2026-11-06

Status: implemented; offline regression verified. Real-model clarification behavior still awaits the optional one-call decision probe or user testing. Scope: Python Agent/tool contract and deterministic tests only. No native build, running-user-DAW control, paid language request, cloud inference or preference/key change was performed by this subtask.

## Findings and plan

The existing public snapshot already supplies `bpm`, `numerator`, `denominator` and `position_seconds`; the generation host takes those values from the project. Missing native tempo data is therefore not an established cause. The Agent currently has no normalized default-generation context, requires a duration on every start tool call, delegates bars-to-seconds calculation to the language model and leads with generic “understand the goal / propose_plan” guidance before generation-specific instructions. These are concrete sources of unnecessary clarification. The exact user/model conversation is not stored in the metadata-only audit, so this inspection cannot attribute the repeated BPM question to a particular model response.

Implemented changes:

1. Supply a typed generation-default summary from the fresh frozen snapshot: actual tempo/meter, insertion position and seconds per bar. Explicitly tell the language model to use these instead of asking the user to repeat BPM.
2. Resolve omitted duration locally to 20 seconds, shortened to a valid shorter selected time range; support a bar count without requiring the language model to calculate seconds. Preserve explicit unsupported/invalid limits instead of silently clamping them.
3. Permit a neutral music description when no style/instrument is specified. Keep explicit user details, generate only when the user requests generation, and keep the existing visible new-track confirmation.
4. Add meaningful offline tool/runtime regression coverage. Preserve source, command, timestamps and raw logs with Recorder. A mocked language provider proves orchestration/defaulting, not real-model intent accuracy.

## Behavior and boundaries

`generation_defaults` now exposes actual project BPM/meter, seconds per bar and the frozen insertion position in each fresh request. The generation tool accepts an omitted duration and supplies 20 seconds locally; a valid shorter selected time range supplies its own span. Explicit `duration_bars` is converted using the actual denominator as well as numerator and BPM, then reduced to the existing native `duration_seconds` contract. A neutral prompt is available only when musical style was unspecified; explicit description, duration, lyrics and seed are preserved. No global tempo edit occurs. Explicitly unsupported tempo/meter, short selections and conflicting duration fields fail instead of silently widening or changing the request.

The system guidance now distinguishes generating from informational conversation, uses generation-specific tools rather than generic editing guidance, and directs the model to proceed from candidate completion to the existing visible new-track review. It tells the model to report adopted duration/current BPM briefly, instead of asking for known values again. A requested BPM different from the project is explicitly unsupported by the independent generation parameter contract: explain that boundary or propose a separate tempo edit; never claim the requested BPM was applied. There is no heuristic keyword-based auto-generation and no forced tool call. The existing Apply button remains the only import authorization.

The working structure remains: user request plus fresh project snapshot -> model chooses a tool -> local typed adapter resolves defaults and validates scope -> native generation job produces an immutable candidate -> model proposes import -> user confirms -> native command commits one new track with readback and Undo. This change strengthens the snapshot-to-tool step, without adding audio-thread work, a second writable project state, or any network request to the real-time pipeline.

## Verification

| Check | Result | Evidence |
| --- | --- | --- |
| Generation contract/runtime suite | 34/34, 6.845 seconds | `docs/builds/20261106T093030.699747Z-5bd84a208f.json` |
| Full offline Agent regression | 334/334, 54.077 seconds | `docs/builds/20261106T093049.883918Z-5ce0d9c8de.json` |
| Changed Agent source whitespace check | Passed | `git diff --check -- scripts/music_agent/generation.py scripts/music_agent/runtime.py tests/test_music_agent_generation.py` |

Both test runs used Python 3.14 on the existing Windows development machine and Recorder with configuration label Release. These are Python functional tests, not DAW performance, device playback, cloud inference or music-quality measurements. Raw logs are the corresponding `build-logs/<record-id>.log`. The focused run retained the whole-source fingerprint `7940e6dce1fdea496828003e90600d011e5f4b86a1da78db5555cab2172b7c4b`. The full run correctly records a concurrent native `AnalysisPanel.cpp` change; all Agent code and tests remained unchanged throughout the run.

The nine added tests cover actual 93 BPM/3/4 defaults without a hardcoded tempo; 6/8 bar conversion; missing duration; short selected ranges; explicit out-of-range refusal; preserving provided musical parameters; conflicting seconds/bars; informational questions remaining non-mutating; and a two-step fixture tool flow reaching review without Apply. They do not establish that an arbitrary real LLM will always choose the right tool or never clarify.

Parent audit review confirms that logs contain task/provider/job metadata, not the user's prompt or the model's response. The repeated BPM question is a user-reported symptom; aggregate token/call counters cannot attribute that symptom to an individual conversation or imply all calls belonged to one generation.

## Manual and optional semantic checks

1. On a disposable 93 BPM, 3/4 project, say `生成一段温暖的爵士钢琴纯音乐，先让我试听` without BPM or duration. Expect one candidate prepared at the frozen playhead using 20 seconds and the actual project tempo; no follow-up BPM form, and no track added before Apply.
2. On 120 BPM, 6/8, say `生成8小节吉他纯音乐`. Expect the request to resolve to 12 seconds locally; actual generated timing still needs audition and is not an exact-bar guarantee.
3. Ask `你能生成音乐吗，先说明流程`. Expect explanation without an unsolicited generation job.
4. Explicitly request a different BPM or a duration outside 10–120 seconds. Expect the current limitation to be explained, not a silent global-tempo edit, silent truncation or an unsupported success claim.

The optional probe is prepared at ignored `build-logs/generation_decision_probe.py`. Following parent scope, it uses a simulated read-only 93 BPM/3/4/17.5-second project, with no actual DAW process. `--live` reads the existing saved OpenAI configuration without changing it and allows exactly one provider `complete` call for item 1. It intercepts the returned message before any tool execution, asserts that its first decision is `start_generation`, normalizes arguments locally, and records only model name, tool names, numerical adopted defaults, elapsed time and token usage. It stops on a clarification or failure without retry. This verifies language-to-tool choice only: it invokes no music GPU job, imports no audio, and cannot claim end-to-end generation or listening quality.

Default invocation is an explicitly offline wrapper self-check. That check passed under Recorder `docs/builds/20261106T093916.788889Z-fb9dcee725.json` with synthetic tool choice, zero API/network inference, zero music jobs and zero executed tools. Its report is ignored `build-logs/generation-decision-probe-offline.json`. This subtask did not execute `--live`; parent may run the single separately authorized request and append its result. No production source or test-suite file changed after the 334-test run.
