$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$contentLabRoot = Join-Path $projectRoot 'contentlab'
$dotenvPath = Join-Path $projectRoot '.env'
$logsPath = Join-Path $projectRoot 'logs'
$python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
}
if (-not $python -or -not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Python 3.14 was not found.' }
if (-not (Test-Path -LiteralPath $dotenvPath -PathType Leaf)) { throw 'Project .env was not found.' }
New-Item -ItemType Directory -Force -Path $logsPath | Out-Null

# Parse the existing dotenv file in this script so PowerShell does not re-quote inline Python.
# Values stay in process memory and are never printed or written to a log.
$environment = @{}
foreach ($line in [IO.File]::ReadAllLines($dotenvPath, [Text.Encoding]::UTF8)) {
    if ($line -match '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
        $name = $Matches[1]
        $value = $Matches[2].Trim()
        if ($value.Length -ge 2 -and $value.StartsWith('"') -and $value.EndsWith('"')) {
            $value = $value.Substring(1, $value.Length - 2)
            $value = $value.Replace('\n', "`n").Replace('\r', "`r").Replace('\t', "`t").Replace('\"', '"').Replace('\\', '\')
        } elseif ($value.Length -ge 2 -and $value.StartsWith("'") -and $value.EndsWith("'")) {
            $value = $value.Substring(1, $value.Length - 2)
        } else {
            $value = ($value -replace '\s+#.*$', '').Trim()
        }
        $environment[$name] = $value
    }
}
foreach ($name in $environment.Keys) {
    [Environment]::SetEnvironmentVariable($name, [string]$environment[$name], 'Process')
}
if (-not $env:JWT_SECRET -or -not $env:DB_PASSWORD) {
    throw 'JWT_SECRET and DB_PASSWORD must be configured in the local environment.'
}

$mavenRepo = (Join-Path $projectRoot '.maven-cache').Replace('\', '/')
$repoOption = "-Dmaven.repo.local=$mavenRepo"
$existingMavenOpts = [string]$env:MAVEN_OPTS
$env:MAVEN_OPTS = (($existingMavenOpts + ' ' + $repoOption).Trim())
$springLog = Join-Path $logsPath 'spring-local.log'
$fastApiOut = Join-Path $logsPath 'fastapi-local.out.log'
$fastApiErr = Join-Path $logsPath 'fastapi-local.err.log'

$fastApiHealthy = $false
try {
    $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 3
    $fastApiHealthy = $response.StatusCode -eq 200
} catch { }
if (-not $fastApiHealthy) {
    $apiListener = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue
    if ($apiListener) { throw 'Port 8000 is occupied by a process that does not pass the FastAPI health check.' }
    Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','ai_server:app','--host','127.0.0.1','--port','8000','--env-file',$dotenvPath) `
        -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $fastApiOut -RedirectStandardError $fastApiErr | Out-Null
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $fastApiHealthy = $true; break }
        } catch { }
    }
    if (-not $fastApiHealthy) { throw "FastAPI did not become healthy. See $fastApiErr" }
}

$springHealthy = $false
try {
    $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/api/health' -UseBasicParsing -TimeoutSec 3
    $springHealthy = $response.StatusCode -eq 200
} catch { }
if ($springHealthy) {
    Write-Output 'Spring Boot and FastAPI are already healthy; no duplicate server was started.'
    exit 0
}
$springListener = Get-NetTCPConnection -State Listen -LocalPort 8080 -ErrorAction SilentlyContinue
if ($springListener) { throw 'Port 8080 is occupied by a process that does not pass the Spring health check.' }

$mavenWrapper = Join-Path $contentLabRoot 'mvnw.cmd'
if (-not (Test-Path -LiteralPath $mavenWrapper -PathType Leaf)) { throw 'Maven wrapper was not found under contentlab.' }
Push-Location $contentLabRoot
try {
    # Start Spring directly through the project wrapper; use the same project-local cache as tests.
    & $mavenWrapper $repoOption 'spring-boot:run' *> $springLog
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($exitCode -ne 0) { throw "Spring Boot exited with code $exitCode. See $springLog" }
