param([string]$DawExe = "")
$ErrorActionPreference = 'Stop'
$agentRoot = Split-Path -Parent $PSScriptRoot
$agentRunner = Join-Path $PSScriptRoot 'dev_agent.py'
if (-not $DawExe) { $DawExe = Join-Path $agentRoot 'build\agent-batch2\bin\Release\E-musician.exe' }
if (-not (Test-Path -LiteralPath $DawExe -PathType Leaf)) { throw 'Embedded DAW executable missing. Run python scripts/dev_agent.py build first.' }
$agentPython = (Get-Command python -ErrorAction Stop).Source
$agentArguments = '"{0}" run --exe "{1}"' -f $agentRunner, $DawExe
Start-Process -FilePath $agentPython -ArgumentList $agentArguments -WorkingDirectory $agentRoot -WindowStyle Hidden
