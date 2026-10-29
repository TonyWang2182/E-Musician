param([string]$DawExe = "")
$ErrorActionPreference = 'Stop'
$agentRoot = Split-Path -Parent $PSScriptRoot
$agentRunner = Join-Path $PSScriptRoot 'run_agent.py'
if (-not $DawExe) { $DawExe = Join-Path $agentRoot 'build\bin\Release\E-musician.exe' }
if (-not (Test-Path -LiteralPath $DawExe -PathType Leaf)) { throw 'DAW executable missing. Use -DawExe PATH or build the Release executable first.' }
$agentPython = (Get-Command python -ErrorAction Stop).Source
$agentArguments = '"{0}" --exe "{1}"' -f $agentRunner, $DawExe
Start-Process -FilePath $agentPython -ArgumentList $agentArguments -WorkingDirectory $agentRoot -WindowStyle Hidden
