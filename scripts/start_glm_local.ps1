# Optional isolated local benchmark server; never registered for startup.
$ErrorActionPreference = 'Stop'
$glmRoot = Join-Path (Split-Path $PSScriptRoot -Parent) 'artifacts\glm-runtime'
$glmExe = Join-Path $glmRoot 'ollama\ollama.exe'
if (-not (Test-Path -LiteralPath $glmExe)) { throw 'Local benchmark runtime is not downloaded.' }
if (Get-NetTCPConnection -LocalPort 11439 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 11439 is already in use. Reuse the existing benchmark server if appropriate.'
}
$env:OLLAMA_HOST = '127.0.0.1:11439'
$env:OLLAMA_MODELS = Join-Path $glmRoot 'models'
$env:OLLAMA_NO_CLOUD = '1'
$glmProcess = Start-Process -FilePath $glmExe -ArgumentList 'serve' -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $glmRoot 'server.out.log') -RedirectStandardError (Join-Path $glmRoot 'server.err.log')
$glmProcess.Id | Set-Content (Join-Path $glmRoot 'server.pid')
Write-Output "Local benchmark server PID: $($glmProcess.Id), port: 11439"
