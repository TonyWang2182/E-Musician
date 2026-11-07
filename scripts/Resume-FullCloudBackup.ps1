param(
    [string]$BackupId = 'full-20261107T080330Z'
)
$ErrorActionPreference = 'Stop'
if ($BackupId -notmatch '^full-[0-9]{8}T[0-9]{6}Z$') { throw 'Unexpected backup identifier' }
$repoDirectory = Split-Path -Parent $PSScriptRoot
$backupDirectory = Join-Path 'E:\MusicAgent&DAW\cloud-inference\backups' $BackupId
$sourceFile = Join-Path $backupDirectory 'source.json'
$identity = Get-Content -LiteralPath $sourceFile -Raw | ConvertFrom-Json
if ($identity.host -ne 'emusician-autodl' -or $identity.remote_root -ne "/root/autodl-tmp/emusician/exports/$BackupId") {
    throw 'Backup identity does not match the approved source'
}
$active = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and $_.CommandLine -like '*pull_full_backup.py pull*' -and $_.CommandLine -like "*$BackupId*"
})
if ($active.Count -gt 0) {
    Write-Output 'This backup already has a running downloader. See progress.json.'
    exit 0
}
$stamp = Get-Date -Format 'yyyyMMddTHHmmss'
$logDirectory = Join-Path $repoDirectory 'build-logs'
$stdout = Join-Path $logDirectory "full-backup-$stamp.stdout.log"
$stderr = Join-Path $logDirectory "full-backup-$stamp.stderr.log"
$arguments = @('scripts/dev_compute.py', 'command', 'C:/Python314/python.exe',
    'scripts/cloud/pull_full_backup.py', 'pull', '--host', 'emusician-autodl',
    '--remote-root', $identity.remote_root, '--destination', ('"' + $backupDirectory + '"'),
    '--direct-file', '--workers', '4')
$process = Start-Process -FilePath 'C:\Python314\python.exe' -ArgumentList $arguments -WorkingDirectory $repoDirectory `
    -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
@{ pid = $process.Id; started = (Get-Date).ToUniversalTime().ToString('o'); backup_id = $BackupId;
   stdout = $stdout; stderr = $stderr; state = 'launched-not-yet-verified' } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backupDirectory 'background-process.json') -Encoding UTF8
Write-Output "Backup downloader started in the background (PID $($process.Id)). See progress.json; only verification.json proves completion."
