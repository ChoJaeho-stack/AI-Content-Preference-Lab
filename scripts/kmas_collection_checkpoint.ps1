function Get-KmasHash([string]$Value) {
    $hash = [Security.Cryptography.SHA256]::Create()
    try {
        [BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value))).Replace('-', '').ToLowerInvariant()
    } finally { $hash.Dispose() }
}

function Write-KmasCheckpoint([string]$Path, $Record) {
    $temp = "$Path.$([Guid]::NewGuid()).tmp"
    $bytes = [Text.Encoding]::UTF8.GetBytes(($Record | ConvertTo-Json -Depth 10 -Compress))
    $stream = [IO.File]::Open($temp, 'CreateNew', 'Write', 'None')
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally { $stream.Dispose() }
    [IO.File]::Move($temp, $Path)
}

function Get-KmasResponseFailure($Exception, [DateTimeOffset]$Now) {
    $response = $Exception.Response
    $status = if ($response) { [int]$response.StatusCode } else { 0 }
    $timeout = $Exception -is [TimeoutException] -or
        ($Exception -is [Net.WebException] -and $Exception.Status -eq [Net.WebExceptionStatus]::Timeout)
    $until = $Now
    if ($response -and $response.Headers) {
        $retryAfter = [string]$response.Headers['Retry-After']
        $seconds = 0
        $date = [DateTimeOffset]::MinValue
        if ([int]::TryParse($retryAfter, [ref]$seconds) -and $seconds -gt 0) {
            $until = $Now.AddSeconds($seconds)
        } elseif ([DateTimeOffset]::TryParse($retryAfter, [ref]$date) -and $date -gt $Now) {
            $until = $date
        }
    }
    @{
        Retry = $timeout -or $status -eq 429 -or ($status -ge 500 -and $status -le 599)
        Code = if ($timeout) { 'Timeout' } elseif ($status) { "HTTP$status" } else { 'TransportError' }
        Until = $until
    }
}

function Invoke-KmasWithRetry([string]$Title, [int]$PageIndex) {
    $ledger = Join-Path $checkpointRoot 'requests'
    [void][IO.Directory]::CreateDirectory($ledger)
    for ($attempt = 0; $attempt -le $MaxRetries; $attempt++) {
        $now = [DateTimeOffset]::UtcNow
        $day = $now.ToOffset([TimeSpan]::FromHours(9)).ToString('yyyyMMdd')
        if ($script:requestCount -ge $MaxRequests -or
            @(Get-ChildItem -LiteralPath $ledger -Filter "request-$day-*.json").Count -ge $DailyLimit) {
            throw 'RequestBudgetExhausted'
        }
        $latest = Get-ChildItem -LiteralPath $ledger -Filter 'wait-*.json' | Sort-Object Name -Descending | Select-Object -First 1
        if ($latest) {
            $waitRecord = Get-Content -LiteralPath $latest.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            $delay = ([DateTimeOffset]::Parse($waitRecord.until) - $now).TotalSeconds
            if ($delay -gt 60) { throw 'KmasCooldownActive' }
            if ($delay -gt 0) { Start-Sleep -Seconds ([int][Math]::Ceiling($delay)) }
        }
        $now = [DateTimeOffset]::UtcNow
        $day = $now.ToOffset([TimeSpan]::FromHours(9)).ToString('yyyyMMdd')
        if (@(Get-ChildItem -LiteralPath $ledger -Filter "request-$day-*.json").Count -ge $DailyLimit) {
            throw 'RequestBudgetExhausted'
        }
        $marker = [Guid]::NewGuid()
        Write-KmasCheckpoint (Join-Path $ledger "request-$day-$marker.json") @{ utc = $now.ToString('o') }
        Write-KmasCheckpoint (Join-Path $ledger "wait-$($now.UtcTicks)-$marker.json") @{
            until = $now.AddSeconds(15 + $DelaySeconds).ToString('o')
            result = 'Reserved'
        }
        $script:requestCount++
        $failure = $null
        try {
            $payload = Request-KmasPage $Title $PageIndex
        } catch {
            $failure = Get-KmasResponseFailure $_.Exception ([DateTimeOffset]::UtcNow)
        }
        $finish = [DateTimeOffset]::UtcNow
        $until = $finish.AddSeconds($DelaySeconds)
        if ($failure -and $failure.Retry) {
            $until = $finish.AddSeconds([Math]::Max($DelaySeconds, [Math]::Pow(2, $attempt + 1)))
            if ($failure.Until -gt $until) { $until = $failure.Until }
        }
        Write-KmasCheckpoint (Join-Path $ledger "wait-$($finish.UtcTicks)-$marker.json") @{
            until = $until.ToString('o')
            result = if ($failure) { $failure.Code } else { 'Received' }
        }
        if (-not $failure) { return $payload }
        if (-not $failure.Retry -or $attempt -eq $MaxRetries -or ($until - $finish).TotalSeconds -gt 60) {
            throw ("KmasRequestFailed-" + $failure.Code)
        }
    }
}

function Get-KmasCachedPage([string]$Title, [int]$PageIndex) {
    $titleKey = Get-KmasHash $Title
    # The live title endpoint advances one record when pageNo increases by one.
    # The unfiltered catalog uses its separately documented page numbering.
    $requestPage = if ($Title) { $PageIndex * 100 } else { $PageIndex }
    $path = Join-Path $runPath "page-$titleKey-$requestPage.json"
    if (Test-Path -LiteralPath $path) {
        return (Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json)
    }
    $page = Read-Page (Invoke-KmasWithRetry $Title $requestPage)
    if ($PageIndex -gt 0) {
        $first = Get-Content -LiteralPath (Join-Path $runPath "page-$titleKey-0.json") -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($page.Total -ne $first.result.totalCount) { throw 'IncompleteOrChangedPagination' }
    }
    $remaining = $page.Total - 100 * $PageIndex
    if ($remaining -lt 0 -or $page.Items.Count -ne [Math]::Min(100, $remaining)) {
        throw 'IncompleteOrChangedPagination'
    }
    $fields = @('prdctNm', 'title', 'pltfomCdNm', 'listSeCd', 'isbn', 'setIsbn', 'edtn', 'plscmpnIdNm',
        'dtaTyCdNm', 'sntncWritrNm', 'pictrWritrNm', 'mastrId', 'mainGenreCdNm', 'pusryBeginDe')
    if ($IncludeSynopsis) { $fields += 'outline' }
    if ($IncludeCoverSource) { $fields += 'imageDownloadUrl' }
    $page = [pscustomobject]@{
        result = @{ resultState = 'success'; totalCount = $page.Total }
        itemList = @(foreach ($item in $page.Items) {
            $record = [ordered]@{}
            foreach ($field in $fields) { $record[$field] = Get-Text $item $field }
            [pscustomobject]$record
        })
    }
    Write-KmasCheckpoint $path $page
    return $page
}
