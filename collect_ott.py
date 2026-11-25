import os
import json
import time
import threading
import requests

from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()
API_KEY = os.getenv("TMDB_API_KEY")

if not API_KEY:
    raise ValueError("TMDB_API_KEY가 없습니다.")

BASE = "https://api.themoviedb.org/3"

INPUT_FILE = "contents_expanded.json"
OUTPUT_FILE = "contents_with_ott.json"

MAX_WORKERS = 10
MAX_RETRIES = 3

start_time = time.time()
local = threading.local()

# 1. 원본 데이터 불러오기
with open(INPUT_FILE, encoding="utf-8") as f:
    contents = json.load(f)

# 2. 기존 수집 데이터 불러오기
cache = {}

if os.path.exists(OUTPUT_FILE):
    with open(OUTPUT_FILE, encoding="utf-8") as f:
        previous = json.load(f)

    for item in previous:
        if (
            item.get("ott_status") == "done"
            or (
                "ott_status" not in item
                and item.get("ott")
            )
        ):
            cache[(item["type"], item["id"])] = item["ott"]

# 3. OTT 이름 정리
def normalize_provider(name):
    name = name.lower()

    mapping = {
        "netflix": "넷플릭스",
        "tving": "티빙",
        "wavve": "웨이브",
        "coupang": "쿠팡플레이",
        "disney": "디즈니+",
        "watcha": "왓챠",
        "apple tv": "애플TV+",
        "amazon": "프라임 비디오",
        "laftel": "라프텔"
    }

    for key, value in mapping.items():
        if key in name:
            return value

    return None

# 4. 스레드별 HTTP 연결
def get_session():
    if not hasattr(local, "session"):
        local.session = requests.Session()

    return local.session

# 5. OTT 정보 조회 및 재시도
def fetch_ott(content):

    category = content["type"]
    content_id = content["id"]

    for attempt in range(MAX_RETRIES):

        try:
            response = get_session().get(
                f"{BASE}/{category}/{content_id}/watch/providers",
                params={"api_key": API_KEY},
                timeout=20
            )

            response.raise_for_status()

            data = response.json()
            kr = data.get("results", {}).get("KR", {})

            ott_list = set()

            for provider in kr.get("flatrate", []):
                name = normalize_provider(
                    provider.get("provider_name", "")
                )

                if name:
                    ott_list.add(name)

            return sorted(ott_list), "done"

        except requests.RequestException as e:

            print(
                f"[재시도 {attempt + 1}/{MAX_RETRIES}] "
                f"{content['title']}: {e}"
            )

            delay = 2 ** attempt

            if e.response is not None:
                retry_after = e.response.headers.get("Retry-After", "")

                if retry_after.isdigit():
                    delay = max(delay, int(retry_after))

            time.sleep(delay)

    return [], "failed"

# 6. 안전한 중간 저장
def save():
    temp_file = OUTPUT_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(
            contents, f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temp_file, OUTPUT_FILE)

# 7. 캐시 적용
pending = []

for content in contents:
    key = (content["type"], content["id"])

    if key in cache:
        content["ott"] = cache[key]
        content["ott_status"] = "done"
    else:
        content["ott_status"] = "pending"
        pending.append(content)

completed = len(contents) - len(pending)

print(f"전체 콘텐츠: {len(contents)}개")
print(f"기존 캐시: {completed}개")
print(f"신규 조회: {len(pending)}개")
print(f"동시 작업 수: {MAX_WORKERS}개")
print("=" * 50)

# 8. 멀티스레드 동시 처리
executor = ThreadPoolExecutor(
    max_workers=MAX_WORKERS
)

try:
    futures = {
        executor.submit(fetch_ott, content): content
        for content in pending
    }

    for future in as_completed(futures):

        content = futures[future]
        ott, status = future.result()

        content["ott"] = ott
        content["ott_status"] = status

        completed += 1

        print(
            f"[{completed}/{len(contents)}] "
            f"{content['title']} - "
            f"{', '.join(ott) or status}"
        )

        if completed % 20 == 0:
            save()

except KeyboardInterrupt:
    print("\n수집 중단 - 진행 상황 저장")

finally:
    save()
    executor.shutdown(
        wait=True,
        cancel_futures=True
    )

# 9. 성능 측정
elapsed = time.time() - start_time

success = sum(
    1 for c in contents if c.get("ott")
)

failed = sum(
    1 for c in contents
    if c.get("ott_status") == "failed"
)

remaining = sum(
    1 for c in contents
    if c.get("ott_status") == "pending"
)

print("\n===== 수집 결과 =====")
print(f"전체 콘텐츠: {len(contents)}개")
print(f"OTT 확인: {success}개")
print(f"조회 오류: {failed}개")
print(f"미처리: {remaining}개")
print(f"소요 시간: {elapsed:.2f}초")
print(f"소요 시간: {elapsed / 60:.2f}분")