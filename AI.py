
import json

# 1. 콘텐츠 데이터 불러오기
with open("contents.json", "r", encoding="utf-8") as f:
    contents = json.load(f)

# 2. 장르 매핑
genre_map = {
    "로맨스": 10749,
    "액션": 28,
    "코미디": 35,
    "드라마": 18,
    "공포": 27,
    "스릴러": 53,
    "범죄": 80,
    "SF": 878,
    "판타지": 14,
    "미스터리": 9648,
    "예능": 10764,
    "토크쇼": 10767
}

# 3. 콘텐츠 장르 검색
print("\n===== 콘텐츠 검색 =====")
print("검색 가능 장르:", ", ".join(genre_map.keys()))

search_genre = input("원하는 장르를 입력하세요: ").strip()
genre_id = genre_map.get(search_genre)


# 4. 장르별 콘텐츠 필터링
results = []

for content in contents:
    if genre_id in content.get("genre_ids", []):
        results.append(content)

# 5. 평점 높은 순서로 정렬
results.sort(key=lambda x: x["rating"], reverse=True)

# 6. TOP 5 추천
if results:
    print("\n===== 추천 TOP 5 =====")

    for i, content in enumerate(results[:5], 1):
        print(f"\n{i}위: {content['title']}")
        print("평점:", content["rating"])
else:
    print("해당 장르의 콘텐츠가 없습니다.")
