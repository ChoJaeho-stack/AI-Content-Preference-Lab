import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

taste = input("어떤 콘텐츠를 좋아하시나요? ")

prompt = f"""
너는 콘텐츠 취향 분석 전문가야.

사용자 취향: {taste}

다음 내용을 분석해 줘.
1. 사용자 콘텐츠 취향
2. 선호하는 장르
3. 추천 작품 5개
4. 추천 이유
"""

response = client.models.generate_content(
    model="gemini-3.8-flash",
    contents=prompt
)

print(response.text)