# Run once from an Administrator PowerShell. Does not reboot automatically.
$ErrorActionPreference = 'Stop'
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Open Windows Terminal as Administrator, then run this script again.'
}
$taskRepo = Split-Path -Parent $PSScriptRoot
$taskLogDir = Join-Path $taskRepo 'experiments/reports/environment'
New-Item -ItemType Directory -Path $taskLogDir -Force | Out-Null
Start-Transcript -Path (Join-Path $taskLogDir 'wsl-admin-install.log') -Append
try {
    & dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
    if ($LASTEXITCODE -notin @(0,3010)) { throw "WSL feature failed: $LASTEXITCODE" }
    & dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
    if ($LASTEXITCODE -notin @(0,3010)) { throw "VirtualMachinePlatform failed: $LASTEXITCODE" }
    Write-Host 'Components enabled. Save your work and restart Windows when requested.'
    Write-Host 'After restarting: wsl --update'
    Write-Host 'Then: wsl --install -d Ubuntu-24.04 --no-launch'
    Write-Host 'Then launch: wsl -d Ubuntu-24.04 ; create your Linux user/password there.'
} finally {
    Stop-Transcript
}
