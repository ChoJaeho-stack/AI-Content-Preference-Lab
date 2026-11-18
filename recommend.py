
import json

# 실제 OTT 콘텐츠 데이터 불러오기
with open("ott_contents.json", "r", encoding="utf-8") as f:
    contents = json.load(f)

# TMDB 장르 정보
GENRES = {
    "로맨스": {
        "movie": [10749],
        "tv": [18]
    },
    "코미디": {
        "movie": [35],
        "tv": [35]
    },
    "액션": {
        "movie": [28],
        "tv": [10759]
    },
    "스릴러": {
        "movie": [53, 9648],
        "tv": [9648, 80]
    },
    "전체": {
        "movie": [],
        "tv": []
    }
}

# 콘텐츠 유형 분류
def classify_content(item):
    if item["type"] == "movie":
        return "영화"

    genre_ids = set(item.get("genre_ids", []))

    # TMDB TV 장르
    # 10764 = Reality, 10767 = Talk
    if genre_ids & {10764, 10767}:
        return "예능"

    # 뉴스 장르는 예능으로 분류하지 않음
    if 10763 in genre_ids:
        return "기타"

    return "드라마"


print("=== AI 콘텐츠 취향 연구소 ===")

ott = input("OTT 선택 (넷플릭스/티빙/전체): ").strip()
category = input("콘텐츠 유형 (영화/드라마/예능/전체): ").strip()
genre = input("장르 (로맨스/코미디/액션/스릴러/전체): ").strip()

# 입력 검증
if ott not in ["넷플릭스", "티빙", "전체"]:
    raise ValueError("OTT 선택이 올바르지 않습니다.")

if category not in ["영화", "드라마", "예능", "전체"]:
    raise ValueError("콘텐츠 유형이 올바르지 않습니다.")

if genre not in GENRES:
    raise ValueError("장르 선택이 올바르지 않습니다.")

results = []

for item in contents:
    content_type = classify_content(item)

    # OTT 필터
    if ott != "전체" and ott not in item.get("ott", []):
        continue

    # 콘텐츠 유형 필터
    if category != "전체" and content_type != category:
        continue

    # 장르 필터
    if genre != "전체":
        target_genres = GENRES[genre][item["type"]]

        if not set(item.get("genre_ids", [])) & set(target_genres):
            continue

    # 추천 점수 계산
    rating = float(item.get("rating") or 0)
    popularity = float(item.get("popularity") or 0)

    score = rating * 7 + min(popularity / 10, 30)

    results.append({
        "title": item["title"],
        "type": content_type,
        "score": round(score, 1),
        "rating": rating,
        "ott": item.get("ott", [])
    })

# 추천 점수 높은 순 정렬
results.sort(key=lambda x: x["score"], reverse=True)

print("\n=== 맞춤 추천 TOP 5 ===")

if not results:
    print("조건에 맞는 작품이 없습니다.")
else:
    for rank, item in enumerate(results[:5], 1):
        print(f'\n{rank}위: {item["title"]}')
        print(f'유형: {item["type"]}')
        print(f'추천 점수: {item["score"]}')
        print(f'평점: {item["rating"]}')
        print(f'OTT: {", ".join(item["ott"])}')

