# CONTENT LAB 배포 준비

## 준비할 환경

- Spring Boot와 FastAPI는 각각 컨테이너로 실행한다. `compose.yaml`은 Spring Boot만 호스트 루프백에 공개하며 FastAPI는 컨테이너 네트워크에서 `ai:8000`으로 접근한다. 운영에서는 HTTPS 프록시 또는 플랫폼 인그레스를 Spring Boot에 연결한다. MySQL과 선택적 Redis는 서비스에서 접근 가능한 사설 엔드포인트를 사용한다.
- 로컬 소스 실행 절차는 [개발 가이드](AGENTS.md)를 따른다. Compose 및 운영 Spring 실행에는 `prod` 프로필을 사용한다. 환경 설정은 [.env.example](.env.example)에서 필요한 변수 이름을 확인해 비밀 저장소 또는 Git으로 관리하지 않는 별도 파일로 주입한다.
- 영화·TV 추천을 실제 생성으로 검증하려면 승인된 Gemini 계정, 사용 한도와 `GEMINI_API_KEY`를 준비하고 `CONTENTLAB_AI_MODE=gemini`를 설정한다. 비용 승인 전에는 `disabled`를 사용한다. 이 모드에서 웹툰은 로컬 점수를 계산하며 영화·TV 추천은 일시 사용 불가 응답을 반환한다. 모든 유형을 합성 데이터로 확인하려면 격리 브라우저 검사 환경의 모의 Gemini를 사용한다.
- 공개 카탈로그는 공급자와 작품별로 수집 근거, 제목·작가·설명·이미지 저장 및 표시 범위, 출처 표기와 갱신 조건을 확인하고 기록한다. 이용 권한이 확인된 데이터만 적재한다. 이미지 표시 권한이 없으면 해당 URL을 비워 포스터 대체 표시를 사용한다. 합성 카탈로그는 격리 DB에만 두고 시연 시 합성 데이터임을 표시한다.
- 네이버웹툰과 글로벌 WEBTOON의 공개 약관을 검토했다. 이 프로젝트에 웹툰 데이터 또는 표지의 재게시를 허용한 개별 계약은 확인되지 않았다. 공급자가 승인한 데이터 공급 방식과 외부 표시 범위가 확인되기 전에는 공개 카탈로그에 포함하지 않는다. [네이버웹툰 이용약관](https://member.webtoon.naver.com/policy/terms) · [WEBTOON 이용약관](https://www.webtoons.com/en/terms)

## MySQL 준비 및 마이그레이션

1. MySQL 8의 격리 스테이징 DB와 별도 실행 계정을 만든다. 기본 문자 집합은 `utf8mb4`를 사용한다. 스키마 작업은 별도 DDL 자격으로 실행한다. 운영 프로필에서 앱 시작 시 실행하던 기본 테이블 DDL은 꺼져 있다.
2. **신규 빈 스키마**에만 [기본 스키마](db/bootstrap/001_base_schema.sql)를 적용한다. 기존 스키마에서는 기본 스키마 적용을 건너뛴다. 기존 `contents(id,type)`와 `members(id)`의 데이터형, 인덱스, 스토리지 엔진, 문자열 collation을 웹툰 외래 키와 대조한다.
3. 미적용 상태를 확인한 뒤 [웹툰·취향 마이그레이션](db/migrations/V20261119_01__webtoon_catalog_and_taste.sql)을 한 번 적용한다. MySQL 클라이언트에서 대상 DB를 명시하고 비밀번호는 대화형 프롬프트로 입력한다. 다음은 저장소 루트에서 실행하는 격리용 예시다.

   ```powershell
   mysql --host=staging-db.example.invalid --port=3306 --user=contentlab_migrator --password --database=contentlab_staging
   ```

   ```sql
   SELECT DATABASE(), @@hostname, @@port;
   SOURCE db/bootstrap/001_base_schema.sql
   SOURCE db/migrations/V20261119_01__webtoon_catalog_and_taste.sql
   SHOW TABLES;
   ```

4. 적용 대상, 적용 파일, 실행 시각 및 결과를 릴리스 기록에 남긴다. MySQL DDL은 문장별로 반영되므로 실패 시 남은 테이블을 확인하고, 복원해 둔 별도 환경에서 수정 절차를 먼저 검증한다. 운영에는 승인된 백업과 복구 시험, 점검 시간, 적용 대상 대조를 거쳐 반영한다.
5. 승인된 카탈로그를 적재하고 JS 화면과 Java·Python의 카탈로그 읽기를 확인한다. Java 앱 계정에 기능에 필요한 DML을, Python 계정에는 조회 권한만 부여하는 구성을 운영에서 별도 주입할 수 있다. 편의상 Compose는 양쪽 컨테이너에 같은 스테이징 계정을 전달한다. 운영 실행 계정에 DDL 권한을 넣을 필요가 없다.

## 로컬 Compose 실행과 검증

1. [.env.example](.env.example)을 `.env.compose` 같은 Git 제외 파일로 복사한다. 지정한 호스트가 컨테이너에서 접근 가능하며 준비한 격리 DB와 일치하는지 확인한다. 기존 로컬 `.env`를 사용 중이면 새 파일을 선택한다. DB 비밀번호와 기존 승인 키 또는 새 격리용 Base64 JWT 서명 키는 실행 환경이나 별도 파일로 주입한다. 리터럴 달러 기호를 포함하는 Compose 환경 파일 값은 작은따옴표로 감싼다. [Docker 환경 변수 인용 규칙](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/#env-file-syntax)
2. 저장소 루트에서 `start_local.bat .env.compose`로 시작하고 [로컬 웹 화면](http://127.0.0.1:18080/)을 연다. 종료 시 같은 파일로 `stop_local.bat .env.compose`를 실행한다. 원클릭 스크립트는 작업 폴더별 Compose 프로젝트 이름을 사용하며 시작 시 화면에 표시한다. `CONTENTLAB_WEB_PORT`를 지정한 경우 아래 점검 URL에도 해당 포트를 적용한다.

   ```powershell
   docker compose --env-file .env.compose config --quiet
   curl.exe --fail --silent http://127.0.0.1:18080/api/health
   curl.exe --fail --silent http://127.0.0.1:18080/api/contents/count
   curl.exe --fail --silent "http://127.0.0.1:18080/api/webtoons?page=1&size=1"
   ```

3. 웹과 AI 상태 체크는 프로세스의 HTTP 응답을 검사한다. 위 카탈로그 점검은 MySQL 읽기와 웹툰 스키마 준비 상태를 별도로 확인한다. Spring과 Uvicorn 로그는 표준 출력으로 수집하며 Compose는 서비스당 10MB의 로그 파일을 최대 3개 유지한다. 상태 조회는 `docker compose -p <표시된-프로젝트> --env-file .env.compose ps`, 최근 로그는 같은 옵션에 `logs --tail 100 web ai`를 붙인다. 비밀이 포함된 전체 Compose 설정이나 컨테이너 환경은 출력하지 않는다.
4. Redis를 검증할 때만 `CONTENTLAB_CACHE_ENABLED=true`와 `SPRING_DATA_REDIS_URL`을 주입한다. 제한된 격리 Redis에서 목록·상세 캐시와 캐시 장애 시 DB 조회를 확인하고, 운영에서는 인증과 TLS가 설정된 사설 연결을 사용한다.
5. 운영 MySQL에는 서버 이름을 검증하는 TLS를 구성한다. Java JDBC URL에 `?sslMode=VERIFY_IDENTITY`를 붙이고 신뢰할 CA를 Java 신뢰 저장소에 제공한다. Compose에서 JDBC URL 접미사는 `CONTENTLAB_JDBC_PARAMS`로 지정할 수 있다. Python에는 컨테이너에서 읽을 수 있는 CA 번들의 경로를 `DB_SSL_CA`로 주입한다. 사설 CA를 쓰는 경우 플랫폼에서 읽기 전용으로 제공한다. 각 클라이언트가 잘못된 이름이나 신뢰되지 않은 인증서를 거절하는지 스테이징에서 확인한다.

## 운영 반영과 롤백

1. 승인된 스테이징 환경에서 Java·Python 이미지를 빌드하고 이미지 검사 및 SBOM을 생성한다. 승인된 레지스트리에 올린 두 이미지의 다이제스트와 현재 서비스의 이전 다이제스트를 릴리스 기록에 남긴다. 스테이징의 HTTP, 회원 전체 흐름, 캐시 설정, TLS와 인증을 확인한다.
2. 운영 반영 승인 후, 마이그레이션 대상 DB와 백업을 대조한다. 필요 시 승인된 DDL을 별도로 적용한 뒤 서비스의 런타임 계정과 비밀 저장소를 연결한다. Spring Boot에만 HTTPS 인그레스와 요청 제한을 적용하고 FastAPI, MySQL, Redis는 사설 네트워크에 둔다. SSO나 별도 도메인을 계획하면 인증과 CORS 범위를 다시 검토한다.
3. 검증된 다이제스트로 새 버전을 기동한다. Compose가 배포 실행기라면 `CONTENTLAB_WEB_IMAGE`, `CONTENTLAB_AI_IMAGE`에 승인된 이미지를 지정하고, 운영 프로젝트·환경 옵션과 함께 `docker compose up -d --no-build --wait`를 실행한다. Compose의 공개 주소는 루프백이다. 같은 호스트의 HTTPS 프록시가 이 포트를 사용하도록 구성하거나 플랫폼 내부 네트워킹을 사용한다.
4. 건강 상태와 HTTP 오류율을 관측하고 격리 계정으로 로그인·추천·기록 조회를 확인한다. 추천 요청에 실제 Gemini 생성이 포함되면 그 단계에서 별도로 승인된 범위만 실행한다.
5. 애플리케이션 문제가 확인되면 직전 Java·Python 이미지 다이제스트와 이전 환경 구성을 재적용하고 같은 상태·기능 점검을 수행한다. 사용자의 세션을 유지하려면 승인된 기존 JWT 키를 계속 사용한다. 추가형 웹툰 테이블은 이전 코드의 호환성을 스테이징에서 확인한 뒤 유지한다. DB 복구가 필요하면 롤백 승인과 별도 복구본 검증을 거치고 쓰기 중단 시점과 데이터 보존 범위를 확정한다.

## 공개 전 스테이징 보안 확인

- 브라우저와 Spring API는 같은 출처를 사용한다. FastAPI 포트와 MySQL·Redis에 외부에서 직접 연결할 수 없는지 확인한다. HTTPS 프록시의 TLS, HSTS, 요청 본문 크기와 시간 제한을 실제 공개 URL에서 검사한다.
- 가입·로그인에는 계정·주소별 요청 제한을, 추천에는 회원별 요청 제한과 모델 사용 한도를 적용해 테스트한다. 특히 가입의 기존 계정 응답이 이메일 존재 여부를 드러내는 문제를 배포 범위에 맞춰 판단한다.
- 현재 JWT는 브라우저의 `localStorage`에 저장된다. 로그아웃은 브라우저의 토큰을 제거하며 발급된 토큰은 자체 만료까지 유효하다. 배포 전에 인라인 스크립트 및 이미지 출처와 호환되는 CSP를 스테이징에서 검증하고, 토큰 저장 방식과 서버 폐기 정책은 인증 계약 변경의 영향까지 검토한다.

참고 문서는 [Docker Compose 네트워킹](https://docs.docker.com/compose/how-tos/networking/), [환경 변수 보간](https://docs.docker.com/reference/compose-file/interpolation/), [서비스와 로그 설정](https://docs.docker.com/reference/compose-file/services/)이다.
