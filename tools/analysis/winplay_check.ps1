# Plays a video through Windows' own media pipeline (the one Windows Media Player style apps use), muted, and reports stalls.
# usage (Windows PowerShell 5.1): powershell -File winplay_check.ps1 "C:\full\path\movie.mp4" [seconds]
param([string]$Path, [int]$Seconds = 12)
[void][Windows.Media.Playback.MediaPlayer, Windows.Media, ContentType=WindowsRuntime]
[void][Windows.Media.Core.MediaSource, Windows.Media, ContentType=WindowsRuntime]
$uri = New-Object System.Uri((Resolve-Path $Path).Path)
$mp = New-Object Windows.Media.Playback.MediaPlayer
$mp.IsMuted = $true
$failed = $null
Register-ObjectEvent -InputObject $mp -EventName MediaFailed -Action { $global:failed = $EventArgs.ErrorMessage } | Out-Null
$mp.Source = [Windows.Media.Core.MediaSource]::CreateFromUri($uri)
$mp.Play()
$sw = [Diagnostics.Stopwatch]::StartNew()
$last = 0.0; $lastT = 0.0; $stalls = @(); $samples = 0
while ($sw.Elapsed.TotalSeconds -lt $Seconds) {
    Start-Sleep -Milliseconds 100
    $pos = $mp.PlaybackSession.Position.TotalSeconds
    $t = $sw.Elapsed.TotalSeconds
    $samples++
    if ($t - $lastT -ge 0.5) {
        $moved = $pos - $last
        if ($t -gt 1.5 -and $moved -lt 0.25) { $stalls += ("at {0:N1}s: position moved only {1:N2}s in 0.5s (state {2})" -f $t, $moved, $mp.PlaybackSession.PlaybackState) }
        $last = $pos; $lastT = $t
    }
}
$dur = $mp.PlaybackSession.NaturalDuration.TotalSeconds
"duration reported: {0:N2}s   position after {1}s: {2:N2}s   state: {3}" -f $dur, $Seconds, $mp.PlaybackSession.Position.TotalSeconds, $mp.PlaybackSession.PlaybackState
if ($failed) { "FAILED: $failed" }
if ($stalls.Count) { "stalls: $($stalls.Count)"; $stalls | Select-Object -First 8 } else { "no stalls" }
$mp.Dispose()
