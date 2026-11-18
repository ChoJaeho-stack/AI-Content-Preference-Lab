import os
import json
import mysql.connector
from dotenv import load_dotenv

load_dotenv(override=True)


# 1. MySQL 연결
def get_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        use_pure=True
    )


# 2. 전체 콘텐츠 조회
def get_contents():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT * FROM contents")
        contents = cursor.fetchall()

        for content in contents:
            for key in ["genre_ids", "ott"]:
                value = content.get(key)

                if isinstance(value, str):
                    content[key] = json.loads(value)
                elif value is None:
                    content[key] = []

        return contents

    finally:
        cursor.close()
        conn.close()


# 3. 데이터 조회 테스트
if __name__ == "__main__":
    contents = get_contents()
    print("MySQL 연결 성공!")
    print(f"전체 콘텐츠: {len(contents)}개")