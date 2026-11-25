#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][switch]$ApprovedApiCall,
    [Parameter(Mandatory)][string]$PythonExe,
    [string]$CheckpointDir = '.kmas-checkpoint',
    [ValidatePattern('^[A-Za-z0-9_-]{1,40}$')][string]$CheckpointBatch = 'default',
    [ValidateRange(1, 1000)][int]$MaxRequests = 100,
    [ValidateRange(1, 1000)][int]$DailyLimit = 1000,
    [switch]$CatalogScan,
    [switch]$PrepareDatabase,
    [switch]$IncludeSynopsis,
    [switch]$IncludeCoverSource
)
$ErrorActionPreference = 'Stop'
if (-not $ApprovedApiCall) { throw 'Explicit API approval is required.' }
$project = Split-Path -Parent $PSScriptRoot
$checkpoint = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($CheckpointDir)
[void][IO.Directory]::CreateDirectory($checkpoint)
$stamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
$resolution = Join-Path $checkpoint "resolution-$stamp.csv"
$stage = Join-Path $checkpoint "stage-$stamp.json"
$review = Join-Path $checkpoint "dryrun-$stamp.json"
$backup = Join-Path $checkpoint "review-backup-$stamp.json"
if (-not (Get-Command $PythonExe -ErrorAction SilentlyContinue)) { throw 'Python executable was not found.' }

$result = & (Join-Path $PSScriptRoot 'resolve_kmas_ids.ps1') -Live `
    -InputCsv (Join-Path $project 'kmas_import_readiness_20261124_003620_c6277259.csv') `
    -OutputCsv $resolution -CheckpointDir $checkpoint -CheckpointBatch $CheckpointBatch -IncludeReviewedCatalog -CatalogScan:$CatalogScan `
    -MaxRequests $MaxRequests -DailyLimit $DailyLimit -IncludeSynopsis:$IncludeSynopsis `
    -IncludeCoverSource:$IncludeCoverSource
$result
if ($result.Pending -gt 0) { return }

Push-Location $project
try {
    & $PythonExe -m kmas_staging_import Stage --resolution $resolution --report $stage
    if ($LASTEXITCODE -ne 0) { throw 'Stage failed.' }
    $staged = Get-Content -LiteralPath $stage -Raw -Encoding UTF8 | ConvertFrom-Json
    [pscustomobject]@{ StageReport = $stage; Candidates = $staged.verified_import_candidates }
    if (-not $PrepareDatabase -or -not $staged.verified_import_candidates) { return }
    & $PythonExe -m kmas_staging_import DryRun --resolution $resolution --report $review
    if ($LASTEXITCODE -ne 0) { throw 'DryRun failed.' }
    [pscustomobject]@{ DryRunReport = $review }
    & $PythonExe -m kmas_staging_import ReviewBackup --resolution $resolution --report $review --backup $backup
    if ($LASTEXITCODE -ne 0) { throw 'Review backup failed. Inspect the DryRun report.' }
    [pscustomobject]@{ VerifiedReviewBackup = $backup }
} finally { Pop-Location }
