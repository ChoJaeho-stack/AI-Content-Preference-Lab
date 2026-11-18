import os
import json

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from google import genai
from google.genai import types
from database import get_contents

app = FastAPI(title="AI Content Lab")

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


class RecommendRequest(BaseModel):
    taste: str


@app.get("/health")
def health():
    return {
        "status": "success",
        "service": "Python AI Server"
    }


@app.get("/contents/count")
def count_contents():
    return {"count": len(get_contents())}


@app.post("/recommend")
def recommend(request: RecommendRequest):
    contents = get_contents()
    taste = request.taste.strip()

    if not taste:
        raise HTTPException(400, "취향을 입력하세요.")

    keywords = taste.replace(",", " ").split()

    def calculate_score(content):
        score = 0

        for keyword in keywords:
            if keyword in (content.get("title") or ""):
                score += 5
            if keyword in (content.get("overview") or ""):
                score += 3

        return score

    candidates = sorted(
        contents,
        key=lambda c: (
            calculate_score(c),
            c.get("rating") or 0
        ),
        reverse=True
    )[:30]

    prompt = f"""
    너는 AI 콘텐츠 추천 전문가다.

    사용자 취향: {taste}
    콘텐츠 데이터:
    {json.dumps(candidates, ensure_ascii=False)}

    데이터에 존재하는 작품만 최대 5개 추천해.
    없는 정보는 추측하지 마.

    아래 JSON 형식으로 응답해.
    {{
        "taste_analysis": "취향 분석",
        "recommendations": [
            {{
                "id": 123,
                "type": "movie",
                "match_score": 95,
                "reason": "추천 이유"
            }}
        ]
    }}
    """

    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )

        result = json.loads(response.text)

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

        return result

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="AI 추천 서비스 오류"
        )