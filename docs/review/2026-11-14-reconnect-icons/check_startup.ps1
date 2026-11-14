$ErrorActionPreference = 'Stop'
$taskPid = 7052
$taskProcess = Get-Process -Id $taskPid
$taskChildren = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $taskPid")
$taskHelpers = @($taskChildren | Where-Object { $_.CommandLine -match 'run_agent\.py.*--embedded-session' })
$taskConnections = @(Get-NetTCPConnection -OwningProcess $taskPid -ErrorAction SilentlyContinue)
$taskSessions = @()
foreach ($taskHelper in $taskHelpers) {
    if ($taskHelper.CommandLine -match '--embedded-session\s+"?([^"\r\n]+?\.json)"?(?:\s|$)') {
        $taskSessionPath = $matches[1]
        $taskSession = Get-Content -LiteralPath $taskSessionPath -Raw | ConvertFrom-Json
        $taskSessions += [ordered]@{
            helper_pid = $taskHelper.ProcessId
            session_exists = $true
            readiness_file_consumed = -not (Test-Path -LiteralPath $taskSession.ready_path)
            native_authenticated_connection_live = @($taskConnections | Where-Object {
                $_.LocalAddress -eq '127.0.0.1' -and $_.LocalPort -eq $taskSession.port -and $_.State -eq 'Established'
            }).Count -gt 0
        }
    }
}
$taskReport = [ordered]@{
    checked_at = (Get-Date).ToUniversalTime().ToString('o')
    pid = $taskPid
    executable = $taskProcess.Path
    window_title = $taskProcess.MainWindowTitle
    responding = $taskProcess.Responding
    agent_helpers = $taskSessions
    audio_or_model_inference_tested = $false
    page_pixels_inspected = $false
}
if (-not $taskReport.responding -or $taskReport.window_title -notmatch '0\.13\.3') { throw 'Final candidate window unavailable' }
if ($taskSessions.Count -ne 1 -or -not $taskSessions[0].readiness_file_consumed -or -not $taskSessions[0].native_authenticated_connection_live) { throw 'Agent native/helper handshake not confirmed' }
$taskReport | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath 'docs/review/2026-11-14-reconnect-icons/STARTUP.json' -Encoding utf8
$taskReport | ConvertTo-Json -Depth 5
