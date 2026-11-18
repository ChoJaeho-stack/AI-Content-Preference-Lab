
import os
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("TMDB_API_KEY")

if not API_KEY:
    raise ValueError("TMDB_API_KEY가 없습니다.")

BASE = "https://api.themoviedb.org/3"
session = requests.Session()

def get(path, params=None):
    options = {
        "api_key": API_KEY,
        "language": "ko-KR"
    }
    if params:
        options.update(params)

    response = session.get(
        BASE + path, params=options, timeout=20
    )
    response.raise_for_status()
    return response.json()

# 한국에서 제공되는 OTT 목록에서 ID 찾기
providers = {}

for category in ["movie", "tv"]:
    data = get(
        f"/watch/providers/{category}",
        {"watch_region": "KR"}
    )

    providers[category] = {}

    for p in data.get("results", []):
        name = p.get("provider_name", "").lower()

        if "netflix" in name:
            providers[category]["넷플릭스"] = p["provider_id"]
        elif "tving" in name:
            providers[category]["티빙"] = p["provider_id"]

print("확인된 OTT:", providers)

contents = []
seen = set()

for category in ["movie", "tv"]:
    for ott, provider_id in providers[category].items():
        for page in range(1, 4):
            data = get(
                f"/discover/{category}",
                {
                    "watch_region": "KR",
                    "with_watch_providers": str(provider_id),
                    "with_watch_monetization_types": "flatrate",
                    "with_origin_country": "KR",
                    "with_original_language": "ko",
                    "sort_by": "popularity.desc",
                    "page": page
                }
            )

            for item in data.get("results", []):
                key = (category, item["id"])

                if key not in seen:
                    seen.add(key)
                    contents.append({
                        "id": item["id"],
                        "type": category,
                        "title": item.get("title") or item.get("name"),
                        "genre_ids": item.get("genre_ids", []),
                        "overview": item.get("overview", ""),
                        "rating": item.get("vote_average", 0),
                        "popularity": item.get("popularity", 0),
                        "ott": []
                    })

                for content in contents:
                    if (content["type"], content["id"]) == key:
                        if ott not in content["ott"]:
                            content["ott"].append(ott)
                        break

            time.sleep(0.2)

with open("ott_contents.json", "w", encoding="utf-8") as f:
    json.dump(contents, f, ensure_ascii=False, indent=2)

print(f"\n총 {len(contents)}개 작품 수집 완료")

for item in contents:
    print(item["title"], "-", ", ".join(item["ott"]))
