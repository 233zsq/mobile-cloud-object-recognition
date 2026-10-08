# Administrator step after system components are enabled. Never restarts or launches Linux.
$ErrorActionPreference = 'Stop'
$taskPrincipal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script from an Administrator PowerShell.'
}
$taskRepo = Split-Path -Parent $PSScriptRoot
$taskReportDir = Join-Path $taskRepo 'experiments/reports/environment'
New-Item -ItemType Directory -Path $taskReportDir -Force | Out-Null
Start-Transcript -Path (Join-Path $taskReportDir 'wsl-ubuntu-install.log') -Append
try {
    $taskFeatureStates = @(Get-WindowsOptionalFeature -Online | Where-Object FeatureName -in @('Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform') | Select-Object FeatureName,State)
    & wsl.exe --install -d Ubuntu-24.04 --no-launch | Out-Host
    $taskInstallExit = $LASTEXITCODE
    $taskRecord = @{
        at = (Get-Date).ToString('o')
        requested_distribution = 'Ubuntu-24.04'
        command = 'wsl --install -d Ubuntu-24.04 --no-launch'
        exit_code = $taskInstallExit
        feature_states = $taskFeatureStates
        automatic_restart = $false
        linux_user_created = $false
        gpu_validated = $false
        status = if ($taskInstallExit -in @(0,3010)) { 'installer_completed_check_after_restart' } else { 'installer_failed_or_restart_required_read_log' }
    }
    $taskRecord | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $taskReportDir 'wsl-ubuntu-install.json') -Encoding utf8
    if ($taskInstallExit -notin @(0,3010)) { throw "WSL installer exit code: $taskInstallExit. See transcript; no GPU validation is claimed." }
    Write-Host 'Installer completed. Save work, restart when requested, then check wsl --status and wsl -l -v.'
    Write-Host 'Create your own Linux account using wsl -d Ubuntu-24.04; keep the password outside chat.'
} finally {
    Stop-Transcript
}
