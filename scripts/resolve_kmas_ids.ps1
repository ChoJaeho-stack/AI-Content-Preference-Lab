#Requires -Version 5.1
[CmdletBinding(DefaultParameterSetName = 'Live')]
param(
    [Parameter(Mandatory, ParameterSetName = 'Live')][switch]$Live,
    [Parameter(Mandatory, ParameterSetName = 'Plan')][switch]$LocalPlan,
    [Parameter(Mandatory, ParameterSetName = 'Live')][Parameter(Mandatory, ParameterSetName = 'Plan')][string]$InputCsv,
    [Parameter(Mandatory, ParameterSetName = 'Live')][Parameter(Mandatory, ParameterSetName = 'Plan')][string]$OutputCsv,
    [Parameter(ParameterSetName = 'Live')][switch]$CatalogScan,
    [Parameter(ParameterSetName = 'Live')][ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$CatalogStartDate,
    [Parameter(ParameterSetName = 'Live')][ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$CatalogEndDate,
    [Parameter(ParameterSetName = 'Live')][ValidateRange(1, 1000)][int]$MaxRequests = 50,
    [Parameter(ParameterSetName = 'Live')][string]$CheckpointDir = '.kmas-checkpoint',
    [Parameter(ParameterSetName = 'Live')][ValidatePattern('^[A-Za-z0-9_-]{1,40}$')][string]$CheckpointBatch = 'default',
    [Parameter(ParameterSetName = 'Live')][ValidateRange(1, 1000)][int]$DailyLimit = 1000,
    [Parameter(ParameterSetName = 'Live')][ValidateRange(1, 60)][int]$DelaySeconds = 2,
    [Parameter(ParameterSetName = 'Live')][ValidateRange(0, 3)][int]$MaxRetries = 2,
    [Parameter(ParameterSetName = 'Live')][Parameter(ParameterSetName = 'Plan')][switch]$IncludeReviewedCatalog,
    [Parameter(ParameterSetName = 'Live')][switch]$IncludeSynopsis,
    [Parameter(ParameterSetName = 'Live')][switch]$IncludeCoverSource,
    [Parameter(Mandatory, ParameterSetName = 'SelfTest')][switch]$SelfTest
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$script:requestCount = 0
. (Join-Path $PSScriptRoot 'kmas_collection_checkpoint.ps1')

function Get-Text($Record, [string]$Name) {
    $value = $Record.$Name
    if ($null -eq $value) { return '' }
    if ($value -isnot [string] -and $value -isnot [int] -and $value -isnot [long]) {
        throw 'UnexpectedFieldType'
    }
    return ([string]$value).Trim()
}

function Normalize-Text([string]$Value) {
    return [regex]::Replace($Value.Normalize([Text.NormalizationForm]::FormKC).Trim(), '\s+', ' ').ToLowerInvariant()
}

function Read-Items($Node, [int]$Depth = 0) {
    if ($null -eq $Node) { return }
    if ($Depth -gt 5) { throw 'UnexpectedItemNesting' }
    if ($Node -is [array]) {
        foreach ($entry in $Node) { Read-Items $entry ($Depth + 1) }
    } elseif ($Node -isnot [pscustomobject]) {
        throw 'UnexpectedItemShape'
    } elseif ($Node.PSObject.Properties['prdctNm'] -or $Node.PSObject.Properties['title']) {
        $Node
    } else {
        $containers = @($Node.PSObject.Properties | Where-Object { $_.Name -in @('itemlist', 'item', 'items') })
        if ($containers.Count -ne 1) { throw 'UnexpectedItemShape' }
        Read-Items $containers[0].Value ($Depth + 1)
    }
}

function Read-Page($Payload) {
    $result = $Payload.result
    if ($null -eq $result) { throw 'UnexpectedEnvelope' }
    $total = 0
    if (-not [int]::TryParse((Get-Text $result 'totalCount'), [ref]$total) -or $total -lt 0) {
        if ((Get-Text $result 'resultMessage') -match '필수|검색조건|검색 조건|파라미터|입력') {
            throw 'RequiredSearchCriteria'
        }
        throw 'InvalidTotalCount'
    }
    if ((Get-Text $result 'resultState') -cne 'success') {
        if ($total -eq 0 -and (Get-Text $result 'resultMessage') -match '데이터가\s*없') {
            return @{ Total = 0; Items = @() }
        }
        throw 'UnsuccessfulResponse'
    }
    $containers = @(foreach ($parent in @($Payload, $result)) {
        $parent.PSObject.Properties | Where-Object { $_.Name -eq 'itemlist' }
    })
    if ($total -eq 0 -and $containers.Count -eq 0) { return @{ Total = 0; Items = @() } }
    if ($containers.Count -ne 1) { throw 'UnexpectedItemList' }
    $items = @(Read-Items $containers[0].Value)
    return @{ Total = $total; Items = $items }
}

function Get-PageSet([scriptblock]$FetchPage, [string]$Title) {
    $pageIndex = 0
    $rows = New-Object 'System.Collections.Generic.List[object]'
    $expectedTotal = -1
    do {
        $page = Read-Page (& $FetchPage $Title $pageIndex)
        if ($expectedTotal -lt 0) { $expectedTotal = $page.Total }
        $expectedPageSize = [Math]::Min(100, $expectedTotal - $rows.Count)
        if ($page.Total -ne $expectedTotal -or $page.Items.Count -ne $expectedPageSize) {
            throw 'IncompleteOrChangedPagination'
        }
        foreach ($item in $page.Items) { $rows.Add($item) }
        $pageIndex++
    } while ($rows.Count -lt $expectedTotal)
    return ,$rows.ToArray()
}

function Resolve-Work($InputRow, [object[]]$Items, [bool]$Mock) {
    $targetTitle = Normalize-Text $InputRow.Title
    $targetPlatform = Normalize-Text $InputRow.Platform
    $record = [ordered]@{
        SourceFile = $InputRow.SourceFile; Title = $InputRow.Title; Platform = $InputRow.Platform
        Genre = ''; Author = ''; AuthorsJson = '[]'; SerialStartDate = ''; KMASExternalId = ''
        ListSeCd = ''; ISBN = ''; SetISBN = ''; Synopsis = ''; CoverSourceUrl = ''
        MissingFields = ''; IsMock = "$Mock".ToLowerInvariant(); ResolutionStatus = 'BLOCKED'; ResolutionReason = ''
    }
    $sameTitle = @($Items | Where-Object { (Normalize-Text (Get-Text $_ 'prdctNm')) -ceq $targetTitle })
    $candidates = @(foreach ($row in $sameTitle) {
        $platform = Normalize-Text (Get-Text $row 'pltfomCdNm')
        $code = Get-Text $row 'listSeCd'
        if ($platform -ceq $targetPlatform -and $platform -cne '네이버시리즈' -and $code -in @('', '1') -and
            -not (Get-Text $row 'isbn') -and -not (Get-Text $row 'setIsbn') -and
            -not (Get-Text $row 'edtn') -and -not (Get-Text $row 'plscmpnIdNm') -and
            (Get-Text $row 'dtaTyCdNm') -notmatch '단행본|도서') {
            $row
        }
    })
    $normalizedCandidates = @(foreach ($row in $candidates) {
        $authors = @(foreach ($field in @('sntncWritrNm', 'pictrWritrNm')) {
            $author = Get-Text $row $field
            if ($author) { $author }
        })
        $authors = @($authors | Select-Object -Unique)
        [pscustomobject]@{
            WorkTitle = Get-Text $row 'prdctNm'; DisplayTitle = Get-Text $row 'title'
            WorkId = Get-Text $row 'mastrId'; Code = Get-Text $row 'listSeCd'
            AuthorsJson = ConvertTo-Json -InputObject $authors -Compress
            Author = $authors -join ' · '; Genre = Get-Text $row 'mainGenreCdNm'
            SerialStartDate = Get-Text $row 'pusryBeginDe'; Synopsis = Get-Text $row 'outline'
            CoverSourceUrl = Get-Text $row 'imageDownloadUrl'
        }
    })
    $unique = @($normalizedCandidates | Group-Object -CaseSensitive -Property { ConvertTo-Json -InputObject $_ -Compress })
    if ($unique.Count -eq 0) {
        $record.ResolutionReason = if ($sameTitle.Count) { 'NoExactSerialPlatform' } else { 'NoExactTitle' }
    } elseif ($unique.Count -gt 1) {
        $record.ResolutionReason = 'AmbiguousSameTitlePlatform'
    } else {
        $match = $unique[0].Group[0]
        $record.ListSeCd = $match.Code
        $record.Author = $match.Author
        $record.AuthorsJson = $match.AuthorsJson
        $record.Genre = $match.Genre
        $record.SerialStartDate = $match.SerialStartDate
        $record.ResolutionReason = if ($match.DisplayTitle -and (Normalize-Text $match.DisplayTitle) -cne $targetTitle) {
            'ConflictingDisplayTitle'
        } elseif ($match.WorkId -notmatch '\A[A-Za-z0-9][A-Za-z0-9_.-]{0,190}\z') {
            'MissingOrInvalidMastrId'
        } elseif ($match.Code -cne '1') {
            'MissingExplicitWebtoonCode'
        } elseif (-not $match.Author) {
            'MissingAuthor'
        } elseif ($InputRow.Author -and (Normalize-Text $InputRow.Author) -cne (Normalize-Text $match.Author)) {
            'ConflictingAuthor'
        } elseif ($InputRow.KMASExternalId -and $InputRow.KMASExternalId -cne $match.WorkId) {
            'ConflictingLocalMastrId'
        } else {
            ''
        }
        if (-not $record.ResolutionReason) {
            $record.KMASExternalId = $match.WorkId
            $record.ResolutionStatus = 'VERIFIED'
            if ($IncludeSynopsis) { $record.Synopsis = $match.Synopsis }
            $uri = $null
            if ($IncludeCoverSource -and $match.CoverSourceUrl.Length -le 2048 -and
                [Uri]::TryCreate($match.CoverSourceUrl, [UriKind]::Absolute, [ref]$uri) -and
                $uri.Scheme -eq 'https' -and $uri.Host -and -not $uri.UserInfo) {
                $record.CoverSourceUrl = $match.CoverSourceUrl
            }
        }
    }
    $missing = @(foreach ($name in @('KMASExternalId', 'Author', 'Genre', 'SerialStartDate', 'Synopsis', 'CoverSourceUrl')) {
        if (-not $record[$name]) { $name }
    })
    $record.MissingFields = $missing -join ','
    return [pscustomobject]$record
}

function Reject-DuplicateIds([object[]]$Records) {
    $groups = @($Records | Where-Object KMASExternalId | Group-Object KMASExternalId | Where-Object Count -gt 1)
    foreach ($group in $groups) {
        foreach ($record in $group.Group) {
            $record.ResolutionStatus = 'BLOCKED'
            $record.ResolutionReason = 'DuplicateMastrIdAcrossWorks'
        }
    }
}

function Get-KmasFailureReason([string]$Message) {
    if ($Message -match '^KmasRequestFailed-(HTTP[0-9]{3}|Timeout|TransportError)$' -or
        $Message -in @('KmasCooldownActive', 'RequestBudgetExhausted', 'IncompleteOrChangedPagination',
        'UnexpectedEnvelope', 'InvalidTotalCount', 'RequiredSearchCriteria', 'UnsuccessfulResponse', 'UnexpectedItemList',
        'UnexpectedItemNesting', 'UnexpectedItemShape', 'UnexpectedFieldType')) { return $Message }
    return 'UnexpectedResolutionError'
}

function Request-KmasPage([string]$Title, [int]$PageIndex) {
    $query = [ordered]@{ prvKey = $apiKey; listSeCd = '1'; pageNo = $PageIndex; viewItemCnt = '100' }
    if ($Title) { $query.title = $Title }
    if ($CatalogStartDate) { $query.startDate = $CatalogStartDate; $query.endDate = $CatalogEndDate }
    $encoded = ($query.GetEnumerator() | ForEach-Object {
        '{0}={1}' -f [Uri]::EscapeDataString([string]$_.Key), [Uri]::EscapeDataString([string]$_.Value)
    }) -join '&'
    Invoke-RestMethod -Method Get -Uri ($endpoint + '?' + $encoded) -TimeoutSec 15 `
        -MaximumRedirection 0 -Headers @{ Accept = 'application/json' } -Verbose:$false -Debug:$false
}

function Write-NewCsv([object[]]$Records, [string]$Path) {
    $temp = "$Path.$([Guid]::NewGuid()).tmp"
    $stream = [IO.File]::Open($temp, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $writer = New-Object IO.StreamWriter($stream, (New-Object Text.UTF8Encoding($true)))
        try {
            foreach ($line in ($Records | ConvertTo-Csv -NoTypeInformation)) { $writer.WriteLine($line) }
        } finally { $writer.Dispose() }
    } finally { $stream.Dispose() }
    [IO.File]::Move($temp, $Path)
}

if ($SelfTest) {
    . (Join-Path $PSScriptRoot 'resolve_kmas_ids_selftest.ps1')
    return
}

$apiKey = $env:KMAS_API_KEY
$base = $null
if ($Live -and (-not $apiKey -or -not [Uri]::TryCreate($env:KMAS_API_BASE_URL, [UriKind]::Absolute, [ref]$base) -or
    $base.Scheme -ne 'https' -or $base.Host -notin @('kmas.or.kr', 'www.kmas.or.kr') -or -not $base.IsDefaultPort -or
    $base.AbsolutePath -ne '/' -or $base.UserInfo -or $base.Query -or $base.Fragment)) {
    throw 'Set KMAS_API_KEY and the approved HTTPS KMAS_API_BASE_URL before using -Live.'
}
$targetPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputCsv)
if ((Test-Path -LiteralPath $targetPath) -or -not (Test-Path -LiteralPath (Split-Path -Parent $targetPath) -PathType Container)) {
    throw 'Choose a new output CSV path in an existing directory.'
}
$inputRows = @(Import-Csv -LiteralPath $InputCsv -Encoding UTF8)
if ($IncludeReviewedCatalog) {
    $registryPath = Join-Path $PSScriptRoot '../contentlab/src/main/resources/static/webtoon-official-links.js'
    $registryText = Get-Content -LiteralPath $registryPath -Encoding UTF8 -Raw
    $registry = [regex]::Match($registryText, '(?s)Object\.freeze\((\{.*?\})\);')
    if (-not $registry.Success) { throw 'Reviewed catalog registry format changed.' }
    $registryJson = $registry.Groups[1].Value -replace ',\s*\}$', '}'
    $reviewed = (ConvertFrom-Json $registryJson).PSObject.Properties
    $inputRows += @(foreach ($entry in $reviewed) {
        $work = $entry.Value
        if ($work.status -eq 'verified') {
            [pscustomobject]@{ Title = $work.title; Platform = $work.platform; Author = $work.authors -join ' · '
                IsMock = 'false'; SourceFile = 'webtoon-official-links.js'; KMASExternalId = '' }
        }
    })
}
if (-not $inputRows.Count -or @($inputRows | Where-Object {
    $_.IsMock -cne 'false' -or -not $_.Title.Trim() -or $_.Platform.Length -gt 80 -or $_.Title.Length -gt 255 -or
    -not $_.Platform.Trim() -or (Normalize-Text $_.Platform) -ceq '네이버시리즈' -or $_.SourceFile -match 'mock|selftest'
}).Count) {
    throw 'Input must contain real diagnostic titles and the expected serial platforms.'
}
$dup = @($inputRows | Group-Object { (Normalize-Text $_.Title) + [char]31 + (Normalize-Text $_.Platform) } | Where-Object Count -gt 1)
if ($dup.Count) { throw 'Input contains duplicate title and platform targets.' }

if ($LocalPlan) {
    $planned = @(foreach ($row in $inputRows) {
        $record = Resolve-Work $row @() $false
        $record.ResolutionReason = 'AwaitingApprovedApiCall'
        $record
    })
    Write-NewCsv $planned $targetPath
    [pscustomobject]@{ Targets = $planned.Count; Requests = 0; Completed = 0; Verified = 0
        Pending = $planned.Count; OutputCsv = $targetPath }
    return
}
$endpoint = $base.AbsoluteUri.TrimEnd('/') + '/openapi/search/bookAndWebtoonList'
if ($CatalogStartDate -or $CatalogEndDate) {
    if (-not ($CatalogScan -and $CatalogStartDate -and $CatalogEndDate) -or $CatalogStartDate -gt $CatalogEndDate) {
        throw 'Specify an ordered pair of dates with -CatalogScan.'
    }
    [void][DateTime]::ParseExact($CatalogStartDate, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
    [void][DateTime]::ParseExact($CatalogEndDate, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
}
$checkpointRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($CheckpointDir)
[void][IO.Directory]::CreateDirectory($checkpointRoot)
$lock = [IO.File]::Open((Join-Path $checkpointRoot 'collection.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
try {
    $config = [ordered]@{ version = 1; batch = $CheckpointBatch; endpoint = $endpoint; catalogScan = [bool]$CatalogScan
        synopsis = [bool]$IncludeSynopsis; cover = [bool]$IncludeCoverSource; rows = $inputRows }
    if ($CatalogStartDate) { $config.dates = @($CatalogStartDate, $CatalogEndDate) }
    $runKey = Get-KmasHash ($config | ConvertTo-Json -Depth 8 -Compress)
    $runPath = Join-Path $checkpointRoot $runKey
    [void][IO.Directory]::CreateDirectory($runPath)
    $fetch = { param($title, $page) Get-KmasCachedPage $title $page }
    $catalog = @()
    $stopReason = ''
    if ($CatalogScan) {
        try {
            $catalog = Get-PageSet $fetch ''
        } catch {
            $stopReason = Get-KmasFailureReason $_.Exception.Message
            Write-KmasCheckpoint (Join-Path $runPath "catalog-failure-$([Guid]::NewGuid()).json") @{ reason = $stopReason }
        }
    }
    $consecutiveInvalidResponses = 0
    $resumed = 0
    $completed = 0
    $records = @(foreach ($row in $inputRows) {
        $rowKey = Get-KmasHash ((Normalize-Text $row.Title) + [char]31 + (Normalize-Text $row.Platform))
        $savedPath = Join-Path $runPath "$rowKey.json"
        if (Test-Path -LiteralPath $savedPath) {
            Get-Content -LiteralPath $savedPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $resumed++
            $completed++
            continue
        }
        if ($stopReason) {
            $record = Resolve-Work $row @() $false
            $record.ResolutionReason = 'NotQueriedAfter' + $stopReason
            $record
            continue
        }
        try {
            $items = if ($CatalogScan) { $catalog } else { Get-PageSet $fetch $row.Title }
            $record = Resolve-Work $row $items $false
            Write-KmasCheckpoint $savedPath $record
            $record
            $completed++
            $consecutiveInvalidResponses = 0
        } catch {
            $reason = Get-KmasFailureReason $_.Exception.Message
            $consecutiveInvalidResponses++
            if ($reason -like 'KmasRequestFailed-*' -or
                $reason -in @('KmasCooldownActive', 'RequestBudgetExhausted', 'UnsuccessfulResponse', 'UnexpectedResolutionError') -or
                $consecutiveInvalidResponses -ge 3) { $stopReason = $reason }
            $record = Resolve-Work $row @() $false
            $record.ResolutionReason = $reason
            Write-KmasCheckpoint (Join-Path $runPath "failure-$rowKey-$([Guid]::NewGuid()).json") $record
            if ($reason -in @('UnexpectedEnvelope', 'InvalidTotalCount', 'UnexpectedItemList',
                'UnexpectedItemNesting', 'UnexpectedItemShape', 'UnexpectedFieldType')) {
                Write-KmasCheckpoint $savedPath $record
                $completed++
            }
            $record
        }
    })
    Reject-DuplicateIds $records
    $pending = $records.Count - $completed
    $identified = @($records | Where-Object ResolutionStatus -eq 'VERIFIED').Count
    if ($pending) {
        foreach ($record in $records | Where-Object ResolutionStatus -eq 'VERIFIED') {
            $record.ResolutionStatus = 'BLOCKED'
            $record.ResolutionReason = 'PendingBatchDuplicateCheck'
        }
    }
    Write-NewCsv $records $targetPath
    [pscustomobject]@{
        Targets = $records.Count; Requests = $script:requestCount
        Completed = $completed; Resumed = $resumed; Pending = $pending; Identified = $identified
        StopReason = $stopReason
        Verified = @($records | Where-Object ResolutionStatus -eq 'VERIFIED').Count
        Blocked = @($records | Where-Object ResolutionStatus -eq 'BLOCKED').Count
        OutputCsv = $targetPath
    }
} finally { $lock.Dispose() }
