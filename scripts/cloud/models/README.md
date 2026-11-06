# Cloud model deployment tools

These tools install and inspect versioned cloud model environments. They do not
implement DAW Providers or activate the production generation gateway.

- `yue2/`: YuE2 source, 3B/VAE checkpoints and its isolated inference environment.
- `mir_upgrades/`: independent SCNet, TransKun and ChordMini environments.
- `scores/`: SheetSage2/MERT2 and MuScriptor deployment/access checks.
- `muscriptor_authorized/`: pinned medium authorization, official-source RAM relay, offline CPU/GPU probes and evidence finalizer. Credentials never belong in this repository.
- `library_status.py`: read-only aggregation of per-model deployment records.

Each model owns `/root/autodl-tmp/emusician/manifests/model-library/<id>/deployment.json`.
Keep artifact integrity, environment installation, CPU loading, GPU inference,
quality evaluation and DAW integration as separate facts. Never infer a missing
check from a successful earlier step. Run GPU checks serially under the root
operator's control; the existing ACE service has its own queue and is not yet a
shared all-model scheduler.

Checkpoint downloads and generated audio stay on the cloud instance for this
batch. Only scripts, locks, small manifests and log summaries return to the local
repository. See the [deployment plan](../../../docs/review/2026-11-06-cloud-model-library/PLAN.md).
