# Configuration

Recording, editing, plugins and export work without an account. Configure the
Agent, local analysis or cloud models when you want to use them.

## Python and data folders

Install Windows x64 Python 3.10 or newer. Keep `runtime/scripts` beside
`E-musician.exe` in an extracted release. The Agent uses Python's standard library.

Python is resolved from `EMUSICIAN_PYTHON`, `runtime/python/python.exe`, then
`python.exe` on PATH. Source builds also try their configured interpreter.
To select an interpreter explicitly:

```powershell
$env:EMUSICIAN_PYTHON = 'C:\Python312\python.exe'
& '.\E-musician.exe'
```

| Variable | Windows default | Contents |
| --- | --- | --- |
| `EMUSICIAN_ANALYSIS_ROOT` | `%LOCALAPPDATA%\E-musician\analysis` | Local environments, weights and analysis results |
| `EMUSICIAN_COMPUTE_ROOT` | `%LOCALAPPDATA%\E-musician\cloud-inference` | SSH registration and task records |
| `EMUSICIAN_GENERATION_ROOT` | `%LOCALAPPDATA%\E-musician\cloud-inference` | Generation results and legacy registration |
| `EMUSICIAN_AUDIO_CACHE_ROOT` | Engine-managed per-user cache | Decoded audio cache |

Overrides must be absolute paths. Set both compute and generation roots when
moving cloud task storage, then restart the application. Existing files are not
moved automatically.

Commands below run from the source root. In an extracted release, replace
`scripts/` with `runtime/scripts/`.

## Agent API

Open **Agent** (Ctrl+Shift+A), click the model name to expand **Model settings**,
choose **Kimi** or **OpenAI**, and save your API key and model. Defaults are Kimi
`kimi-k2.6` and OpenAI `gpt-5-mini` with medium reasoning effort. The adapters use
`https://api.moonshot.cn/v1` and `https://api.openai.com/v1`; other providers and
custom endpoints are not supported.

You can also save a key through a hidden console prompt:

```powershell
python scripts/run_agent.py --provider kimi --configure-key
python scripts/run_agent.py --provider openai --configure-key
```

Keys are encrypted for the current Windows user in
`%LOCALAPPDATA%\E-musician\agent\moonshot.key` and `openai.key`; preferences are
in `settings.json`. Configure keys separately on each machine. `MOONSHOT_API_KEY`
and `OPENAI_API_KEY` are used only when the corresponding saved key file is
absent. An unreadable saved key reports an error instead of using the environment.

## Local analysis

Install `uv`, then choose the workers you need:

```powershell
python scripts/setup_analysis.py --kind chords
python scripts/setup_analysis.py --kind transcribe
python scripts/setup_analysis.py --kind beats
python scripts/setup_analysis.py --kind separate
```

Setup creates isolated Python 3.10.19 environments, downloads dependencies and
weights, then probes and registers each worker. Available options:

- `--kind all`: install all four workers.
- `--device cuda`: use CUDA for separation and beats; requires a compatible NVIDIA driver.
- `--kind separate --stems 6`: add six-stem separation.
- `--register-only`: register already installed environments.
- `--root C:\E-musician-data\analysis`: use another folder; set
  `EMUSICIAN_ANALYSIS_ROOT` to that same path before launching the DAW.

See [Models](MODELS.md) for supported results and limitations.

## SSH compute server

Cloud music generation and analysis need your own Linux NVIDIA server running
E-musician compute protocol 2. Set up its models and service using
[the server deployment instructions](MODELS.md#deploy-a-server), then connect it
to the desktop. An Agent API key does not supply this server.

1. Install Windows OpenSSH Client, authorize your public key on the server, and
   add your connection to `%USERPROFILE%\.ssh\config`:

   ```sshconfig
   Host emusician-cloud
       HostName YOUR_SERVER_HOST
       Port YOUR_SSH_PORT
       User YOUR_SERVER_USER
       IdentityFile C:/Users/YOUR_USER/.ssh/id_ed25519
       IdentitiesOnly yes
       StrictHostKeyChecking yes
   ```

2. Confirm the host-key fingerprint with your server administrator, then connect:

   ```powershell
   ssh -o StrictHostKeyChecking=ask emusician-cloud exit
   ```

   Use an SSH agent for passphrase-protected keys; the app connects in batch mode.

3. Create the local audio helper environment:

   ```powershell
   py -3.10 -m venv "$env:LOCALAPPDATA\E-musician\cloud-audio"
   & "$env:LOCALAPPDATA\E-musician\cloud-audio\Scripts\python.exe" -m pip install numpy==1.26.4 scipy==1.13.1 soundfile==0.13.1
   ```

4. Register the prepared server:

   ```powershell
   python scripts/cloud/register_compute.py --ssh-alias emusician-cloud --register --python "$env:LOCALAPPDATA\E-musician\cloud-audio\Scripts\python.exe"
   ```

Registration starts the service if needed, checks capabilities and writes
`compute-registry.json`. Use `--no-start-service` when a separate supervisor
already manages the service. `--root` must match `EMUSICIAN_COMPUTE_ROOT`.

Defaults are remote loopback port `18082`, deployment root
`/root/autodl-tmp/emusician` and Python `/root/miniconda3/bin/python`.
`--remote-port` selects the service port, not the SSH port. `--remote-root` and
`--remote-python` select the service starter; they do not relocate model
environments. Keep HTTP bound to `127.0.0.1`; the desktop reaches it through SSH.

In **Analyze**, choose Local, Cloud or Auto and an available model. Generated and
analyzed results remain candidates until you accept them; accepted assets are
saved locally and can be reopened offline.

Keep credentials, registries, user media and model environments out of source
releases. See [Model assets](MODEL-ASSETS.md) before sharing a model archive.