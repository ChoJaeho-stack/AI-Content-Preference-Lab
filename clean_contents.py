import os
import json
import mysql.connector
from dotenv import load_dotenv

load_dotenv(override=True)

with open("review_contents.json", encoding="utf-8") as f:
    contents = json.load(f)

# 일반 영화 보호 목록
allowed_titles = {
    "미인도",
    "동화지만 청불입니다",
    "정사",
    "수상한 그녀",
    "썸머타임",
    "남자가 사랑할 때",
    "연애 빠진 로맨스",
    "리벤져",
    "나의 PS 파트너"
}

conn = mysql.connector.connect(
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT", "3306")),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME"),
    use_pure=True
)

cursor = conn.cursor()

# 추천 제외 컬럼 추가
cursor.execute(
    "SHOW COLUMNS FROM contents LIKE 'is_excluded'"
)

if cursor.fetchone() is None:
    cursor.execute("""
        ALTER TABLE contents
        ADD COLUMN is_excluded BOOLEAN
        NOT NULL DEFAULT FALSE
    """)

excluded = 0

try:
    for content in contents:

        title = content.get("title", "")
        is_excluded = title not in allowed_titles

        cursor.execute("""
            UPDATE contents
            SET is_excluded = %s
            WHERE id = %s AND type = %s
        """, (
            is_excluded,
            content["id"],
            content["type"]
        ))

        if is_excluded:
            excluded += 1
            print(f"[추천 제외] {title}")
        else:
            print(f"[유지] {title}")

    conn.commit()

    cursor.execute("""
        SELECT COUNT(*) FROM contents
        WHERE is_excluded = FALSE
    """)

    available = cursor.fetchone()[0]

    print("\n===== 데이터 정제 완료 =====")
    print(f"추천 제외 대상: {excluded}개")
    print(f"추천 가능: {available}개")

except Exception as e:
    conn.rollback()
    print(f"오류: {e}")

finally:
    cursor.close()
    conn.close()