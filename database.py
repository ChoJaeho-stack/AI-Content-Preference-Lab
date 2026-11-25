import os
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

VERIFIED_WEBTOON_FEATURES = Path(__file__).with_name("webtoon_verified_features.json")


def _apply_verified_webtoon_features(contents):
    """Overlay source-linked official tags without changing MySQL records."""
    try:
        document = json.loads(VERIFIED_WEBTOON_FEATURES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if document.get("schema_version") != 1 or not isinstance(document.get("items"), list):
        return

    def is_official_naver_work_url(value, external_id):
        try:
            parsed = urlparse(value)
            return (parsed.scheme == "https"
                    and parsed.hostname in {"comic.naver.com", "m.comic.naver.com"}
                    and parsed.path == "/webtoon/list"
                    and parse_qs(parsed.query).get("titleId") == [external_id])
        except (TypeError, ValueError):
            return False

    by_identity = {
        (item.get("source_provider"), str(item.get("external_id"))): item
        for item in document["items"]
        if isinstance(item, dict) and item.get("source_url")
        and item.get("verified_on") and isinstance(item.get("official_tags"), list)
        and isinstance(item.get("taste_tags"), list)
        and set(item["taste_tags"]).issubset(set(item["official_tags"]))
        and is_official_naver_work_url(item.get("source_url"), str(item.get("external_id")))
    }
    for content in contents:
        identity = (content.get("source_provider"), str(content.get("external_id")))
        verified = by_identity.get(identity)
        if (not verified or identity[0] != "naver_webtoon"
                or not is_official_naver_work_url(content.get("official_url"), identity[1])):
            continue
        tags = [tag for tag in verified["official_tags"] if isinstance(tag, str) and tag.strip()]
        taste_tags = [tag for tag in verified["taste_tags"] if isinstance(tag, str) and tag.strip()]
        content["official_tags"] = tags
        features = content.get("taste_features")
        if isinstance(features, dict):
            features["official_tags"] = taste_tags


# 1. MySQL 연결
def get_connection():
    ssl_ca = os.getenv("DB_SSL_CA")
    tls_options = {
        "ssl_ca": ssl_ca,
        "ssl_verify_cert": True,
        "ssl_verify_identity": True,
    } if ssl_ca else {}
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        connection_timeout=5,
        use_pure=True,
        **tls_options,
    )


# 2. 전체 콘텐츠 조회
def get_contents():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT * FROM contents WHERE is_excluded = FALSE")
        contents = cursor.fetchall()

        for content in contents:
            for key in ["genre_ids", "ott"]:
                value = content.get(key)

                if isinstance(value, str):
                    content[key] = json.loads(value)
                elif value is None:
                    content[key] = []

        webtoon_contents = [row for row in contents if row.get("type") == "webtoon"]
        if webtoon_contents:
            cursor.execute("""
                SELECT COUNT(*) AS table_count
                FROM information_schema.tables
                WHERE table_schema=DATABASE()
                  AND table_name IN ('webtoon_metadata', 'content_external_ids')
            """)
            webtoon_schema_ready = cursor.fetchone()["table_count"] == 2
        else:
            webtoon_schema_ready = False

        if webtoon_schema_ready:
            cursor.execute("""
                SELECT COUNT(*) AS column_count
                FROM information_schema.columns
                WHERE table_schema=DATABASE() AND table_name='webtoon_metadata'
                  AND column_name='cover_source_url'
            """)
            has_cover_source_url = cursor.fetchone()["column_count"] == 1
            cover_source_select = "w.cover_source_url" if has_cover_source_url else "NULL AS cover_source_url"
            cursor.execute(f"""
                SELECT w.content_id, w.source_provider, x.external_id,
                       w.service_platform, w.official_url, {cover_source_select}, w.authors,
                       w.genre_tags, w.story_tags, w.mood_tags, w.pacing,
                       w.serial_status
                FROM webtoon_metadata w
                JOIN content_external_ids x
                  ON x.provider_code=w.source_provider
                 AND x.content_id=w.content_id AND x.content_type=w.content_type
                WHERE w.content_type='webtoon'
            """)
            metadata = {row["content_id"]: row for row in cursor.fetchall()}
            for content in webtoon_contents:
                row = metadata.get(content["id"])
                if not row:
                    continue
                parsed = {}
                for key in ("authors", "genre_tags", "story_tags", "mood_tags"):
                    value = row.get(key)
                    parsed[key] = json.loads(value) if isinstance(value, str) else value
                content["taste_features"] = {
                    "genres": parsed["genre_tags"] or [],
                    "story": parsed["story_tags"] or [],
                    "mood": parsed["mood_tags"] or [],
                    "pacing": row.get("pacing") or "",
                }
                content["authors"] = parsed["authors"] or []
                content["source_provider"] = row["source_provider"]
                content["external_id"] = row["external_id"]
                content["service_platform"] = row["service_platform"]
                content["official_url"] = row["official_url"]
                content["cover_source_url"] = row["cover_source_url"]
                content["genre_tags"] = parsed["genre_tags"] or []
                content["story_tags"] = parsed["story_tags"] or []
                content["mood_tags"] = parsed["mood_tags"] or []
                content["pacing"] = row.get("pacing") or ""
                content["serial_status"] = row["serial_status"]

        _apply_verified_webtoon_features(contents)
        return contents

    finally:
        cursor.close()
        conn.close()


# 3. 데이터 조회 테스트
if __name__ == "__main__":
    contents = get_contents()
    print("MySQL 연결 성공!")
    print(f"전체 콘텐츠: {len(contents)}개")
