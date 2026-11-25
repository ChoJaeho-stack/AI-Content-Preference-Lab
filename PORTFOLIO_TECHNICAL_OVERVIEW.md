# AI CONTENT LAB — 포트폴리오 기술 개요

**검증 기록:** 2026-11-24 · **서비스 주소:** `http://127.0.0.1:8080`

## 제품 개요

영화, TV, 웹툰 카탈로그를 제공하고 현재 설문과 회원의 취향 신호를 이용해 추천하는 웹 서비스다. 영화·TV는 Python 추천 서비스의 후보 평가와 Gemini 설명 생성 경로를 사용한다. 웹툰은 확인된 출처·작품 특징을 이용한 결정적 추천 경로를 사용하고, 공식 표지 이용 권한이 확인되지 않은 작품에는 자체 대체 디자인을 명확히 표시한다.

## 시스템 구성

```text
Chromium browser
  └─ HTML / CSS / JavaScript
      └─ Spring Boot (Java 21)
          ├─ Static site, content APIs, authentication, member activity
          ├─ MySQL catalog and member data
          └─ FastAPI (Python)
              ├─ Candidate filtering and recommendation validation
              ├─ Gemini API for the movie / TV path
              └─ Deterministic metadata scoring for the webtoon path
```

Spring은 브라우저 계약, JWT 인증, 회원별 데이터 범위와 추천 기록을 담당한다. FastAPI는 콘텐츠 후보와 추천 처리를 맡는다. Redis는 선택 기능이며 로컬 기본값은 비활성화다.

## 기술 스택

| 구역 | 기술 |
| --- | --- |
| 웹·인증·API | Java 21, Spring Boot, Spring Security, Maven, JWT HttpOnly cookie |
| 추천 서비스 | Python, FastAPI, Google Gen AI SDK, `gemini-3.5-flash-lite` |
| 저장소 | MySQL 8.4, 선택적 Redis |
| UI·검증 | HTML, CSS, JavaScript, Chromium DevTools Protocol |

## API 설계 요약

| 용도 | 경로 | 인증 |
| --- | --- | --- |
| 상태 | `GET /api/health` | 공개 |
| 목록·검색·상세·유사 | `GET /api/contents`, `/api/contents/search`, `/api/contents/{type}/{id}`, `/api/contents/{type}/{id}/similar` | 공개 |
| 회원 인증 | `POST /api/auth/register`, `/api/auth/login`, `/api/auth/logout` | 로그인·로그아웃은 쿠키 발급/폐기 |
| 프로필 | `GET /api/me`, `/api/me/stats`, `/api/me/taste` 및 취향 하위 경로 | 회원 전용 |
| 찜 | `GET /api/favorites`, `POST|DELETE /api/favorites/{type}/{id}` | 회원 전용 |
| 추천·이력 | `POST /api/recommend`, `GET /api/history`, `DELETE /api/history/{id}` | 회원 경로는 JWT의 회원 ID로 범위 지정 |
| FastAPI 내부 | `GET /health`, `GET /contents/count`, `POST /recommend` | 로컬 내부 호출 |

콘텐츠 식별은 `(type, id)`를 함께 사용한다. 브라우저가 전달한 회원 ID를 신뢰하지 않고, Spring이 인증된 JWT에서 회원 ID를 가져와 찜·평가·추천 이력 조회 및 저장에 사용한다.

## 데이터 모델

- `contents`: 영화·TV·웹툰 콘텐츠. 유형과 ID의 조합으로 작품을 구분한다.
- `content_external_ids`, `webtoon_metadata`: 공급자 외부 식별자, 플랫폼, 작품 메타데이터를 내부 카탈로그 ID와 분리한다.
- `members`: 회원 이메일과 암호화된 비밀번호 해시.
- `favorites`: 회원과 콘텐츠 유형·ID를 묶어 중복 찜을 방지한다.
- `member_content_ratings`, `member_taste_surveys`, `member_taste_profiles`, `member_content_feedback`: 평가와 설문·개인 취향 데이터.
- `recommendation_history`: 회원별 입력과 결과 기록.
- `revoked_auth_tokens`: 로그아웃된 JWT의 폐기 상태.

실DB 읽기 검증에서 카탈로그는 영화 591건, TV 603건, 웹툰 66건이었다. 이 중 웹툰 61건은 실제 네이버웹툰 데이터이며 개발용 행은 별도 출처 상태로 관리한다.

## 추천 흐름과 품질 제약

1. 현재 설문에서 선호·제외 신호와 콘텐츠 유형을 읽는다.
2. 유형, 사용자가 입력한 제외 요소, 기존에 좋아하는 작품 등을 적용해 후보를 걸러낸다.
3. 회원 추천은 Spring이 가져온 회원별 찜·평가·취향 및 최근 추천 신호를 FastAPI에 전달한다.
4. 영화·TV Gemini 응답은 실제 후보 카탈로그의 `(type, id)`와 대조하고, 중복·범위 밖 결과를 제외한다.
5. 웹툰은 검증된 장르·태그 기여도에 따라 점수와 근거를 계산한다. 후보가 모자라면 허구 작품으로 채우지 않는다.

Gemini는 후보를 검증된 카탈로그 밖으로 확장할 수 없다. 웹툰 경로는 Gemini가 확인되지 않은 메타데이터를 생성하지 않도록 로컬 결정적 점수를 사용한다.

## 검증 결과 스냅샷

| 검증 | 결과 |
| --- | --- |
| Java 전체 Maven 테스트 | 61건, 실패 0, 오류 0, 건너뜀 9 |
| Python 전체 단위 테스트 | 60건 통과 |
| Spring–FastAPI 회원 종단 간 | 별도 격리 E2E에서 찜·회원별 추천/이력·평가·로그인 쿠키 경로 검증. 4건 통과 |
| 합성 데이터 실제 Gemini | 격리 fixture로 생성 1회 성공, Spring 추천 이력 저장 확인 |
| 실DB TV Gemini | 실제 DB 후보 3건 반환, `tv` 유형·후보 ID 검증 통과. PowerShell 네이티브 파이프의 한글 출력 인코딩으로 제목 로그는 판독 불가 |
| 실DB 영화 Gemini | 승인된 재시도 포함 총 2회 시도, 모두 upstream HTTP 503. SDK/테스트에서 각 시도는 단일 생성 요청으로 제한했고 추가 재시도는 중단 |
| 실제 서비스 Chromium | 게스트 웹툰 TOP 5, 5가지 설문 변화, 공포 제외, 상세·공식 링크, PC·모바일, 브라우저 오류 0건. 새 Chrome 세션 2회 통과 |
| 격리 QA 회원 Chromium | 실제 Chrome 회원가입, HttpOnly 쿠키, 재시작 후 로그인 복원, 찜·평가·추천 기록 복원, 로그아웃, 세션 쿠키 만료 통과. 합성 회원과 활동만 전용 QA DB에 저장 |
| 실DB 카탈로그/API | Spring·FastAPI health 성공, 전체 1,260건, 영화 591·TV 603·웹툰 66 |
| 독립 QA DB | 20 KMAS + 30 합성 작품, 공급자 연결 30건, 로컬 대체 표지 29 SVG + 1 PNG, 메타데이터 누락 0건 |

### Maven 기본 실행에서 건너뛴 9건

건너뜀은 테스트 실패가 아니다. 기본 전체 실행에서 환경 변수로 opt-in하는 실제 통합 테스트를 비활성화했기 때문이다.

- Redis + MySQL 읽기 통합 1건: `CONTENTLAB_REDIS_INTEGRATION_TEST=true` 및 전용 Redis `127.0.0.1:16379` 필요.
- Spring 회원 E2E 5건: `CONTENTLAB_RECOMMEND_E2E=true` 및 격리 MySQL/FastAPI 필요. 별도 실행에서는 4건 통과했고 Gemini 1건은 live 전용 변수로 별도 검증했다.
- 유사 콘텐츠 벤치마크 1건: `CONTENTLAB_SIMILAR_BENCHMARK=true` 및 빈 Redis 논리 DB 4 필요.
- 취향 프로필 MySQL 통합 1건: `CONTENTLAB_TASTE_MYSQL_TEST=true`와 빈 전용 DB `contentlab_taste_test` 및 별도 암호 필요.
- 웹툰 Redis 통합 1건: `CONTENTLAB_WEBTOON_REDIS_TEST=true` 및 전용 Redis 필요.

## 이번 추가 검증의 미완료 범위

- 기존 MySQL에 QA 이메일 형태의 계정 12개가 있었지만 재사용 가능한 암호를 찾지 못했다. 기존 실DB 회원 테스트 스크립트는 신규 계정을 영구 생성하고 정리하지 않아 실행하지 않았다.
- 기존 MySQL의 QA 계정 암호는 찾지 못했다. 대신 기존 `.env.webtoon-final-qa` 설정으로 분리된 QA 프로젝트를 새 빌드 없이 재가동해 Chrome 회원 흐름을 검증했다. 테스트 회원·활동은 이 격리 DB에만 추가했다.
- 실DB 영화 Gemini 추천은 재시도 포함 2회가 HTTP 503으로 끝났다. 모델/공급자 쪽 원문 오류는 민감한 응답을 출력하지 않는 방식으로 제한되어 있어 세부 원인을 확정할 수 없다. 추가 호출은 하지 않았다. API 계정의 무료 할당량/결제 여부도 로컬에서 확인할 수 없다.
- 실DB 드라마 Gemini 호출은 후보 3건과 카탈로그 ID/유형 검증에 성공했으나 Windows 터미널 출력 인코딩 때문에 제목을 QA 로그에서 판독할 수 없었다.
- 기존 독립 DB 검증 스크립트의 예상값이 예전 30건 DB에 고정되어 있어 현재 50건(20 KMAS + 30 합성) 구성에 맞게 기대값만 수정하고 재검증했다.
- 본 문서는 로컬 개발 검증을 기록한다. 외부 배포, 실사용자 트래픽, 물리 모바일 기기, 유료 할당량 상태는 검증하지 않았다.

## 주요 문제 해결 사례

1. 정적 페이지와 게스트 추천이 JWT 인증에 막히는 문제를 공개 경로와 회원 전용 경로로 나눠 확인했다. 공개 리소스는 로그인 없이 제공하면서 회원 API에는 인증을 유지했다.
2. 추천 점수가 모두 중립으로 표시되는 문제를 UI 레이블이 아니라 입력 전달, 후보 필터, 메타데이터 기여도와 응답 검증 흐름에서 조사했다. 실제 브라우저 설문에서 결과 순위와 웹툰 점수가 달라지는 것을 확인했다.
3. 공급자 ID와 내부 콘텐츠 ID의 의미를 분리해 작품 식별과 중복 처리에 사용했다. 제목만으로 자동 병합하지 않으며 검증되지 않은 웹툰 데이터는 추천 후보에서 제외한다.
4. 포스터가 없는 웹툰은 공식 표지를 임의로 복사하지 않고, 2:3 비율을 맞춘 로컬 대체 디자인과 대체 표기 상태를 표시한다.
5. Spring 테스트가 로컬 Maven 저장소 확인 단계에서 막히는 문제를 테스트 복사본과 프로젝트 `.maven-cache`를 사용해 격리했다. 실제 서버 동작은 테스트 후 health와 카탈로그로 재확인했다.

## 로컬 실행

프로젝트 루트에서 FastAPI:

```powershell
py -m uvicorn ai_server:app --host 127.0.0.1 --port 8000 --env-file .env
```

새 PowerShell에서 Spring:

```powershell
Set-Location contentlab
.\mvnw.cmd spring-boot:run
```

기존 `.env`, DB 비밀번호, JWT 키, Gemini 키는 저장소에 기록하지 말고 환경별 비밀 설정으로 관리한다.

## 발표 시 설명할 핵심

- **인증 경계:** 회원 ID를 클라이언트가 아니라 JWT에서 결정하는 이유와 HttpOnly 쿠키·로그아웃 토큰 폐기 흐름.
- **작품 식별:** 공급자 ID와 `(type, id)` 내부 키의 역할 차이, 동명이작과 콘텐츠 유형 충돌 방지.
- **추천 검증:** 현재 제외 조건을 우선하는 이유, Gemini 결과를 후보 카탈로그에 재대조하는 이유, 후보 부족 시 가짜 추천을 만들지 않는 정책.
- **테스트 격리:** 실제 MySQL을 읽는 검증과 임시 테이블 통합 테스트, opt-in Redis·전용 DB 테스트를 나누는 방법.
- **현재 한계:** 실DB 영화 Gemini 503, 격리 Docker 환경 미가동, 실서비스 Chrome 회원 플로우 미검증을 숨기지 않고 다음 검증 조건과 함께 설명한다.

## 영화·TV Gemini 후보 제한 (2026-11-24)

Gemini 요청 직전에만 영화·TV 후보를 관련도 상위 40개로 제한한다. 현재 취향 태그 일치 수, 기존 알고리즘 점수(평점·장르·찜·최근 추천 신호), 개인화 점수 순으로 평가하고, 동점은 정규화 제목·유형·ID로 안정적으로 정렬한다. 앞쪽 행을 단순히 자르지 않는다. 이미 필터에서 제외된 콘텐츠는 shortlist에 들어가지 않으며, Gemini 응답도 전달한 shortlist의 `(type, id)`에 한정해 검증한다. 웹툰의 결정적 추천 경로는 수정하지 않았다.

실제 로컬 카탈로그를 읽는 FastAPI prompt builder에서 생성 요청을 모의 처리해 비교했다. 선호 입력이 없는 동일 조건에서 영화 591→40개, 302,154→20,346자 및 536,882→35,376 UTF-8 바이트; TV 603→40개, 240,268→13,838자 및 387,016→19,982 UTF-8 바이트였다. 요청 실패 시 503 재시도와 사용자 메시지 계약은 유지했다. 모의 Chrome은 영화 503 안내와 upstream 오류 본문 비노출을 확인했다. 실제 Gemini 호출은 하지 않았다.

변경 확인: Python 추천 테스트 6건 통과, Chrome 모의 503 브라우저 테스트 1건 통과. 전체 테스트 반복 및 Java 변경은 없었다.
## 실서비스 재검증 후 상태 (2026-11-24)

FastAPI만 기존 `.env`로 재시작했고, 런타임 프로세스와 HTTP health 및 로컬 카탈로그 조회가 정상임을 확인했다. 실제 Chrome에서 Spring 제공 페이지를 열고 회원 기록 변경 없이 FastAPI에 직접 연결해 영화·TV 추천을 각 1회 호출했다. 각각 HTTP 503과 동일한 일반 혼잡 안내를 받았으며 카드 결과는 없었다.

두 요청의 FastAPI 오류 유형은 `ConnectError`이고 provider HTTP status는 없었다. FastAPI 실행 샌드박스에서는 TCP 443 연결이 실패했지만, 별도의 네트워크 허용 DNS/TCP 진단에서는 연결됐다. 이는 샌드박스 네트워크 제한 가능성을 가리킨다. 앱 응답 503은 유지됐고, 실제 Gemini 서버가 보낸 503인지 확인되지 않았다. ConnectError는 기존 재시도 조건에 해당하지 않아 각 요청은 한 번만 시도됐다. 이 최초 확인 당시에는 Gemini 응답을 받지 못했고, 추가 호출 승인을 기다렸다. 승인 후 수행한 네트워크 허용 실제 Chrome 검증 결과는 아래 절에 기록했다. 본 Chrome 검증은 Spring 회원 이력 경로를 우회한 API/UI 연동이며 회원 기능 전체 E2E가 아니다.

후보 40개 제한은 영화·TV 경로에서만 적용되며 웹툰은 기존 조기 반환 경로를 유지한다. 재시작된 FastAPI와 Spring은 최종 확인 시 정상 응답했다.

## 실제 Gemini 최종 재검증 (2026-11-24)

최초 샌드박스 구동에서 발생한 `ConnectError`를 provider 503으로 오인하지 않도록 구분했다. TCP 443은 네트워크 허용 환경에서 성공했고, FastAPI를 해당 환경에서 재시작한 뒤 기존 `.env`로 실제 Chrome 요청을 수행했다. 승인 범위인 영화 1회와 TV 1회 모두 HTTP 200으로 끝났다. Chrome 화면은 영화 5개, TV 4개 카드를 렌더링했고 PC/모바일 각각 가로 넘침이 없었다. Gemini API는 각 유형의 실제 요청 경로에서 호출됐으며 이전 샌드박스 ConnectError는 외부 Gemini 503이 아니었다.

회원 이력에 쓰지 않도록 Chrome의 추천 요청만 FastAPI에 직접 연결했으므로 Spring 회원 추천 저장 경로는 이번 검증 범위 밖이다. 독립 read-only QA에서는 Spring/FastAPI health와 카탈로그 조회, access log를 다시 확인했다. access log의 POST 200은 세 건이지만 제어된 Chrome 하네스가 확인한 요청/응답은 두 건(영화·TV 각 1회)이라 나머지 한 건은 상관관계를 확인하지 못했다. 추가 API 호출 없이 종료했다. 기존 webtoon 테스트와 다른 성공 테스트는 반복하지 않았다.

## 2026-11-24 후속 독립 QA: 장르 표시와 Gemini 응답

- Spring/FastAPI를 실제 Chrome 및 읽기 전용 API 점검으로 확인했다. 사이트와 두 health endpoint는 HTTP 200, FastAPI 카탈로그 수는 1,260건이었다. DB 재확인 결과 영화 591, TV 603, 웹툰 66건이며, 임시 QA 계정 정리 뒤 회원 14, 찜 10, 추천 이력 27건 등 기존 기준값이 유지됐다.
- 실제 Gemini 영화·TV 추천은 Chrome에서 각 유형을 요청했으나 둘 다 provider `ServerError` HTTP 503으로 끝났다. UI는 일반적인 일시 혼잡 안내만 표시했고 추천 카드 및 해당 요청의 이력은 저장되지 않았다. 승인된 호출 범위가 소진되어 재시도하지 않았다. 따라서 이번에는 실 Gemini 추천의 순위·TOP 5·포스터를 검증할 결과가 없으며 외부 서비스의 가용성은 미해결이다.
- 별도 실제 Chrome 회원 QA에서는 가입·로그인·쿠키 유지·찜·평가·웹툰 TOP 5·이력·로그아웃이 통과했다. 찜 화면에서 영화 장르 `드라마`, 웹툰 장르 `로맨스` 및 두 표지 영역의 50×75 크기를 PC·모바일에서 확인했고, 로그아웃 뒤 회원 API는 401을 반환했다. QA 회원과 그 회원의 테스트 행만 정리했다.
- movie/TV API 응답의 `genre_ids`를 카드 표시 허용 필드에 포함하고, 추천 응답에도 원본 카탈로그 장르 ID를 전달한다. 변경 후 Python 집중 테스트 1건 및 Chrome 모의 카드 검사 통과 결과를 재사용했다. Java 회원 찜 집중 테스트는 1건 통과했다. 실제 FastAPI 프로세스는 이 변경을 포함하도록 재기동했으며 두 서버 health를 다시 확인했다.

## Gemini 장애 시 영화·드라마 DB fallback (2026-11-24)

- 원인: 직전 실제 제공자 로그에 Google GenAI SDK `ServerError`, code 503, status `UNAVAILABLE`이 기록됐고, FastAPI의 Gemini 호출 경로가 모든 생성 오류를 HTTP 503으로 변환해 추천을 끝냈다. 기존 영화·TV 로컬 점수 경로는 `CONTENTLAB_AI_MODE=local` 전용 QA 분기였으므로 운영 Gemini 모드에서는 재사용되지 않았다.
- 처리: Gemini의 429/5xx, 명시적 `UNAVAILABLE` 및 연결·시간초과 장애에 한해 영화·TV 요청을 기존 카탈로그 후보·제외 필터·개인 취향/장르 점수·평점·최근 추천 감점으로 로컬 재정렬한다. DB에서 확인한 실제 작품만 최대 5개 반환하고 포스터 URL, 장르 ID, 계산 점수와 이유를 보존한다. 불명확한 내부 예외나 잘못된 Gemini JSON은 fallback으로 감추지 않는다. 웹툰 경로는 바꾸지 않았다.
- API 응답에 `recommendation_source=local_fallback`을 넣는다. Spring은 추가 응답 필드를 보존해 회원 추천 기록 JSON에도 함께 저장한다. 화면과 기록 상세는 Gemini 장애로 자체 알고리즘을 사용했음을 표시한다.
- 검증: Python 집중 테스트 5건 통과(영화·TV별 503 fallback, 제외 조건, 후보 순위, 실제 포스터/장르 전달, 과부하 재시도 이후 fallback, 알 수 없는 내부 오류는 기존 오류 처리 유지). 실제 Chrome → Spring → FastAPI(503 주입) → MySQL 통합 확인에서 영화와 드라마 각 5개 카드, 점수·장르·표지, fallback 안내, 회원별 추천 기록의 출처 표식을 확인했다. 실제 Gemini는 호출하지 않았다. 임시 QA 회원과 해당 테스트 행은 제거했다.
- 독립 읽기 전용 QA에서 카탈로그 영화 591, TV 603, 웹툰 66건 및 기존 회원 14, 찜 10, 이력 27건을 재확인했다. Spring/FastAPI 상태와 사이트 응답은 HTTP 200이다. Java 전체 테스트와 실물 브라우저/Gemini 제공자 응답은 이번 변경에서 반복하지 않았다.

## Gemini TOP2·메타데이터·순위 회귀 수정 (2026-11-24)

- 코드 비교에서 세 원인을 확인했다. Gemini 결과 검증은 후보 40개 안의 ID만 허용했지만, 메타데이터를 원본 카탈로그 대신 점수 계산용 축약 후보에서 가져와 표지 URL과 장르 ID가 비었다. Gemini가 적합하다고 반환한 2건을 그대로 반환해 TOP2가 되었고, 정렬은 취향 점수보다 최근 추천 감점을 먼저 적용해 화면 점수와 순위가 달라질 수 있었다.
- 검증된 `(type,id)`를 허용 후보와 대조한 뒤 `catalog_by_key` 원본 행에서 제목·포스터·장르를 구성한다. Gemini가 5건 미만을 반환하면 제외 조건을 통과한 자체 점수 상위작을 중복 없이 보충한다. 보충 카드와 추천 이력에 출처를 저장하고 화면에 출처를 표시한다. 모든 경로의 최종 순위는 화면에 표시되는 `match_score` 내림차순이며, 점수가 같을 때만 취향 일치 신호·기존 알고리즘 점수·최근 추천 여부와 안정 키를 사용한다.
- 실제 MySQL에는 `파이널 테이블`(ID 316702)과 `이상한 변호사 우영우`(ID 197067)의 표지 URL과 장르 ID `[18]`가 존재한다. 실제 Chromium에서 로컬 DB를 연결하고 모의 Gemini가 이 두 행을 선택하도록 격리 실행해 각 카드의 표지·`드라마` 장르, 85%·90% 응답의 점수순 정렬, 5건 보충, 출처 안내와 이력 저장을 확인했다. 이 검사의 후보 한도 확장은 격리 프로세스에서 두 행의 메타데이터 경로만 확인하기 위한 QA 설정이며 제품 설정은 40개다. 별도의 실제 Gemini HTTP 503 주입 Chrome 검증에서도 영화·TV 각 5건, 출처 안내와 기록 저장을 확인했다.
- 집중 Python 테스트 5건, Python 문법 및 Chrome 스크립트 문법 검사가 통과했다. 운영 DB 카탈로그/회원 데이터를 삭제하거나 변경하지 않았다. 임시 QA 계정 데이터만 제거했다. 독립 읽기 전용 점검에서 영화 591, TV 603, 웹툰 66, 회원 14, 찜 10건을 확인했으며 추천 이력은 28건이었다. QA 계정이 아닌 새 이력은 삭제하지 않고 보존했다. Spring/FastAPI/메인 페이지는 HTTP 200이다.
- 실제 Gemini 생성 호출은 추가 비용 승인 전이므로 수행하지 않았다. 따라서 이번 성공 응답 경로의 브라우저 검증은 실제 DB와 Spring을 연결했지만 모델 응답만 모의했다. 실 provider 응답 확인은 승인 후 TV 1건, 단일 시도로 진행한다.

## 실제 Gemini 1회 확인 및 localhost 최종 상태 (2026-11-24)

사용자 승인으로 실제 Chrome 로그인 흐름에서 TV 추천 생성 요청 1건만 실행했다. FastAPI 프로세스의 재시도 한도를 1회로 제한했고 웹툰 보조 생성은 꺼 두었다. Google GenAI가 `ServerError` 503 / `UNAVAILABLE`을 반환했으며, 추가 시도 없이 FastAPI가 DB 자체 추천으로 전환했다. Spring은 HTTP 200과 추천 5건을 브라우저에 전달했고 카드 데이터·화면·회원 추천 이력이 일치했다. 이는 실제 Gemini 장애에서 fallback이 실행된 실서비스 연결 검증이다. 성공적인 실제 Gemini 응답은 이번에도 받지 못했다.

별도 모의 성공 응답 통합 QA에서는 2개 Gemini 결과(85%, 90%)를 표시 점수 순으로 재정렬하고 자체 점수 후보 3개를 보충했다. 원본 DB 행에서 표지·장르를 복원하여 `파이널 테이블`(316702), `이상한 변호사 우영우`(197067)의 URL과 장르 ID `[18]`를 실제 Chrome 카드에 표시했고, 두 항목을 포함한 5건과 출처 표식을 회원 추천 기록에 저장했다. 이 검증은 모델 호출을 모의한 것이며 유료 요청이 아니다.

실행 후 DB 읽기 전용 대조: 영화 591, TV 603, 웹툰 66, 회원 14, 찜 10, 추천 이력 28건. 임시 QA 회원의 행은 제거했고 QA 계정이 아닌 기존 이력은 보존했다. 메인 페이지, Spring 및 복원된 기본 설정 FastAPI health는 HTTP 200이다. 이 작업에서는 Java 파일을 바꾸지 않아 Maven 전체 테스트를 실행하지 않았다.

## Google GenAI 연결 오류의 자체 추천 전환 (2026-11-25)

실제 요청 로그에서 Google GenAI transport `ConnectError`가 FastAPI 503으로 바뀌고, Spring이 이를 사용자 혼잡 오류로 변환한 경로를 확인했다. SDK가 던진 클래스와 로컬 `httpx.ConnectError`가 동일 타입이 아니어서 기존 `isinstance` 판별을 우회했다. Gemini 호출 구간에서 `ConnectError` 클래스명을 일시적 upstream 연결 실패로 인식하게 수정해 영화·TV의 카탈로그 fallback으로 이어지도록 했다. 사용자 입력·회원 취향 필터, 후보 점수, 공포 제외 및 결과 정렬 로직은 변경하지 않았다.

집중 Python 회귀 테스트 2건 통과. 실제 MySQL 읽기 전용 카탈로그를 이용한 FastAPI TestClient 재현은 HTTP 200과 드라마 추천 5건을 반환했고 Gemini는 호출하지 않았다. 수정 적용을 위해 FastAPI만 재기동했고 Spring/FastAPI health는 모두 200이다. 실제 Chrome 회원 요청은 검증하지 않았다. Maven Central 연결 제한으로 Spring 클라이언트 단위 테스트는 실행 결과를 확인할 수 없었다.

## 단계형 취향 관련도 확장 (2026-11-25)

### 문제와 원인

TV 추천은 `contentType=tv`와 `preference=드라마`를 함께 받는다. 기존 subtype 필터가 TV 예능인 선호 작품과 그 특성이 맞는 예능 후보를 전부 제거해, MySQL에 저장된 `더 지니어스`가 있어도 `데블스 플랜` 선호에서 결과가 0건이었다. 로컬 fallback의 우선순위 정렬 방향도 반대로 적용되어 중요 특성이 직접 일치한 후보보다 약한 일반 후보가 앞에 올 수 있었다.

### 처리 흐름

1. 콘텐츠 유형, 명시적 비선호 장르·특성 제외를 먼저 적용한다. 이 조건은 관련도 확장에서 해제하지 않는다.
2. 검증 카탈로그에서 추출한 선호 태그가 직접 맞는 후보를 계산한다. `두뇌게임`, `전략`, `심리전`, `추리` 등 명시 특성은 넓은 장르 ID만 맞는 후보보다 우선한다.
3. 직접 후보가 부족할 때만 제한된 특성 관계표의 한 단계 이웃을 추가한다. 관계표는 태그 사이 관계만 표현하며 작품 제목이나 작품별 별칭을 두지 않는다.
4. 제시할 관련 후보가 없으면 5개를 강제로 채우지 않는다. Gemini 성공 응답, 자체 후보 보충 및 fallback 응답은 화면 점수 내림차순으로 반환한다.

### 실제 DB 읽기 전용 결과

FastAPI `TestClient`를 로컬 점수 모드로 호출했고 실제 로컬 MySQL 카탈로그를 읽었다. 영화 `기생충`은 5건(91, 73, 73, 73, 73점), TV `데블스 플랜`은 5건이며 첫 후보는 `더 지니어스`(93점), 이어 관련 경쟁·서바이벌 작품(71점)이었다. 웹툰 `화산귀환`은 근거가 확인된 4건(절대회귀 75, 광마회귀 72, 호랑이형님 55, 신의 탑 52점)을 반환했다. 공포 제외 조건, 점수 정렬, 이유 문구를 확인했다. 같은 TV 취향에 찜 작품을 전달했을 때 결과와 점수가 달라져 회원 취향 입력의 영향도 확인했다. 이 요청에는 Gemini 호출, DB 쓰기, 실제 Chrome 검증이 포함되지 않았다.

수정 후 `test_ai_server` 전체 38건이 통과했고 Python 구문 검사 및 `git diff --check`도 통과했다. 로컬 FastAPI를 코드 변경 반영을 위해 1회 재시작한 뒤 FastAPI·Spring·메인 페이지가 모두 HTTP 200임을 확인했다.
