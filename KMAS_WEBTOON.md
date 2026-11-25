# KMAS 웹툰 카탈로그 연동

## 확인된 공식 계약

KMAS [Open API 안내](https://kmas.or.kr/guide/openapi)는 실명 확인 계정, 발급 키, 관리자 승인이 필요하고 개발/운영 모두 승인 뒤 사용하도록 안내합니다. 일일 요청 한도는 1,000회, 조회 경로는 `/openapi/search/bookAndWebtoonList`, `listSeCd=1`은 웹툰, `viewItemCnt` 최대값은 100입니다. 문서에 적힌 서비스 호스트는 `서비스URL주소` 자리표시자이므로 프로그램은 호스트를 추정하지 않습니다. 승인된 사용 안내에서 받은 HTTPS 서비스 루트를 `KMAS_API_BASE_URL`에 넣어야 합니다.

응답 문서는 `result.resultState`, `result.totalCount`, `result.itemlist`와 `mastrId`, `prdctNm`, `pictrWritrNm`, `sntncWritrNm`, `mainGenreCdNm`, `outline`, `imageDownloadUrl` 등을 설명합니다. 같은 문서의 샘플 행에는 `listSeCd=2` 도서가 실려 있어, 동기화기는 `listSeCd=1`인 행만 받습니다. 실제 API 스키마가 문서와 다르면 가져오기를 중단하고 기존 카탈로그를 보존합니다.

## 승인 전

- 기본값은 `KMAS_API_MODE=mock`; 앱 시작 시 외부 호출은 없습니다.
- 단위 검증에는 `test_kmas_webtoon_provider.py`의 합성 응답을 사용합니다. 실제 작품 데이터로 오인하지 않습니다.
- 30개 창작 가상 작품과 자체 제작 SVG 포스터는 `contentlab_demo_fictional` provider와 격리 시연 DB 전용입니다. KMAS importer는 이 레코드를 읽거나 덮어쓰지 않습니다.
- 표지 URL은 `cover_source_url`에 출처 메타데이터로 보관할 수 있지만 다운로드하거나 공개하지 않습니다. 줄거리는 권리 설정이 닫혀 있으면 `contents.overview`에 저장하지 않습니다.

## 승인 후 동기화

18083 격리 QA에서는 사용자가 확인한 `https://www.kmas.or.kr` 서비스 루트로 제목 검색을 검증했고 연재작 15건을 적재했습니다. 실제 제목 검색은 최상위 `itemList`를 반환하며, 검증한 작품 행에는 `mastrId`와 `listSeCd`가 없었습니다. 아래 전체 목록 동기화는 공개 문서의 응답 형식을 처리합니다.

1. 별도 웹툰 카탈로그 MySQL 스키마를 준비하고, 승인된 변경 절차로 `V20261119_01__webtoon_catalog_and_taste.sql`, `V20261121_01__webtoon_cover_source_url.sql`, `V20261122_01__kmas_daily_usage.sql`을 적용합니다. 운영 DB에 자동 마이그레이션하지 않습니다.
2. 서버 비밀 저장소 또는 로컬 비밀 환경에 DB 연결값, `KMAS_API_MODE=live`, `KMAS_API_APPROVED=true`, 발급된 `KMAS_API_KEY`, 안내문에서 확인한 `KMAS_API_BASE_URL`을 설정합니다. 키는 URL 쿼리 파라미터로만 요청에 포함되며 로그/오류에 출력하지 않습니다.
3. 기본 요청은 페이지당 100건, 동기화 1회 최대 10페이지입니다. 별도 usage 테이블에서 요청마다 일일 1,000회 한도를 원자적으로 소비합니다. 인증 실패·429·오류 응답을 재시도하지 않습니다.
4. `py -m kmas_webtoon_provider`를 명시적으로 실행합니다. 모든 페이지를 먼저 검증한 뒤 한 트랜잭션으로 ID(provider + `mastrId`) 기준 upsert합니다. 데이터베이스 잠금으로 중복 동기화를 막고, 충돌·불완전 응답이면 롤백합니다.
5. 웹툰 추천 인스턴스에서 `WEBTOON_RECOMMENDATION_PROVIDERS=kmas`로 설정합니다. 실제 카탈로그 DB에는 가상 데모 seed를 넣지 않습니다. Spring 웹툰 카탈로그, 개인화 추천은 기존 ID/type 및 회원 이력 구조를 그대로 사용합니다.

## 검증된 공급자 ID CSV 가져오기

### 중단 후 이어서 실행하는 수집

승인된 API 키와 서비스 URL이 설정된 PowerShell 5.1에서 실행한다. 47개 진단 작품을 먼저 조회하고 기존 공식 링크 대조 목록 20개를 이어서 점검한다. 기본 요청 간격은 2초다. HTTP 429·5xx와 타임아웃에 한해 최대 두 번 재시도하며, 짧은 지수 백오프와 서버가 지정한 `Retry-After` 중 더 긴 값을 적용한다. 대기가 60초를 넘으면 중단하고 다음 실행에도 대기 종료 시각을 적용한다.

```powershell
Set-Location 'C:\Users\user\Downloads\ai_content_lab'
$python = 'C:\Users\user\AppData\Local\Programs\Python\Python314\python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_kmas_collection.ps1 -ApprovedApiCall -PythonExe $python -CheckpointDir .\.kmas-checkpoint -MaxRequests 100 -PrepareDatabase
```

중단 후 같은 명령을 재실행한다. 체크포인트에는 작품별 결과, 파싱한 페이지, 정제한 실패 사유, 모든 요청 시도의 예약과 대기 시간이 저장된다. 입력과 수집 옵션이 같으면 완료 작품과 저장된 페이지를 재사용한다. 요청 전 예약하므로 그 시점에 프로세스가 종료된 경우에도 해당 시도는 한도에 포함된다. 한 실행에 지정한 최대 요청 수와 같은 체크포인트 디렉터리의 한국 날짜 기준 누적 한도를 모두 적용한다. 다른 프로그램에서 사용한 요청은 이 원장에 없으므로, 같은 키를 다른 프로그램에서도 쓰면 그 사용량을 고려해 `-DailyLimit`을 낮춘다.

제목 조회에서 공식 ID가 계속 누락되면 같은 체크포인트 디렉터리로 `-CatalogScan`을 추가해 공식 목록에서 동일한 67개를 대조한다. 목록의 페이지 총계가 바뀌면 해당 실행은 중단된다. 목록을 처음부터 다시 확인할 때는 같은 디렉터리에 `-CheckpointBatch refresh1`을 추가하고, 그 실행을 이어갈 때도 같은 이름을 쓴다. 새 배치도 기존 요청 한도와 대기 원장을 사용한다.

개별 확인기의 목록 모드에 `-CatalogStartDate YYYY-MM-DD -CatalogEndDate YYYY-MM-DD`를 지정하면 공식 등록일 범위 조건을 적용한다. 제목 검색의 실응답에서는 `pageNo`가 행 오프셋으로 동작해 페이지당 100건에 대해 0, 100, 200 순으로 조회한다.

`Pending`이 0이면 현재 CSV를 Stage한다. `-PrepareDatabase`를 지정했고 검증된 후보가 있으면 읽기 전용 DryRun과 대상 행 검토 백업의 체크섬 검증을 이어서 실행한다. DB 쓰기에 앞서 출력에 나온 `OutputCsv`와 `DryRunReport`를 검토한다. 실제 Apply는 별도 승인 후 아래 절차에 따라 새 커밋 직전 백업 경로를 지정해 실행한다. 체크포인트, CSV, 검토 백업을 Git에 올리지 않는다. 설명·표지 출처를 수집하려면 각각의 사용 권한을 확인한 뒤에만 `-IncludeSynopsis`, `-IncludeCoverSource`를 추가한다.

### 개별 검증과 적용

#### 네이버웹툰 공식 작품 페이지 기반 등록

KMAS `mastrId`가 빠진 응답은 KMAS 공식 ID 연동에서 계속 제외한다. 네이버웹툰 공식 페이지에서 제목과 작가를 대조한 작품은 `(naver_webtoon, titleId)`를 외부 식별자로 등록할 수 있다. 공식 URL과 검토 원본 참조는 Stage 보고서에 기록한다. 내부 ID는 공급자와 외부 ID로부터 결정하며 기존 외부 매핑이 있으면 같은 내부 ID를 재사용한다. 공식 페이지 근거가 부족한 작품, 동명 또는 공식 URL이 기존 레코드와 충돌하는 작품은 검토 대상으로 남긴다.

KMAS `mastrId`는 KMAS 쪽 연동에 가장 직접적인 식별자다. 저장한 제목 조회 페이지 50개의 행 677개에서는 `mastrId`와 `listSeCd`를 확인하지 못했다. 체크포인트에는 응답의 일부 필드만 남아 있으므로 원본의 미저장 필드까지 확인된 상태는 아니다. KMAS 공개 아카이브 URL은 별도 검토 근거로 활용할 수 있다. 같은 작품의 네이버웹툰과 네이버시리즈가 서로 다른 아카이브 레코드에 나타나므로 아카이브 번호를 `mastrId`나 다른 플랫폼의 작품 번호로 전용하지 않는다.

네이버웹툰의 공개 작품 페이지와 플랫폼 ID는 링크 검증과 중복 방지에 사용할 수 있고, 내부 ID는 회원 활동에 필요한 참조를 유지한다. 검증 매니페스트는 출처를 재검토하는 비용을 줄이지만 플랫폼 또는 제공 업체의 전체 카탈로그를 대체하지는 않는다. 이 경로에서 가져오는 데이터는 작품 제목·작가·확인된 장르·공식 링크로 제한하며, 표지와 줄거리는 저장하지 않는다. 장르 근거가 없는 작품은 장르 필드를 비워 둔다.

```powershell
$python = 'C:\Users\user\AppData\Local\Programs\Python\Python314\python.exe'
$stamp = Get-Date -Format yyyyMMdd-HHmmss
$evidence = @(
    '--naver-evidence', 'contentlab/src/main/resources/static/webtoon-official-links.js',
    '--genre-evidence', '.env.kmas-18083-catalog.json',
    '--naver-reviewed-additions', 'scripts/naver_verified_webtoon_evidence.json'
)
$review = ".\.kmas-checkpoint\naver-$stamp-dryrun.json"
& $python -m kmas_staging_import Stage @evidence --report ".\.kmas-checkpoint\naver-$stamp-stage.json"
& $python -m kmas_staging_import DryRun @evidence --report $review
& $python -m kmas_staging_import ReviewBackup @evidence --report $review --backup ".\.kmas-checkpoint\naver-$stamp-review-backup.json"
```

승인된 DB 쓰기는 같은 증거 파일과 DryRun을 사용하고 새 커밋 직전 백업 파일을 생성한다.

```powershell
& $python -m kmas_staging_import Apply @evidence --report $review --backup ".\.kmas-checkpoint\naver-$stamp-before-apply.json" --approved-db-write
```

향후 KMAS가 공식 ID를 제공하면 검증된 교차 매핑을 검토한 뒤 기존 내부 ID에 `kmas` 보조 매핑을 추가할 수 있다. 기본 출처와 내부 ID가 그대로이므로 기존 찜·평가·이력 참조를 유지할 수 있다. 같은 공급자에 임시 식별자가 이미 매핑된 경우에는 공급자별 유일성 제약이 적용되므로 별도 검토가 필요하다.

`WEBTOON_GEMINI_REASON_SELECTION=true`를 명시하면 웹툰 추천에서 Gemini가 검증된 설명 후보의 순번을 선택한다. 순위·점수·후보는 기존 결정적 로직이 정하며, 모델에는 설명 후보와 작품 제목만 전달한다. 응답이 유효하지 않거나 호출이 실패하면 기본 설명을 사용한다. 기본값에서는 웹툰 경로의 Gemini 호출이 비활성이다.

기존 진단 CSV에서 확인한 제목·작가·장르는 조회 단서로 사용한다. 공식 응답의 `mastrId`와 웹툰 구분 코드가 검증된 해소 CSV를 받은 후 아래 절차를 사용한다. 기존 제목 검색의 `title-search:` 식별자가 있는 작품은 제목만으로 이동하거나 병합하면 회원의 찜·평가·이력 참조가 바뀔 수 있으므로 DryRun에서 검토 대상으로 표시한다.

Windows PowerShell 5.1에서 승인된 `KMAS_API_KEY`와 `KMAS_API_BASE_URL`을 주입한 뒤 다음 명령으로 해소 CSV를 만든다. 제목 검색이 공식 ID나 웹툰 구분 코드를 반환하지 않으면 행은 `BLOCKED`로 남는다. 공식 전체 목록을 조회하려면 남은 일일 요청량을 확인한 뒤 같은 명령에 `-CatalogScan -MaxRequests`와 허용할 요청 수를 추가하고 새 출력 파일을 사용한다.

```powershell
Set-Location 'C:\Users\user\Downloads\ai_content_lab'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\resolve_kmas_ids.ps1 -Live -InputCsv .\kmas_import_readiness_20261124_003620_c6277259.csv -OutputCsv .\kmas_id_resolution_20261124.csv
```

```powershell
Set-Location 'C:\Users\user\Downloads\ai_content_lab'
$contentlabPython = 'C:\Users\user\AppData\Local\Programs\Python\Python314\python.exe'
$kmasStamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$kmasResolution = '.\kmas_id_resolution_20261124.csv'
$kmasReview = ".\kmas_db_dryrun_${kmasStamp}.json"
& $contentlabPython -m kmas_staging_import Stage --resolution $kmasResolution --report ".\kmas_stage_${kmasStamp}.json"
& $contentlabPython -m kmas_staging_import DryRun --resolution $kmasResolution --report $kmasReview
```

`Stage`는 CSV만 읽고 검증 통과 수, 누락 필드, 제외 이유를 보고한다. `DryRun`은 `DB_*` 환경의 MySQL에 읽기 전용 트랜잭션을 열어 스키마, 공급자 ID, 내부 ID, 기존 제목 충돌을 확인한다. 입력과 DB 상태가 들어 있는 새 보고서 파일이 생성된다. 설명·표지 공개는 기존 `KMAS_SYNOPSIS_DISPLAY_ALLOWED`, `KMAS_COVER_DISPLAY_ALLOWED`에 따른다. 필드가 비어 있으면 기존 적재 데이터의 해당 값을 보존한다.

새로 배정하는 내부 작품 ID는 Chromium에서 정밀하게 처리할 수 있는 정수 범위를 사용한다. 이미 매핑된 공급자 ID는 해당 내부 ID를 다시 사용한다.

실제 쓰기 승인 후 같은 PowerShell 세션에서 다음을 실행한다. `Apply`는 동일한 입력, DB, DB 상태, 표시 권한과 충돌 없는 DryRun을 요구한다. DB 잠금 아래 대상 콘텐츠, 공급자 매핑, 웹툰 메타데이터의 변경 전 상태를 신규 JSON 백업에 기록하고 체크섬을 확인한 다음, 공급자 ID 기준으로 트랜잭션을 커밋한다. 백업은 해당 작품의 롤백 판단 자료이며 전체 DB 덤프와 복원 도구는 별도다. 백업과 보고서는 Git에 추가하지 않으며, 대상 DB 전체 백업이 필요한 환경에서는 별도의 승인된 백업 절차를 먼저 사용한다.

```powershell
& $contentlabPython -m kmas_staging_import Apply --resolution $kmasResolution --report $kmasReview --backup ".\kmas_catalog_before_${kmasStamp}.json" --approved-db-write
```

## 데이터·권리 경계

`mastrId`는 KMAS 내부 외부 ID로 보존하며 플랫폼 작품 ID나 공식 작품 URL로 취급하지 않습니다. 문서에서 웹툰 플랫폼 공식 URL 필드가 확인되지 않아 `official_url`은 비워 둡니다. 작가와 장르는 추천용 메타데이터로 저장합니다. 줄거리 화면 노출은 `KMAS_SYNOPSIS_DISPLAY_ALLOWED=true`, 표지 URL 공개는 `KMAS_COVER_DISPLAY_ALLOWED=true`를 각각 권리 확인 후 설정할 때만 허용됩니다. 기본값은 둘 다 false이며, 표지는 파일로 복제하지 않습니다. API 접근 승인과 저작물 표시/저장 권한은 별도 확인 사항입니다.

### 제목으로 선별 적재

승인된 격리 DB를 가리키도록 설정한 뒤 정확한 제목마다 `--title`을 지정합니다.

```powershell
py -m kmas_webtoon_provider --title "기기괴괴" --title "신의 탑"
```

제목마다 1회 조회하고 `KMAS_MAX_PAGES`만큼 실행할 수 있습니다. 전량이 한 페이지에 있어야 하며, 응답이 불완전하면 해당 실행에서 작품을 저장하지 않습니다. 정확히 일치하는 연재작을 한 건으로 특정할 수 없으면 그 제목을 건너뜁니다. 검증을 통과한 작품은 정규화한 제목과 작가로 만든 기존 `title-search:` 식별자를 사용해 한 번에 저장합니다. 줄거리와 표지 링크는 이 경로에서 수집하지 않습니다.

제목 검색은 기본 웹툰 스키마와 `V20261122_01__kmas_daily_usage.sql`을 요구합니다. 기존 18083의 선별 적재는 일일 사용량 테이블 없이 수행됐으므로 새 명령을 사용하기 전 해당 테이블을 확인해야 합니다. 제목 검색 경로에서는 표지 출처 열이 선택 사항입니다.

## 공식 작품 페이지 연결

18083에서 제목·작가·플랫폼을 공식 작품 페이지와 대조한 20건을 `webtoon-official-links.js`에 기록했습니다. 연결에는 KMAS 공급자와 외부 ID를 사용하며, 런타임에 제목·작가·플랫폼이 검토 기록과 일치해야 합니다. 레지스트리에는 검증 상태, 검토 당시 카탈로그 식별 정보, 공식 페이지 표기 작가와 목적지를 넣습니다. 검증 기록이 없거나 작품 식별 정보가 달라지면 버튼이 숨겨집니다.

| KMAS 작품명 | KMAS 작가 · 플랫폼 | 공식 대조 및 링크 | 상태 |
| --- | --- | --- | --- |
| 기기괴괴 | 오성대 · 네이버웹툰 | [네이버웹툰](https://m.comic.naver.com/webtoon/list?titleId=557672) | 일치 |
| 테러맨 | 한동우·고진호 · 네이버웹툰 | [네이버웹툰](https://m.comic.naver.com/webtoon/list?titleId=670149) | 일치 |
| 갓 오브 하이스쿨 | 박용제 · 네이버웹툰 | [네이버웹툰](https://m.comic.naver.com/webtoon/list?titleId=318995) | 일치 |
| 서울역 네크로맨서 | 신지훈·지성웅 · 카카오페이지 | [카카오웹툰](https://webtoon.kakao.com/content/서울역-네크로맨서/2813), 신지훈·지성웅·진설우 표기 | 일치 |
| 후레자식 | 김칸비(팀 겟네임)·황영찬 · 네이버웹툰 | [네이버웹툰](https://m.comic.naver.com/webtoon/list?titleId=628997), [공식 작가 목록](https://m.comic.naver.com/curation/list?id=93&type=ARTIST)에서 작가 일치, 상세는 로그인·연령 확인 | 일치 |
| 참교육 | 채용택·한가람 · 네이버웹툰 | [네이버웹툰](https://m.comic.naver.com/webtoon/list?titleId=758037) | 일치 |
| 외모지상주의 | 박태준 · 네이버웹툰 | [네이버웹툰](https://m.comic.naver.com/webtoon/list?titleId=641253) | 일치 |
| 하이브 | 김규삼 · 네이버웹툰 | [공식 1~2부](https://m.comic.naver.com/webtoon/list?titleId=609480)에 연결, [3부](https://m.comic.naver.com/webtoon/list?titleId=675331)는 별도 페이지 | 일치, 시즌 범위 표시 |
| 복학왕 | 기안84 · 네이버웹툰 | [네이버웹툰](https://m.comic.naver.com/webtoon/list?titleId=626907) | 일치 |
| 부활남 | 김재한·채용택 · 네이버웹툰 | [네이버웹툰](https://m.comic.naver.com/webtoon/list?titleId=670139), 채용택·김재한으로 표기 | 일치 |
| 세기말 풋사과 보습학원 | 순끼 · 네이버웹툰 | [네이버웹툰](https://m.comic.naver.com/webtoon/list?titleId=761722) | 일치 |
| 유미의 세포들 | 이동건 · 네이버웹툰 | [네이버웹툰](https://m.comic.naver.com/webtoon/list?titleId=651673) | 일치 |
| 소녀의 세계 | 모랑지 · 네이버웹툰 | [네이버웹툰](https://m.comic.naver.com/webtoon/list?titleId=654774) | 일치 |
| 경이로운 소문 | 장이 · 다음웹툰 | [현재 카카오웹툰](https://webtoon.kakao.com/content/경이로운-소문/1525) | 일치 |
| 돼지우리 | 오름미디어 · 탑툰 | [탑툰](https://toptoon.com/comic/ep_list/pigpen), 김칸비·천범식의 [네이버웹툰 동명작](https://m.comic.naver.com/webtoon/list?titleId=724854)과 별개 | 일치, 동명작 분리 |
| 심연의 하늘 | 윤인완·김선희 · 네이버웹툰 | [공식 시즌 1~3](https://m.comic.naver.com/webtoon/list?titleId=608261)에 연결 | 일치, 시즌 범위 표시 |
| 신의 탑 | SIU · 네이버웹툰 | [네이버웹툰](https://m.comic.naver.com/webtoon/list?titleId=183559) | 일치 |
| 연애혁명 | 232 · 네이버웹툰 | [네이버웹툰](https://m.comic.naver.com/webtoon/list?titleId=570503) | 일치 |
| 노블레스 | 손제호·이광수 · 네이버웹툰 | [네이버웹툰](https://m.comic.naver.com/webtoon/list?titleId=25455) | 일치 |
| 이번 생도 잘 부탁해 | 이혜 · 네이버웹툰 | [네이버웹툰](https://m.comic.naver.com/webtoon/list?titleId=746858) | 일치 |

검증 목록에 포함한 목적지는 공식 작품 상세 페이지입니다. QA API의 `officialUrl`과 MySQL의 `official_url`은 기존 값인 NULL을 유지합니다. 링크는 TOP 5와 상세에서 새 탭으로 열리며 `noopener noreferrer`를 적용합니다. 기존 대체 표지는 유지하고 외부 표지 파일은 연결하지 않습니다. 이전에 탭에 저장된 추천 결과에 공급자·외부 ID가 빠져 있으면 새 추천을 받은 뒤 링크가 표시됩니다.
