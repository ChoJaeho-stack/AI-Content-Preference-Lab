import os
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("TMDB_API_KEY")

if not API_KEY:
    raise ValueError("TMDB API 키가 없습니다.")

FILE_NAME = "contents_expanded.json"

with open(FILE_NAME, encoding="utf-8") as f:
    contents = json.load(f)

seen = {(c["type"], c["id"]) for c in contents}

titles = [
    "데블스 플랜",
    "더 지니어스",
    "피의 게임",
    "대학전쟁",
    "소사이어티 게임",
    "여고추리반",
    "크라임씬",
    "대탈출",
    "미스터리 수사단",
    "더 인플루언서",
    "검은 양 게임",
    "더 타임 호텔",
    "더 커뮤니티",
    "머니게임",
    "공범",
    "제로섬게임",
    "보물찾기",
    "사상검증구역: 더 커뮤니티",
    "신세계로부터"
]

def normalize(text):
    return "".join(c for c in text.lower() if c.isalnum())

added = 0
failed = []

for title in titles:
    response = requests.get(
        "https://api.themoviedb.org/3/search/tv",
        params={
            "api_key": API_KEY,
            "language": "ko-KR",
            "query": title
        },
        timeout=15
    )

    response.raise_for_status()
    results = response.json().get("results", [])

    item = next(
        (
            r for r in results
            if normalize(title) in [
                normalize(r.get("name") or ""),
                normalize(r.get("original_name") or "")
            ]
            and "KR" in r.get("origin_country", [])
        ),
        None
    )

    if not item:
        failed.append(title)
        print(f"[검색 실패] {title}")
        continue

    key = ("tv", item["id"])

    if key in seen:
        print(f"[이미 존재] {title}")
        continue

    poster_path = item.get("poster_path")

    contents.append({
        "id": item["id"],
        "type": "tv",
        "title": item["name"],
        "genre_ids": item.get("genre_ids", []),
        "overview": item.get("overview", ""),
        "rating": item.get("vote_average", 0),
        "popularity": item.get("popularity", 0),
        "poster_url": (
            f"https://image.tmdb.org/t/p/w500{poster_path}"
            if poster_path else None
        )
    })

    seen.add(key)
    added += 1

    print(f"[추가 완료] {title}")

    time.sleep(0.3)

with open(FILE_NAME, "w", encoding="utf-8") as f:
    json.dump(contents, f, ensure_ascii=False, indent=2)

print(f"\n추가 수집: {added}개")
print(f"전체 콘텐츠: {len(contents)}개")
print(f"검색 실패: {failed}")