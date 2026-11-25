import os
import json
import time
import mysql.connector
from dotenv import load_dotenv

load_dotenv(override=True)

start_time = time.time()

# 1. 데이터 불러오기
with open("contents_with_ott.json", encoding="utf-8") as f:
    contents = json.load(f)

# 2. MySQL 연결
conn = mysql.connector.connect(
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT", "3306")),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME"),
    use_pure=True
)

cursor = conn.cursor()
print("MySQL 연결 성공!")

# 3. 기존 데이터 개수 확인
cursor.execute("SELECT COUNT(*) FROM contents")
before_count = cursor.fetchone()[0]

# 4. Upsert SQL
sql = """
INSERT INTO contents (
    id, type, title, overview,
    genre_ids, rating, popularity,
    ott, poster_url
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
AS new
ON DUPLICATE KEY UPDATE
    title = new.title,
    overview = new.overview,
    genre_ids = new.genre_ids,
    rating = new.rating,
    popularity = new.popularity,
    ott = new.ott,
    poster_url = new.poster_url
"""

# 5. 데이터 변환
data = []

for content in contents:

    data.append((
        content["id"],
        content["type"],
        content.get("title"),
        content.get("overview", ""),
        json.dumps(
            content.get("genre_ids", []),
            ensure_ascii=False
        ),
        content.get("rating", 0),
        content.get("popularity", 0),
        json.dumps(
            content.get("ott", []),
            ensure_ascii=False
        ),
        content.get("poster_url")
    ))

# 6. 일괄 저장 및 트랜잭션
try:
    BATCH_SIZE = 200

    for i in range(0, len(data), BATCH_SIZE):

        batch = data[i:i + BATCH_SIZE]

        cursor.executemany(sql, batch)

        print(
            f"저장 진행: "
            f"{min(i + BATCH_SIZE, len(data))}/{len(data)}"
        )

    conn.commit()

    # 7. 저장 결과 확인
    cursor.execute("SELECT COUNT(*) FROM contents")
    after_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM contents
        WHERE poster_url IS NOT NULL
    """)
    poster_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM contents
        WHERE JSON_LENGTH(ott) > 0
    """)
    ott_count = cursor.fetchone()[0]

    print("\n===== 데이터베이스 저장 완료 =====")
    print(f"기존 콘텐츠: {before_count}개")
    print(f"전체 콘텐츠: {after_count}개")
    print(f"신규 추가: {after_count - before_count}개")
    print(f"포스터 보유: {poster_count}개")
    print(f"OTT 정보 보유: {ott_count}개")
    print(f"소요 시간: {time.time() - start_time:.2f}초")

except Exception as e:
    conn.rollback()
    print(f"저장 실패: {e}")
    print("변경 사항 롤백 완료")

finally:
    cursor.close()
    conn.close()