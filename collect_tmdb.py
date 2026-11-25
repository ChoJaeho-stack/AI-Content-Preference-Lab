import os
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("TMDB_API_KEY")

if not API_KEY:
    raise ValueError("TMDB API 키가 없습니다.")

contents = []
seen = set()

MAX_PAGES = 30

for category in ["movie", "tv"]:

    url = f"https://api.themoviedb.org/3/discover/{category}"

    for page in range(1, MAX_PAGES + 1):

        params = {
            "api_key": API_KEY,
            "language": "ko-KR",
            "with_origin_country": "KR",
            "with_original_language": "ko",
            "sort_by": "popularity.desc",
            "page": page
        }

        response = requests.get(
            url, params=params, timeout=15
        )
        response.raise_for_status()

        data = response.json()
        results = data.get("results", [])

        if not results:
            break

        for item in results:

            key = (category, item["id"])

            if key in seen:
                continue

            genres = item.get("genre_ids", [])

            # 애니메이션 제외
            if 16 in genres:
                continue

            title = item.get("title") or item.get("name")

            poster_path = item.get("poster_path")

            poster_url = (
                f"https://image.tmdb.org/t/p/w500{poster_path}"
                if poster_path else None
            )

            contents.append({
                "id": item["id"],
                "type": category,
                "title": title,
                "genre_ids": genres,
                "overview": item.get("overview", ""),
                "rating": item.get("vote_average", 0),
                "popularity": item.get("popularity", 0),
                "poster_url": poster_url
            })

            seen.add(key)

        print(
            f"[{category}] {page}/{MAX_PAGES} 페이지 "
            f"| 누적 {len(contents)}개"
        )

        if page >= data.get("total_pages", 1):
            break

        time.sleep(0.3)

with open("contents_expanded.json", "w", encoding="utf-8") as f:
    json.dump(contents, f, ensure_ascii=False, indent=2)

print(f"\n수집 완료: {len(contents)}개")