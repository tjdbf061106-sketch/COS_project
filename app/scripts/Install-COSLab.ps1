param(
    [string]$InstallDirectory = (Join-Path $env:LOCALAPPDATA 'Programs\COSLab'),
    [string]$ShortcutDirectory = ([Environment]::GetFolderPath('Desktop'))
)
$ErrorActionPreference = 'Stop'
$sourceRoot = $PSScriptRoot
$installRoot = [System.IO.Path]::GetFullPath($InstallDirectory)
if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot 'COSLab.exe'))) {
    throw 'COSLab.exe must be in the same folder as this installer.'
}
$sourceResolved = [System.IO.Path]::GetFullPath($sourceRoot)
$targetResolved = [System.IO.Path]::GetFullPath($installRoot)
if ($sourceResolved -eq $targetResolved -or
    $targetResolved.StartsWith($sourceResolved.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase) -or
    $sourceResolved.StartsWith($targetResolved.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'The extracted release folder and installation folder must be separate.'
}
if (Get-Process -Name COSLab -ErrorAction SilentlyContinue) {
    throw 'Please close COS Lab before installing or updating.'
}
New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
foreach ($entry in Get-ChildItem -LiteralPath $sourceRoot -Force) {
    Copy-Item -LiteralPath $entry.FullName -Destination $installRoot -Recurse -Force
}
$desktopPath = [System.IO.Path]::GetFullPath($ShortcutDirectory)
New-Item -ItemType Directory -Path $desktopPath -Force | Out-Null
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $desktopPath 'COS Lab.lnk'))
$shortcut.TargetPath = Join-Path $installRoot 'COSLab.exe'
$shortcut.WorkingDirectory = $installRoot
$shortcut.Description = 'COS Lab - Skin and eye irritation research'
$shortcut.Save()
Write-Host 'COS Lab installed. Open the COS Lab shortcut on your desktop.'
