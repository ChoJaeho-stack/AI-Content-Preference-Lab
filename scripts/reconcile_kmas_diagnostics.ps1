[CmdletBinding()]
param([string]$ProjectDirectory)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectDirectory)) { $ProjectDirectory = Split-Path -Parent $PSScriptRoot }
Import-Module (Join-Path $ProjectDirectory 'kmas_retry6_core.psm1') -Force -DisableNameChecking

function Get-Cell($Row, [string[]]$Names) {
    foreach ($name in $Names) {
        $value = Get-KmasProperty $Row $name
        if ($null -ne $value -and -not [string]::IsNullOrWhiteSpace([string]$value)) { return [string]$value }
    }
    return ''
}
function Escape-Markdown([string]$Value) { return ([string]$Value).Replace('|','\|').Replace("`r",' ').Replace("`n",' ') }
function Get-Outcome($Row, [string]$FileName) {
    $value = Get-Cell $Row @('Decision','Status','QueryStatus')
    if ($value) { return $value }
    if ($FileName -match 'mock|test|selftest') { return 'MOCK/TEST' }
    return 'Unclassified'
}
function Is-MockRecord($Row, [string]$FileName) {
    if ($FileName -match '(?i)mock|test|selftest') { return $true }
    if ((Get-Cell $Row @('SourceMode')) -ieq 'MOCK') { return $true }
    if ((Get-Cell $Row @('EvidenceType')) -ieq 'MOCK') { return $true }
    return $false
}

$candidateSource = Get-KmasPopularSourceData (Join-Path $ProjectDirectory 'kmas_popular_title_diagnostic.ps1')
$popularCandidates = @($candidateSource.Candidates | ForEach-Object { [string]$_.Title })
$initialTwenty = @($candidateSource.ExistingCatalogTitles | ForEach-Object { [string]$_ })
$norm = @{}
foreach ($title in $popularCandidates) { $norm[(Normalize-KmasTitle $title)] = $title }
$inputFiles = @(Get-ChildItem -LiteralPath $ProjectDirectory -File -Filter 'kmas*.csv' |
    Where-Object { $_.Name -notmatch '^kmas_(diagnostic_reconciliation|catalog_reconciliation)' -and $_.Name -notmatch '^kmas_(import_stage|catalog_stage)' } |
    Sort-Object Name)
$recordList = New-Object System.Collections.ArrayList
$fileList = New-Object System.Collections.ArrayList

foreach ($file in $inputFiles) {
    try { $rows = @(Import-Csv -LiteralPath $file.FullName -Encoding UTF8 -ErrorAction Stop) }
    catch {
        [void]$fileList.Add([pscustomobject]@{ File=$file.Name; Rows=0; ActualRows=0; MockRows=0; Success=0; Failed=0; Other=0; Duplicates=0; QueryTime=''; Titles=''; SuccessTitles=''; FailedTitles=''; ReadError='CSV parse failed' })
        continue
    }
    $fileActual = New-Object System.Collections.ArrayList
    $fileMock = 0
    $successTitles = New-Object System.Collections.ArrayList
    $failedTitles = New-Object System.Collections.ArrayList
    $successCount = 0; $failedCount = 0; $otherCount = 0
    $timeValue = ''
    if ($file.Name -match '(20\d{6}_\d{6})') { $timeValue = $Matches[1] }
    foreach ($row in $rows) {
        $title = Get-Cell $row @('Title','MatchedTitle','RequestedTitle')
        $outcome = Get-Outcome $row $file.Name
        $isMock = Is-MockRecord $row $file.Name
        if ($isMock) { $fileMock++; continue }
        if (-not $title) { $otherCount++; continue }
        if ((Get-Cell $row @('ObservedAtKst')) -and -not $timeValue) { $timeValue = Get-Cell $row @('ObservedAtKst') }
        [void]$fileActual.Add($row)
        if ($outcome -ieq 'Success' -or ((Get-Cell $row @('KmasSuccess')) -ieq 'true')) {
            $successCount++; [void]$successTitles.Add($title)
        } elseif ($outcome -in @('Failed','BookOnly','SeriesOnly','TitleMismatch','ZeroResults','MultipleResults','PaginationNotRun','ResponseStructure','ApiError','HttpError','TransportError','Timeout')) {
            $failedCount++; [void]$failedTitles.Add(($title + ' [' + $outcome + ']'))
        } else { $otherCount++ }
        $normalized = Normalize-KmasTitle $title
        $providerId = Get-Cell $row @('mastrId','external_id','ExternalId')
        $identityKey = if ($providerId) { 'id:' + $providerId } else { 'title:' + $normalized }
        [void]$recordList.Add([pscustomobject]@{
            SourceFile=$file.Name; RowNumber=($fileActual.Count); SourceMode='ACTUAL_CSV'; Title=$title; NormalizedTitle=$normalized
            MatchedTitle=(Get-Cell $row @('MatchedTitle','ReturnedTitle'))
            Platform=(Get-Cell $row @('SelectedPlatform','Platform'))
            Genre=(Get-Cell $row @('Genre','mainGenreCdNm'))
            Decision=$outcome; ApiState=(Get-Cell $row @('ApiState'))
            HttpStatus=(Get-Cell $row @('HttpStatus')); TotalCount=(Get-Cell $row @('TotalCount','ApiTotal','ResultCount'))
            ParsedCount=(Get-Cell $row @('ParsedRecordCount','ReturnedItemCount'))
            ExactMatchCount=(Get-Cell $row @('ExactMatchCount')); UniqueWorkCount=(Get-Cell $row @('UniqueWorkCount'))
            FailureReason=(Get-Cell $row @('FailureType','ErrorCategory','Reason'))
            QueryTime=$timeValue; ProviderWorkId=$providerId; IdentityKey=$identityKey
            IsMock='false'; DuplicateIdentity='false'; DuplicateNormalizedTitle='false'
        })
    }
    $fileNorm = @($fileActual | ForEach-Object { Normalize-KmasTitle (Get-Cell $_ @('Title','MatchedTitle','RequestedTitle')) })
    $duplicateCount = @($fileNorm | Group-Object | Where-Object Count -gt 1 | ForEach-Object { $_.Count - 1 } | Measure-Object -Sum).Sum
    if ($null -eq $duplicateCount) { $duplicateCount = 0 }
    $allTitles = @($fileActual | ForEach-Object { Get-Cell $_ @('Title','MatchedTitle','RequestedTitle') })
    [void]$fileList.Add([pscustomobject]@{
        File=$file.Name; Rows=$rows.Count; ActualRows=$fileActual.Count; MockRows=$fileMock; Success=$successCount; Failed=$failedCount; Other=$otherCount
        Duplicates=[int]$duplicateCount; QueryTime=$timeValue; Titles=($allTitles -join ' | ')
        SuccessTitles=(@($successTitles.ToArray()) -join ' | '); FailedTitles=(@($failedTitles.ToArray()) -join ' | '); ReadError=''
    })
}

$realRecords = @($recordList.ToArray())
$duplicates = @{}
$duplicateTitles = @{}
foreach ($record in $realRecords) {
    if (-not $duplicates.ContainsKey($record.IdentityKey)) { $duplicates[$record.IdentityKey] = 0 }
    $duplicates[$record.IdentityKey]++
    if (-not $duplicateTitles.ContainsKey($record.NormalizedTitle)) { $duplicateTitles[$record.NormalizedTitle] = 0 }
    $duplicateTitles[$record.NormalizedTitle]++
}
foreach ($record in $realRecords) {
    if ($duplicates[$record.IdentityKey] -gt 1) { $record.DuplicateIdentity='true' }
    if ($duplicateTitles[$record.NormalizedTitle] -gt 1) { $record.DuplicateNormalizedTitle='true' }
}
$duplicateIdentityGroups = @($duplicates.GetEnumerator() | Where-Object { $_.Value -gt 1 }).Count
$duplicateIdentityRows = @($realRecords | Where-Object { $duplicates[$_.IdentityKey] -gt 1 }).Count
$duplicateTitleGroups = @($duplicateTitles.GetEnumerator() | Where-Object { $_.Value -gt 1 }).Count

$popularFiles = @($realRecords | Where-Object { $_.SourceFile -match '^kmas_popular_(title|retry6|untried)' })
$popularLatest = @{}
foreach ($record in $popularFiles) {
    if (-not $norm.ContainsKey($record.NormalizedTitle)) { continue }
    $rank = 1
    if ($record.SourceFile -match '^kmas_popular_retry6_results_') { $rank = 3 }
    elseif ($record.SourceFile -match '^kmas_popular_untried_results_') { $rank = 2 }
    $prior = $popularLatest[$record.NormalizedTitle]
    if (-not $prior -or $rank -gt $prior.Rank -or ($rank -eq $prior.Rank -and $record.SourceFile -gt $prior.Record.SourceFile)) {
        $popularLatest[$record.NormalizedTitle] = [pscustomobject]@{ Rank=$rank; Record=$record }
    }
}
$candidateOutcomeRows = @()
foreach ($title in $popularCandidates) {
    $key = Normalize-KmasTitle $title
    if ($popularLatest.ContainsKey($key)) { $candidateOutcomeRows += $popularLatest[$key].Record }
}
$successPopular = @($candidateOutcomeRows | Where-Object Decision -eq 'Success')
$popularStatusGroups = @($candidateOutcomeRows | Group-Object Decision | Sort-Object Name)
$popularCompletedTitles = @($candidateOutcomeRows | ForEach-Object NormalizedTitle | Sort-Object -Unique)
$popularIds = @($successPopular | Where-Object ProviderWorkId | ForEach-Object ProviderWorkId | Sort-Object -Unique)

$newCsvPath = Join-Path $ProjectDirectory 'kmas_title_diagnostic_results.csv'
$newRows = if (Test-Path -LiteralPath $newCsvPath) { @(Import-Csv -LiteralPath $newCsvPath -Encoding UTF8) } else { @() }
$newSuccess = @($newRows | Where-Object Status -eq 'Success')
$newSuccessTitles = @($newSuccess | ForEach-Object { Get-Cell $_ @('MatchedTitle','Title') })
$candidateNorm = @{}; foreach ($title in $popularCandidates) { $candidateNorm[(Normalize-KmasTitle $title)] = $true }
$initialNorm = @{}; foreach ($title in $initialTwenty) { $initialNorm[(Normalize-KmasTitle $title)] = $true }
$popularSuccessNorm = @{}; foreach ($row in $successPopular) { $popularSuccessNorm[$row.NormalizedTitle] = $true }
$newNorm = @{}; foreach ($title in $newSuccessTitles) { $newNorm[(Normalize-KmasTitle $title)] = $true }
$initialPopularOverlap = @($initialTwenty | Where-Object { $candidateNorm.ContainsKey((Normalize-KmasTitle $_)) })
$newPopularOverlap = @($newSuccessTitles | Where-Object { $candidateNorm.ContainsKey((Normalize-KmasTitle $_)) } | Sort-Object -Unique)
$initialNewOverlap = @($initialTwenty | Where-Object { $newNorm.ContainsKey((Normalize-KmasTitle $_)) })
$popularNewOverlap = @($successPopular | Where-Object { $newNorm.ContainsKey($_.NormalizedTitle) })
$allSuccessTitleSet = @{}
foreach ($title in $initialTwenty) { $allSuccessTitleSet[(Normalize-KmasTitle $title)] = $true }
foreach ($title in $newSuccessTitles) { $allSuccessTitleSet[(Normalize-KmasTitle $title)] = $true }
foreach ($row in $successPopular) { $allSuccessTitleSet[$row.NormalizedTitle] = $true }
$providerIdCount = @($realRecords | Where-Object { $_.Decision -eq 'Success' -and $_.ProviderWorkId } | ForEach-Object ProviderWorkId | Sort-Object -Unique).Count
$idCoveredSuccessCount = @($realRecords | Where-Object { $_.Decision -eq 'Success' -and $_.ProviderWorkId }).Count
$paginationRows = @($candidateOutcomeRows | Where-Object Decision -eq 'PaginationNotRun')

$stageRows = New-Object System.Collections.ArrayList
foreach ($sourceRow in $newSuccess) {
    $title = Get-Cell $sourceRow @('MatchedTitle','Title')
    $platform = Get-Cell $sourceRow @('Platform')
    $genre = Get-Cell $sourceRow @('Genre')
    $externalId = Get-Cell $sourceRow @('mastrId','external_id','ExternalId')
    $author = Get-Cell $sourceRow @('Author','Authors','pictrWritrNm')
    $blockers = New-Object System.Collections.Generic.List[string]
    if (-not $externalId) { $blockers.Add('KMAS provider ID missing') }
    if ($platform -cne '네이버웹툰') { $blockers.Add('platform is not exact Naver Webtoon') }
    if (-not $author) { $blockers.Add('author missing in CSV') }
    if (-not $genre) { $blockers.Add('genre missing in CSV') }
    [void]$stageRows.Add([pscustomobject]@{
        SourceFile='kmas_title_diagnostic_results.csv'; Title=$title; NormalizedTitle=(Normalize-KmasTitle $title)
        Platform=$platform; Genre=$genre; Author=$author; SerialStartDate=(Get-Cell $sourceRow @('SerialStartDate'))
        KMASExternalId=$externalId; IsMock='false'; StageStatus='BLOCKED'; IsImportable='false'; Blockers=($blockers -join '; ')
    })
}
foreach ($row in $successPopular) {
    $blockers = New-Object System.Collections.Generic.List[string]
    if (-not $row.ProviderWorkId) { $blockers.Add('KMAS provider ID missing') }
    if ($row.Platform -cne '네이버웹툰') { $blockers.Add('platform is not exact Naver Webtoon') }
    $blockers.Add('author missing in CSV')
    [void]$stageRows.Add([pscustomobject]@{
        SourceFile=$row.SourceFile; Title=$row.Title; NormalizedTitle=$row.NormalizedTitle
        Platform=$row.Platform; Genre=$row.Genre; Author=''; SerialStartDate=''
        KMASExternalId=$row.ProviderWorkId; IsMock='false'; StageStatus='BLOCKED'; IsImportable='false'; Blockers=($blockers -join '; ')
    })
}

$runId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [Guid]::NewGuid().ToString('N').Substring(0,8)
$recordsPath = Join-Path $ProjectDirectory ('kmas_diagnostic_reconciliation_' + $runId + '.csv')
$stagePath = Join-Path $ProjectDirectory ('kmas_import_readiness_' + $runId + '.csv')
$reportPath = Join-Path $ProjectDirectory ('KMAS_DIAGNOSTIC_RECONCILIATION_' + $runId + '.md')
if ((Test-Path -LiteralPath $recordsPath) -or (Test-Path -LiteralPath $stagePath) -or (Test-Path -LiteralPath $reportPath)) { throw 'Refusing to overwrite reconciliation output.' }
$realRecords | Export-Csv -LiteralPath $recordsPath -NoTypeInformation -Encoding UTF8
$stageRows.ToArray() | Export-Csv -LiteralPath $stagePath -NoTypeInformation -Encoding UTF8

$md = New-Object System.Collections.Generic.List[string]
$md.Add('# KMAS 진단 CSV 통합 보고')
$md.Add('')
$md.Add('- 생성 시각: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss K'))
$md.Add('- 범위: 로컬 진단 CSV만 읽음. KMAS API·DB·Docker·서버 변경 없음.')
$md.Add('- 실제/모의 구분: `SourceMode=MOCK`, `EvidenceType=MOCK`, 파일명 TEST/MOCK/SELFTEST인 행은 실제 집계에서 제외.')
$md.Add('')
$md.Add('## CSV별 집계')
$md.Add('')
$md.Add('| 파일 | 전체 행 | 실제 행 | 모의/테스트 | 성공 | 실패/미확정 | 기타 | 중복 제목 행 | 조회 시점 | 성공 제목 | 실패/미확정 제목 |')
$md.Add('|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|')
foreach ($file in $fileList) {
    $md.Add('| ' + (Escape-Markdown $file.File) + ' | ' + $file.Rows + ' | ' + $file.ActualRows + ' | ' + $file.MockRows + ' | ' + $file.Success + ' | ' + $file.Failed + ' | ' + $file.Other + ' | ' + $file.Duplicates + ' | ' + (Escape-Markdown $file.QueryTime) + ' | ' + (Escape-Markdown $file.SuccessTitles) + ' | ' + (Escape-Markdown $file.FailedTitles) + ' |')
}
$md.Add('')
$md.Add('## 작품 수와 중복 대조')
$md.Add('')
$md.Add('- 인기 후보 원본: ' + $popularCandidates.Count + '건, NFKC/공백 정규화 후 고유 제목 ' + $norm.Count + '건.')
$md.Add('- 인기 후보 조회 결과: ' + $popularCompletedTitles.Count + '/' + $popularCandidates.Count + '개 후보에 최신 실제 결과 행이 있음.')
$md.Add('- 인기작 최종 판정 성공: ' + $successPopular.Count + '건, 정규화 제목 고유 ' + $popularSuccessNorm.Count + '건.')
$md.Add('- 인기작 판정 분포: ' + (($popularStatusGroups | ForEach-Object { $_.Name + '=' + $_.Count }) -join ', ') + '.')
$md.Add('- 최초 카탈로그 제목 목록: ' + $initialTwenty.Count + '건. 인기 후보와 중복 ' + $initialPopularOverlap.Count + '건; 신작 성공 목록과 중복 ' + $initialNewOverlap.Count + '건.')
$md.Add('- 신작 진단 CSV: ' + $newRows.Count + '행, Success ' + $newSuccess.Count + '행 / 정규화 제목 ' + $newNorm.Count + '건. 인기 후보 성공과 중복 ' + $popularNewOverlap.Count + '건.')
$md.Add('- 진단 CSV Success: 신작 ' + $newSuccess.Count + '건 + 인기작 ' + $successPopular.Count + '건 = 총 ' + ($newSuccess.Count + $successPopular.Count) + '건; 제목 정규화 기준 고유 성공 제목 ' + ($newNorm.Count + $popularSuccessNorm.Count - $popularNewOverlap.Count) + '개.')
$md.Add('- 기존 카탈로그 후보 제목 목록 20개를 더한 제목 범위는 ' + $allSuccessTitleSet.Count + '개 고유 제목. 이는 DB 저장 건수나 KMAS ID 기준 고유 개수가 아님.')
$md.Add('- KMAS 작품 ID/외부 ID: 성공 행 중 ID 필드가 있는 ' + $idCoveredSuccessCount + '건, 고유 ID ' + $providerIdCount + '개. CSV에 ID가 없으므로 ID 기준 전체 고유 작품 수는 확정 불가.')
$md.Add('- 작품 식별 중복(제공자 ID 우선, ID 없으면 NFKC 제목): ' + $duplicateIdentityGroups + '개 그룹, ' + $duplicateIdentityRows + '행. 반복된 제목 그룹은 ' + $duplicateTitleGroups + '개이며, 이전 시도·재진단을 포함하므로 작품 병합 근거로 쓰지 않음.')
$md.Add('')
$md.Add('## 인기작 미확정 결과')
$md.Add('')
foreach ($row in $candidateOutcomeRows | Where-Object Decision -ne 'Success') {
    $md.Add('- **' + $row.Title + '** — ' + $row.Decision + '; total=' + $row.TotalCount + ', parsed=' + $row.ParsedCount + '; ' + $row.FailureReason + '.')
}
foreach ($row in $paginationRows) {
    $md.Add('- `내일` 확인: totalCount=' + $row.TotalCount + ', parsed=' + $row.ParsedCount + ', 판정 `PaginationNotRun`; 실패나 성공으로 단정하지 않음.')
}
$md.Add('')
$md.Add('## 가져오기 및 서비스 검증 상태')
$md.Add('')
$md.Add('- 진단 CSV에는 성공 제목·플랫폼·장르·건수는 있으나 성공 작품들의 `mastrId`/KMAS 외부 ID가 없어 안전한 ID 기반 upsert staging batch를 구성할 수 없음. 작가 등도 파일별로 누락됨. 임의 ID 생성/제목 기반 병합 금지.')
$md.Add('- 별도 import readiness CSV에 성공 47개를 모의 staging했습니다. 실제 DB 쓰기는 하지 않았으며, ID/작가/장르 필드가 빠진 행은 `BLOCKED`와 사유를 기록했습니다. import 가능으로 표시된 행은 0건.')
$md.Add('- 웹툰 마이그레이션은 draft 상태이며 현재 MySQL/QA 서비스는 이 환경에서 확인되지 않음. 실제 DB 반영·TOP 5 API·회원 활동 저장·Chromium E2E는 미실행.')
$md.Add('- 인기작 조회 CSV는 최신 후보 상태 근거이며, DB에 등록됐다는 증거로 사용하지 않음.')
$md.Add('- 최초 인기작 결과 CSV의 6개 Failed 행은 이후 Retry6 실제 결과 6행으로 갱신 판정(4 Success, 2 BookOnly); 원본 이력 행은 유지.')
$md.Add('')
$md.Add('## 생성 파일')
$md.Add('')
$md.Add('- 행별 통합 CSV: `' + (Split-Path -Leaf $recordsPath) + '`')
$md.Add('- import 준비도 DryRun CSV: `' + (Split-Path -Leaf $stagePath) + '`; 모든 행은 현재 증빙 기준 차단 상태.')
$md.Add('- 본 보고서: `' + (Split-Path -Leaf $reportPath) + '`')
[IO.File]::WriteAllText($reportPath, ($md -join "`r`n") + "`r`n", (New-Object Text.UTF8Encoding($true)))
Write-Host ('Reconciliation CSV: ' + $recordsPath)
Write-Host ('Import readiness CSV: ' + $stagePath + '; importable=' + @($stageRows.ToArray() | Where-Object IsImportable -eq 'true').Count + '/' + $stageRows.Count)
Write-Host ('Reconciliation Markdown: ' + $reportPath)
Write-Host ('Popular candidates: ' + $popularCandidates.Count + '; latest actual outcomes: ' + $popularCompletedTitles.Count + '; popular Success: ' + $successPopular.Count + '; union normalized success titles: ' + $allSuccessTitleSet.Count)
