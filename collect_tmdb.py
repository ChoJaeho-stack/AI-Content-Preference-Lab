
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("TMDB_API_KEY")

if not API_KEY:
    raise ValueError("TMDB API 키가 없습니다.")

contents = []

for category in ["movie", "tv"]:
    url = f"https://api.themoviedb.org/3/discover/{category}"

    params = {
        "api_key": API_KEY,
        "language": "ko-KR",
        "with_origin_country": "KR",
        "with_original_language": "ko",
        "sort_by": "popularity.desc",
        "page": 1
    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()

    results = response.json().get("results", [])

    print(f"\n=== 한국 {category.upper()} ===")

    for item in results:
        title = item.get("title") or item.get("name")

        contents.append({
            "id": item["id"],
            "type": category,
            "title": title,
            "genre_ids": item.get("genre_ids", []),
            "overview": item.get("overview", ""),
            "rating": item.get("vote_average", 0),
            "popularity": item.get("popularity", 0)
        })

        print(title)

with open("contents.json", "w", encoding="utf-8") as f:
    json.dump(contents, f, ensure_ascii=False, indent=2)

print(f"\n수집 완료: {len(contents)}개")
