from database import get_contents

import os
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

# 1. 콘텐츠 데이터 불러오기
contents = get_contents()
print("MySQL 데이터 불러오기 완료!")

# 2. 사용자 취향 입력
taste = input("원하는 콘텐츠 취향을 입력하세요: ")

keywords = taste.replace(",", " ").split()

# 3. 관련성 점수 계산
def calculate_score(content):
    score = 0

    title = content.get("title", "")
    overview = content.get("overview", "")

    for keyword in keywords:
        if keyword in title:
            score += 5

        if keyword in overview:
            score += 3

    return score

# 4. 추천 후보 선별
candidates = sorted(
    contents,
    key=lambda c: (
        calculate_score(c),
        c.get("rating", 0)
    ),
    reverse=True
)[:30]

print(f"전체 콘텐츠: {len(contents)}개")
print(f"추천 후보: {len(candidates)}개")
print("AI 맞춤형 추천 분석 중...", flush=True)

# 5. AI 프롬프트
prompt = f"""
너는 AI 콘텐츠 추천 전문가다.

사용자 취향:
{taste}

콘텐츠 데이터:
{json.dumps(candidates, ensure_ascii=False)}

위 데이터에 존재하는 작품만 추천해 줘.

1. 사용자 취향 분석
2. 맞춤형 추천 작품 최대 5개
3. 작품별 평점
4. 취향 일치 점수 (100점 만점)
5. 작품별 추천 이유
6. 시청 가능한 OTT 플랫폼
7. OTT 정보가 없으면 빈 배열로 표시
8. 데이터에 없는 정보는 추측하지 마.

반드시 아래 JSON 형식으로 응답해.

{{
    "taste_analysis": "사용자 취향 분석",
    "recommendations": [
        {{
            "id": 123,
            "type": "movie",
            "title": "작품명",
            "rating": 8.5,
            "match_score": 95,
            "reason": "추천 이유",
            "ott": ["넷플릭스"]
        }}
    ]
}}
"""

# 6. Gemini API 호출
try:
    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )

    result = json.loads(response.text)

except Exception as e:
    print("AI 추천 서비스에 오류가 발생했습니다.")
    print("잠시 후 다시 시도해 주세요.")
    print(f"오류 정보: {e}")
    raise SystemExit(1)

# 7. 추천 결과 검증
content_map = {
    (c["type"], c["id"]): c
    for c in candidates
}

verified = []
seen = set()

for item in result["recommendations"]:
    key = (item.get("type"), item.get("id"))

    if key in content_map and key not in seen:
        original = content_map[key]

        item["title"] = original["title"]
        item["rating"] = original["rating"]
        item["ott"] = original.get("ott", [])

        verified.append(item)
        seen.add(key)

result["recommendations"] = verified[:5]

print("추천 데이터 검증 완료!")
print(f"검증 통과 작품: {len(verified[:5])}개")

print(json.dumps(result, ensure_ascii=False, indent=2))

# 8. 추천 결과 저장
with open("recommend_result.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("추천 결과 저장 완료!")