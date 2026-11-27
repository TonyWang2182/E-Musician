# Cloud model deployment tools

These tools prepare and inspect the model environments used by the compute
service. See [Models](../../../docs/MODELS.md#deploy-a-server) for server setup
and [Configuration](../../../docs/CONFIGURATION.md#ssh-compute-server) for
connecting the desktop.

- `yue2/`: YuE2 source, 3B/VAE checkpoints and its isolated inference environment.
- `mir_upgrades/`: independent SCNet, TransKun and ChordMini environments.
- `scores/`: SheetSage2/MERT2 and MuScriptor deployment/access checks.
- `muscriptor_authorized/`: authorized medium-model downloads and CPU/GPU probes.
- `library_status.py`: read-only aggregation of per-model deployment records.

Each model records its hashes, environment checks and inference results in
`manifests/model-library/<id>/deployment.json`. Stage these scripts under
`tools/models/`; the separate service installer owns `tools/compute` and
`tools/compute_start.py`. Model weights and credentials remain outside the
source repository; see [Model assets](../../../docs/MODEL-ASSETS.md).
