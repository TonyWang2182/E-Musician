param(
    [string]$Executable = 'E:/emusician-analysis-build/bin-0.13.3/Release/E-musician.exe',
    [string]$Output = 'E:/MusicAgent&DAW/worktrees/audio-analysis/build/reconnect-icons/exe-icon-index-0.png'
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class EMusicianIconAudit {
    [DllImport("shell32.dll", CharSet=CharSet.Unicode)]
    public static extern uint ExtractIconEx(string file, int index, out IntPtr large, out IntPtr small, uint count);
    [DllImport("user32.dll")]
    public static extern bool DestroyIcon(IntPtr icon);
}
'@
$largeIcon = [IntPtr]::Zero
$smallIcon = [IntPtr]::Zero
$resolvedExe = (Resolve-Path -LiteralPath $Executable).Path
$count = [EMusicianIconAudit]::ExtractIconEx($resolvedExe, 0, [ref]$largeIcon, [ref]$smallIcon, 1)
if ($count -lt 1 -or $largeIcon -eq [IntPtr]::Zero) { throw "Unable to extract EXE icon group 0 (returned=$count)." }
$icon = $null
$bitmap = $null
try {
    $icon = [System.Drawing.Icon]::FromHandle($largeIcon)
    $bitmap = $icon.ToBitmap()
    $bitmap.Save($Output, [System.Drawing.Imaging.ImageFormat]::Png)
    [ordered]@{ executable=$resolvedExe; icon_index=0; extracted_icon_count=$count; width=$bitmap.Width; height=$bitmap.Height; output=$Output; sha256=(Get-FileHash -LiteralPath $Output -Algorithm SHA256).Hash } | ConvertTo-Json
} finally {
    if ($null -ne $bitmap) { $bitmap.Dispose() }
    if ($null -ne $icon) { $icon.Dispose() }
    if ($largeIcon -ne [IntPtr]::Zero) { [void][EMusicianIconAudit]::DestroyIcon($largeIcon) }
    if ($smallIcon -ne [IntPtr]::Zero -and $smallIcon -ne $largeIcon) { [void][EMusicianIconAudit]::DestroyIcon($smallIcon) }
}
