
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

# 1. API 키 불러오기
load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("Gemini API 키를 찾을 수 없습니다. .env 파일을 확인하세요.")

client = genai.Client(api_key=api_key)


# 2. 취향 분석 함수
def analyze_taste(liked, disliked, preference):

    prompt = f"""
너는 드라마, 예능, 영화 전문 콘텐츠 추천 AI다.

사용자의 취향을 간단하게 분석해 줘.

좋아하는 작품: {liked}
싫어하는 요소: {disliked}
선호하는 분위기: {preference}

다음 두 가지 항목만 답변해.

1. 취향 분석:
사용자가 좋아하는 콘텐츠의 특징을 설명해 줘.

2. 작품 추천:
사용자의 취향과 비슷한 드라마, 예능 또는 영화 1개를 추천하고
추천 이유를 간단히 설명해 줘.

조건:
- 실제 존재하는 작품만 추천
- 애니메이션 제외
- 한국어로 답변
- 전체 답변 150자 이내
- 불필요한 설명 금지
"""

    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=300
        )
    )

    return response.text


# 3. 프로그램 실행
def main():

    print("=" * 45)
    print("       AI 콘텐츠 취향 연구소")
    print("       드라마 · 예능 · 영화")
    print("=" * 45)

    liked = input("\n1. 좋아하는 작품 1개를 입력하세요.\n> ")

    disliked = input("\n2. 싫어하는 요소 1개를 입력하세요.\n> ")

    preference = input("\n3. 선호하는 분위기를 입력하세요.\n> ")

    print("\nGemini AI가 취향을 분석하고 있습니다...")
    print("잠시만 기다려 주세요.\n")

    try:
        result = analyze_taste(
            liked,
            disliked,
            preference
        )

        print("=" * 45)
        print("             분석 결과")
        print("=" * 45)

        print(result)

    except Exception as error:
        print("\nGemini API 오류가 발생했습니다.")
        print("오류 내용:", error)


# 4. 프로그램 시작
if __name__ == "__main__":
    main()
