print("프로그램 실행 시작!", flush=True)

import os
import json
import mysql.connector
from dotenv import load_dotenv

load_dotenv(override=True)

# 1. MySQL 연결
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

# 2. 콘텐츠 데이터 불러오기
with open("merged_contents.json", "r", encoding="utf-8") as f:
    contents = json.load(f)

# 3. 데이터 저장
sql = """
INSERT INTO contents
(id, type, title, overview, genre_ids, rating, popularity, ott)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    title = VALUES(title),
    overview = VALUES(overview),
    genre_ids = VALUES(genre_ids),
    rating = VALUES(rating),
    popularity = VALUES(popularity),
    ott = VALUES(ott)
"""

for content in contents:
    cursor.execute(sql, (
        content["id"],
        content["type"],
        content["title"],
        content.get("overview", ""),
        json.dumps(content.get("genre_ids", [])),
        content.get("rating", 0),
        content.get("popularity", 0),
        json.dumps(content.get("ott", []), ensure_ascii=False)
    ))

conn.commit()

# 4. 저장된 콘텐츠 개수 확인
cursor.execute("SELECT COUNT(*) FROM contents")
count = cursor.fetchone()[0]

print(f"DB 저장 콘텐츠: {count}개")
print("데이터베이스 저장 완료!")

cursor.close()
conn.close()