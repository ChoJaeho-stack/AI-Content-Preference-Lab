$base = [pscustomobject]@{
    prdctNm = '검증 대상'; title = '검증 대상'; pltfomCdNm = '네이버웹툰'
    listSeCd = '1'; mastrId = '1000020001'; sntncWritrNm = '글 작가'; pictrWritrNm = '그림 작가'
    mainGenreCdNm = '드라마'; outline = '모의 줄거리'; imageDownloadUrl = 'https://example.invalid/cover.jpg'
}
$target = [pscustomobject]@{ SourceFile = 'fixture'; Title = '검증 대상'; Platform = '네이버웹툰' }
function New-Candidate([hashtable]$Overrides) {
    $copy = [ordered]@{}
    foreach ($property in $base.PSObject.Properties) { $copy[$property.Name] = $property.Value }
    foreach ($entry in $Overrides.GetEnumerator()) { $copy[$entry.Key] = $entry.Value }
    return [pscustomobject]$copy
}
function Assert-Resolution($Actual, [string]$Expected) {
    if ($Actual -cne $Expected) { throw "Expected $Expected but received $Actual" }
}

$book = New-Candidate @{ listSeCd = '2'; mastrId = '1000020002'; isbn = '9781234567890' }
$series = New-Candidate @{ pltfomCdNm = '네이버시리즈'; mastrId = '1000020003' }
$match = Resolve-Work $target @($base, $base, $book, $series) $true
Assert-Resolution $match.ResolutionStatus 'VERIFIED'
Assert-Resolution $match.KMASExternalId '1000020001'
Assert-Resolution $match.AuthorsJson '["글 작가","그림 작가"]'
Assert-Resolution $match.IsMock 'true'
Assert-Resolution $match.Synopsis ''
Assert-Resolution $match.CoverSourceUrl ''
Assert-Resolution ((Resolve-Work $target @($book, $series) $true).ResolutionReason) 'NoExactSerialPlatform'
$homonym = New-Candidate @{ mastrId = '1000020004'; pictrWritrNm = '다른 작가' }
Assert-Resolution ((Resolve-Work $target @($base, $homonym) $true).ResolutionReason) 'AmbiguousSameTitlePlatform'
$noId = New-Candidate @{ mastrId = ''; listSeCd = '' }
Assert-Resolution ((Resolve-Work $target @($noId) $true).ResolutionReason) 'MissingOrInvalidMastrId'
$noType = New-Candidate @{ listSeCd = '' }
Assert-Resolution ((Resolve-Work $target @($noType) $true).ResolutionReason) 'MissingExplicitWebtoonCode'
$noAuthors = New-Candidate @{ sntncWritrNm = ''; pictrWritrNm = '' }
Assert-Resolution ((Resolve-Work $target @($noAuthors) $true).ResolutionReason) 'MissingAuthor'
$conflictingTarget = [pscustomobject]@{ SourceFile = 'fixture'; Title = '검증 대상'; Platform = '네이버웹툰'; Author = '다른 작가' }
Assert-Resolution ((Resolve-Work $conflictingTarget @($base) $true).ResolutionReason) 'ConflictingAuthor'
$IncludeSynopsis = $true
$IncludeCoverSource = $true
Assert-Resolution ((Resolve-Work $target @($base) $true).Synopsis) '모의 줄거리'
Assert-Resolution ((Resolve-Work $target @($base) $true).CoverSourceUrl) 'https://example.invalid/cover.jpg'
$badUrl = New-Candidate @{ imageDownloadUrl = 'https://test:token@example.invalid/cover.jpg' }
Assert-Resolution ((Resolve-Work $target @($badUrl) $true).CoverSourceUrl) ''
$secondRecord = Resolve-Work $target @($base) $true
$secondRecord.Title = '중복 자료 ID'
Reject-DuplicateIds @($match, $secondRecord)
Assert-Resolution $match.ResolutionReason 'DuplicateMastrIdAcrossWorks'
Assert-Resolution $secondRecord.ResolutionReason 'DuplicateMastrIdAcrossWorks'

$documented = { [pscustomobject]@{ result = [pscustomobject]@{ resultState = 'success'; totalCount = 1; itemlist = @($base) } } }
Assert-Resolution ((Get-PageSet $documented '검증 대상').Count) 1
$errorWithoutCount = {
    [pscustomobject]@{ result = [pscustomobject]@{ resultState = 'error'; resultMessage = 'API error' } }
}
try { $null = Read-Page (& $errorWithoutCount); throw 'FailedToRejectErrorEnvelope' }
catch { Assert-Resolution $_.Exception.Message 'UnsuccessfulResponse' }
$missingCriteria = {
    [pscustomobject]@{ result = [pscustomobject]@{ resultState = 'error'; resultMessage = '검색 조건을 입력하세요' } }
}
try { $null = Read-Page (& $missingCriteria); throw 'FailedToClassifyMissingCriteria' }
catch { Assert-Resolution $_.Exception.Message 'RequiredSearchCriteria' }
$emptyResponse = {
    [pscustomobject]@{ result = [pscustomobject]@{ resultState = 'error'; resultMessage = '데이터가 없습니다'; totalCount = 0 } }
}
Assert-Resolution ((Read-Page (& $emptyResponse)).Total) 0
$observed = {
    [pscustomobject]@{ result = [pscustomobject]@{ resultState = 'success'; totalCount = 1 }; itemList = @($noId) }
}
Assert-Resolution ((Get-PageSet $observed '검증 대상').Count) 1
$paged = {
    param($title, $page)
    $count = if ($page -eq 0) { 100 } else { 1 }
    [pscustomobject]@{ result = [pscustomobject]@{
        resultState = 'success'; totalCount = 101; itemlist = @(for ($i = 0; $i -lt $count; $i++) { $base })
    } }
}
Assert-Resolution ((Get-PageSet $paged '검증 대상').Count) 101
$incomplete = {
    [pscustomobject]@{ result = [pscustomobject]@{ resultState = 'success'; totalCount = 2 }; itemList = @($base) }
}
try { $null = Get-PageSet $incomplete '검증 대상'; throw 'FailedToRejectIncompletePage' }
catch { Assert-Resolution $_.Exception.Message 'IncompleteOrChangedPagination' }
$csvRecord = $match | ConvertTo-Csv -NoTypeInformation | ConvertFrom-Csv
Assert-Resolution $csvRecord.AuthorsJson '["글 작가","그림 작가"]'
$arrayId = New-Candidate @{ mastrId = @('1000020001') }
try { $null = Resolve-Work $target @($arrayId) $true; throw 'FailedToRejectArrayId' }
catch { Assert-Resolution $_.Exception.Message 'UnexpectedFieldType' }
'KMAS resolution self-test passed (26 assertions, zero live requests).'
