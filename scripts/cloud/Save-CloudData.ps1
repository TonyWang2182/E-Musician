param([Parameter(Mandatory=$true)][string]$SshAlias, [string]$DestinationRoot = (Join-Path $env:LOCALAPPDATA 'E-musician\cloud-inference'))
$ErrorActionPreference = 'Stop'
if ($SshAlias -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid SSH alias' }
$dataRoot = [IO.Path]::GetFullPath($DestinationRoot)
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
$backupDir = Join-Path $dataRoot ('backups\' + $stamp)
New-Item -ItemType Directory -Path $backupDir -ErrorAction Stop | Out-Null

Write-Host 'Creating cloud data archive. Run only after tasks have finished.'
$reply = & ssh.exe -o BatchMode=yes -o StrictHostKeyChecking=yes $SshAlias '/root/miniconda3/bin/python /root/autodl-tmp/emusician/tools/backup_data.py'
if ($LASTEXITCODE -ne 0) { throw 'Cloud archive creation failed; no verified local backup was published.' }
$receipt = ($reply -join "`n") | ConvertFrom-Json
if ($receipt.archive -notmatch '^emusician-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\.tar\.gz$') { throw 'Invalid archive name' }
if ($receipt.sha256 -notmatch '^[0-9a-f]{64}$') { throw 'Invalid archive checksum' }
$pending = Join-Path $backupDir ($receipt.archive + '.partial')
$remoteFile = "${SshAlias}:/root/autodl-tmp/emusician/exports/$($receipt.archive)"
& scp.exe -o BatchMode=yes -o StrictHostKeyChecking=yes $remoteFile $pending
if ($LASTEXITCODE -ne 0) { throw 'Download failed; partial file retained and is not a verified backup.' }
if ((Get-Item -LiteralPath $pending).Length -ne [long]$receipt.size) { throw 'Archive size mismatch' }
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $pending).Hash -ine $receipt.sha256) { throw 'Archive checksum mismatch' }

$final = Join-Path $backupDir $receipt.archive
Move-Item -LiteralPath $pending -Destination $final -ErrorAction Stop
$receipt | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $backupDir 'receipt.json')
Write-Host ('Verified backup saved to: ' + $final)
Write-Host 'Archive retained on cloud; this command does not shut down or release the instance.'
