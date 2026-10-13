param([Parameter(Mandatory=$true)][string]$Release,[Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$releaseRoot = (Resolve-Path -LiteralPath $Release).Path
$meta = Get-Content -LiteralPath (Join-Path $releaseRoot 'metadata.json') -Raw | ConvertFrom-Json
if ($meta.status -ne 'experimental' -or $meta.approval -ne 'pending_human') { throw 'Expected an unapproved trial' }
if ((Get-FileHash -LiteralPath (Join-Path $releaseRoot 'model.tflite') -Algorithm SHA256).Hash.ToLower() -ne $meta.sha256) { throw 'Model changed' }
$outputRoot = [IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath $outputRoot) { throw 'Preserve existing trial output' }
New-Item -ItemType Directory -Path $outputRoot | Out-Null
$backup = Join-Path $outputRoot 'approved-assets-backup'
New-Item -ItemType Directory -Path $backup | Out-Null
$assets = Join-Path $projectRoot 'android/app/src/main/assets/models'
$names = @('model.tflite','metadata.json','labels.txt','scope-policy.json')
$existed = @{}
foreach ($name in $names) {
    $path = Join-Path $assets $name
    $existed[$name] = Test-Path -LiteralPath $path
    if ($existed[$name]) { Copy-Item -LiteralPath $path -Destination (Join-Path $backup $name) }
}
$mapped = $false
try {
    foreach ($name in $names) { Copy-Item -LiteralPath (Join-Path $releaseRoot $name) -Destination (Join-Path $assets $name) }
    $env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
    if (Test-Path R:\) { throw 'R drive already in use' }
    subst R: $projectRoot
    if ($LASTEXITCODE) { throw 'Mapping failed' }
    $mapped = $true
    & R:\android\gradlew.bat -p R:\android :app:assembleDebug --console=plain
    if ($LASTEXITCODE) { throw 'Trial build failed' }
    $apk = Join-Path $outputRoot 'campus-recognition-1.0-v3-trial.apk'
    Copy-Item -LiteralPath (Join-Path $projectRoot 'android/app/build/outputs/apk/debug/app-debug.apk') -Destination $apk
    $hash = (Get-FileHash -LiteralPath $apk -Algorithm SHA256).Hash.ToLower()
    [IO.File]::WriteAllText((Join-Path $outputRoot 'trial.json'), (@{status='experimental';model_version=$meta.model_version;model_sha256=$meta.sha256;apk_sha256=$hash;installed=$false} | ConvertTo-Json)+"`n",[Text.UTF8Encoding]::new($false))
} finally {
    if ($mapped) { subst R: /D }
    foreach ($name in $names) {
        $path = Join-Path $assets $name
        if ($existed[$name]) { Copy-Item -LiteralPath (Join-Path $backup $name) -Destination $path }
        elseif (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
    }
}
Write-Output 'Trial APK saved; approved source assets restored.'
