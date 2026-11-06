# 0.12.1 native analysis failure isolation

Status: implemented; parent Release build and CTest 11/11 passed (record `20261106T094014.415563Z-f401c0d9f2`). Read-only review confirmed 34 analysis-process assertions and two synthetic UI images. No user DAW process, model inference, GPU job or API was started by this review. Consolidated limits and later parent checks are in [RESULTS](RESULTS.md).

## Observed evidence and limits

The parent review found two local separation tasks reporting CUDA out-of-memory; the quality task subsequently attempted `model.cpu()` and failed a 1 MiB CPU allocation. A later 75-second, six-stem task stopped at separation progress with no result/error JSON. At inspection Windows had about 2.8 GiB of available commit headroom and 6.1 GiB of available physical memory. Those observations support an allocation-pressure problem. They do not identify the instruction or library responsible for the user's NULL-memory error; no matching crash stack was available.

Existing `2026-11-05-audio-analysis/worker-evidence` separation observations used only 7–8 second inputs and recorded roughly 1.285–1.287 GB process RSS. Those short-input measurements are not a commit-memory requirement or a guarantee for long, six-stem, quality jobs. The new thresholds below are conservative admission policy, not benchmark claims.

## Native changes

- `AnalysisWorkerProcess.h` owns the Windows helper and its descendants through a private Job Object. The child starts suspended, receives only its stdin/log handles, joins the job, and then resumes. Job flags `KILL_ON_JOB_CLOSE` and `DIE_ON_UNHANDLED_EXCEPTION` ensure owner cleanup and suppress the unhandled-exception dialog for this process tree. DAW/global process error mode is unchanged.
- Python starts with unbuffered stdout and `faulthandler`. Each task retains `process.log`, `worker-launch.json` with measured available resources and the supplied policy, and `worker-exit.json` with exit code/timing or the critical-memory reason. Native crash exits without `error.json` become an explicit failed task including the hexadecimal exit code. Exit 0 still requires the existing complete, matching result validation.
- Windows resources use `GetPerformanceInfo`: available commit is `(CommitLimit − CommitTotal) × PageSize`; available physical memory is `PhysicalAvailable × PageSize`. Before fingerprinting and again before starting Python, required available commit is 4 GiB for separation, 2 GiB for transcription/beats, and 1 GiB for chords. All require 512 MiB available physical memory. Failure returns a visible error; it does not import or mutate music.
- The same byte-valued `resource_policy` travels in `request.json` to the Python worker. Python may require additional known audio-buffer headroom. It must not silently lower these policy floors. During native polling, available commit below 512 MiB for one continuous second terminates only this analysis process tree. Unknown measurements are not treated as zero memory. Cancellation still has a short cooperative grace period; forced termination and the existing one-hour task ceiling are bounded on the file worker.
- `startJob` now handles `std::thread` creation errors as failures. Work-callable captures are released before publishing `done`, so UI completion polling cannot join while captured process/buffer destructors are still releasing resources. Model execution, process waits, log files and resource probes remain outside the audio and message threads.
- Analysis failure text is now shown in a selectable, read-only, scrollable results area. The exact reason is no longer available only in a truncated label/tooltip. No blocking error dialog was added.

## Focused regression coverage added

`AnalysisWorkerProcessSmoke.inc`, called by the existing workspace smoke harness:

- admission boundaries for all four task kinds and byte-valued protocol;
- critical-memory grace period and recovery reset;
- incomplete result refusal;
- a small Python process returning exit 37, exact quoted argument/log preservation and message-loop dispatch;
- a deliberately invalid native thread entry point in the **fixture subprocess only**, expected to terminate with `0xc0000005` without waiting for an error dialog;
- cancellation of a fixture subprocess and its owned sleeping descendant;
- missing executable produces a bounded failure.

These are fault fixtures, not MIR inference or performance measurements. `AnalysisPanel` adds synthetic failed-state assertions and 600×260 / 540×210 screenshots proving the full error remains available without hover, with import disabled. The parent must record actual execution/build results before marking these tests passed.

## Review references

- Microsoft [Job Object basic limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information): exception-dialog and close/kill semantics.
- Microsoft [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects): process-tree ownership.

## Remaining manual verification

After the recorded 0.12.1 build passes, the user can reopen the saved project and perform one short separation. On constrained memory the expected behavior is a clear refusal or bounded failed task, while the DAW remains usable and no tracks are imported. Success still needs separate real-model/manual evidence; native process-fixture success does not establish separation quality or eliminate every third-party native crash.
