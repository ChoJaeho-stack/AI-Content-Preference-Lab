#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'kmas_collection_checkpoint.ps1')
$scratch = Join-Path ([IO.Path]::GetTempPath()) "kmas-collection-test-$([Guid]::NewGuid())"
[void][IO.Directory]::CreateDirectory($scratch)
$originalKey = $env:KMAS_API_KEY
$originalUrl = $env:KMAS_API_BASE_URL
$fixtureState = @{ calls = 0; platform = (-join [char[]]@(45348,51060,48260,50937,53808)) }
function Start-Sleep { param([int]$Seconds) }
function Invoke-RestMethod {
    param($Method, $Uri, $TimeoutSec, $MaximumRedirection, $Headers, [switch]$Verbose, [switch]$Debug)
    $fixtureState.calls++
    if ($fixtureState.calls -eq 1) { throw [TimeoutException]::new('fake timeout with sensitive context') }
    $title = [Uri]::UnescapeDataString(([regex]::Match($Uri, '[&?]title=([^&]+)').Groups[1].Value))
    [pscustomobject]@{
        result = [pscustomobject]@{ resultState = 'success'; totalCount = 1 }
        itemList = @([pscustomobject]@{
            prdctNm = $title; listSeCd = '1'; mastrId = 'fixture-same-id'
            pltfomCdNm = $fixtureState.platform; sntncWritrNm = 'Fixture Author'
        })
    }
}
function Assert-Equal($Actual, $Expected, [string]$Label) {
    if ($Actual -cne $Expected) { throw "Failed: $Label (expected $Expected; got $Actual)" }
}
try {
    $resolver = Join-Path $PSScriptRoot 'resolve_kmas_ids.ps1'
    $env:KMAS_API_KEY = 'fixture-key'
    $env:KMAS_API_BASE_URL = 'https://www.kmas.or.kr'
    $input = Join-Path $scratch 'input.csv'
    @('Fixture First', 'Fixture Second') | ForEach-Object {
        [pscustomobject]@{ Title = $_; Platform = $fixtureState.platform; IsMock = 'false'; SourceFile = 'fixture.csv' }
    } | Export-Csv -LiteralPath $input -Encoding UTF8 -NoTypeInformation
    $options = @{ Live = $true; InputCsv = $input; CheckpointDir = $scratch; MaxRequests = 2; DailyLimit = 3 }
    $first = & $resolver @options -OutputCsv (Join-Path $scratch 'first.csv')
    Assert-Equal $first.Completed 1 'first completed'
    Assert-Equal $first.Pending 1 'first pending'
    Assert-Equal $first.Verified 0 'partial CSV cannot be imported'
    Assert-Equal $fixtureState.calls 2 'timeout consumes quota and retries'
    $second = & $resolver @options -OutputCsv (Join-Path $scratch 'second.csv')
    Assert-Equal $second.Completed 2 'all completed'
    Assert-Equal $second.Resumed 1 'resume completed work'
    Assert-Equal $second.Verified 0 'duplicate official ID excludes both works'
    Assert-Equal $fixtureState.calls 3 'resumed work incurred no request'
    $third = & $resolver @options -OutputCsv (Join-Path $scratch 'third.csv') -IncludeReviewedCatalog
    Assert-Equal $third.Targets 22 'reviewed candidates included'
    Assert-Equal $third.Requests 0 'daily quota persists across configuration changes'
    Assert-Equal $fixtureState.calls 3 'no request after quota'
    $ledger = Get-ChildItem -LiteralPath (Join-Path $scratch 'requests') -Filter '*.json'
    if (($ledger | Get-Content -Raw) -match 'fixture-key|sensitive context') { throw 'Secrets or raw errors entered the ledger.' }
    $now = [DateTimeOffset]::UtcNow
    $rate = Get-KmasResponseFailure @{ Response = @{ StatusCode = 429; Headers = @{ 'Retry-After' = '120' } } } $now
    Assert-Equal $rate.Retry $true 'retry HTTP 429'
    Assert-Equal $rate.Until ($now.AddSeconds(120)) 'respect Retry-After'
    Assert-Equal (Get-KmasResponseFailure @{ Response = @{ StatusCode = 503 } } $now).Retry $true 'retry HTTP 503'
    Assert-Equal (Get-KmasResponseFailure @{ Response = @{ StatusCode = 401 } } $now).Retry $false 'do not retry authentication failures'
    'KMAS collection checks passed (16 assertions, zero external calls).'
} finally {
    $env:KMAS_API_KEY = $originalKey
    $env:KMAS_API_BASE_URL = $originalUrl
}
