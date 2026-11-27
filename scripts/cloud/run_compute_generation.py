"""Adapt both cloud music generators into the existing local generation candidate."""
from pathlib import Path
import time
try:
    from . import compute_client as client
    from .run_generation import build_payload, inspect_wav
except ImportError:
    import compute_client as client
    from run_generation import build_payload, inspect_wav


def run(path, config=None, tunnel_factory=client.Tunnel):
    path = Path(path).resolve()
    directory = path.parent
    request = client.read_json(path, 128 * 1024)
    if (directory / "result.json").exists():
        raise client.GenerationError("This immutable generation candidate already exists.")
    config = config if config is not None else client.registry(request.get("compute_root"))
    model_id = client.select_model(config, "generate", request.get("model_id", ""))
    previous = build_payload(request, {"model_id": model_id})
    parameters = {k: v for k, v in previous.items() if k not in {"request_id", "kind", "model_id"}}
    payload = {"request_id": previous["request_id"], "kind": "generate", "model_id": model_id, "parameters": parameters}
    cancel = lambda: (directory / "cancel").exists()
    started = time.monotonic()
    def progress(phase, fraction=None):
        client.atomic_json(directory / "progress.json", {"phase": phase, "progress": fraction, "elapsed_seconds": time.monotonic() - started})
    tunnel = tunnel_factory(config, directory)
    try:
        client.check_cancel(cancel)
        progress("connecting")
        tunnel.open()
        client.select_model(tunnel.call("GET", "/capabilities"), "generate", model_id)
        result = client.task(tunnel, payload, directory, cancel, progress)
        progress("downloading")
        artifacts = client.download_artifacts(tunnel, payload["request_id"], result, directory, cancel, progress)
        if "audio.wav" not in artifacts:
            raise client.GenerationError("The generation task did not produce its audio deliverable.")
        audio, peaks = inspect_wav(directory / "audio.wav", artifacts["audio.wav"])
        client.check_cancel(cancel)
        # Requested timing is provenance. The audio geometry above records the
        # actual duration; YuE2 does not promise a natural ending at this budget.
        output = {"schema_version": 1, "job_id": request["job_id"], "result_id": request["job_id"], "kind": "generate",
            "execution": "cloud", "audio": audio, "model": result["model"], "parameters": result.get("parameters", parameters),
            "source": request.get("source", {}), "waveform_peaks": peaks, "warnings": result.get("warnings", []),
            "metrics": result.get("metrics", {}), "artifacts": result["artifacts"],
            "truncated": result.get("truncated"), "conditioning": result.get("conditioning", {}),
            "processing": result.get("processing", {})}
        output["limitations"] = result.get("warnings", [])[:20]
        raw_truncation = result.get("truncated")
        stages = {}
        if isinstance(raw_truncation, dict) and raw_truncation and all(type(value) is bool for value in raw_truncation.values()):
            stages = raw_truncation
            truncated = any(stages.values())
        elif raw_truncation is None or type(raw_truncation) is bool:
            truncated = raw_truncation
        else:
            raise client.GenerationError("The model returned an invalid generation completion state.")
        output["truncated"] = truncated
        output["completion"] = {"truncated": truncated, "stages": stages,
            "reason": "token_budget" if truncated is True else "model_stop" if truncated is False else "unknown",
            "timing_is_exact": result.get("conditioning", {}).get("timing_is_exact", False)}
        output["metrics"]["desktop_elapsed_seconds"] = time.monotonic() - started
        client.atomic_json(directory / "result.json", output)
        progress("ready", 1.)
        return output
    finally:
        tunnel.close()
