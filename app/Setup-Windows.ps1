param([switch]$Reinstall)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$runtimeRoot = Join-Path $PSScriptRoot '.runtime'
$archive = Join-Path $runtimeRoot 'python-3.14.6.zip'
$pythonRoot = Join-Path $runtimeRoot 'python-3.14.6'
$python = Join-Path $pythonRoot 'tools\python.exe'
$expectedHash = '77271b5958f88608884998c27df6f8dd2fa59faf72614bc1e2ffd1d72a3336c3'
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $archive)) {
    Write-Host 'Downloading official CPython 3.14.6 (Windows x64) from NuGet...'
    $download = Join-Path $runtimeRoot 'python-3.14.6.download'
    $url = 'https://api.nuget.org/v3-flatcontainer/python/3.14.6/python.3.14.6.nupkg'
    $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
    if (Test-Path -LiteralPath $curl) {
        & $curl --fail --location --silent --show-error --output $download $url
        if ($LASTEXITCODE -ne 0) { throw 'Python download failed. Retry setup.' }
    } else {
        $client = New-Object System.Net.WebClient
        try { $client.DownloadFile($url, $download) } finally { $client.Dispose() }
    }
    if ((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
        throw 'Downloaded Python checksum mismatch. Retry setup.'
    }
    Move-Item -LiteralPath $download -Destination $archive
}
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
    throw 'Python archive checksum mismatch. Use a fresh app folder and retry.'
}
if ($Reinstall -or -not (Test-Path -LiteralPath $python)) {
    Expand-Archive -LiteralPath $archive -DestinationPath $pythonRoot -Force
}
$setup = Join-Path $PSScriptRoot 'scripts\setup_windows.py'
if ($Reinstall) { & $python $setup --reinstall } else { & $python $setup }
if ($LASTEXITCODE -ne 0) { throw 'Environment setup failed. See the error above.' }
Write-Host 'Ready. Run Start-COSLab.bat or .venv-desktop\Scripts\python.exe scripts\verify_source.py.'
