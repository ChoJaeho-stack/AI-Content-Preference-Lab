"""KMAS webtoon catalog adapter.

Live access is deliberately opt-in: KMAS requires administrator approval and
the documented page uses a placeholder host. This module never guesses that
host, logs the API key, downloads cover art, or exposes source-only fields.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import mysql.connector
from dotenv import dotenv_values, load_dotenv


ENDPOINT_PATH = "/openapi/search/bookAndWebtoonList"
PROVIDER_CODE = "kmas"
FICTIONAL_PROVIDER_CODE = "contentlab_demo_fictional"
DAILY_REQUEST_LIMIT = 1000
MAX_PAGE_SIZE = 100
CONTENT_ID_BASE = 7_000_000_000_000_000
CONTENT_ID_HASH_MODULUS = 1_000_000_000_000_000
KMAS_ENV_KEYS = (
    "KMAS_API_KEY",
    "KMAS_API_APPROVED",
    "KMAS_API_BASE_URL",
    "KMAS_API_MODE",
)


class KmasProviderError(RuntimeError):
    """Safe-to-report provider failure; never includes credentials or URLs."""


def load_kmas_environment(env_file: Path | None = None) -> None:
    """Load project settings without allowing blank process variables to mask .env."""
    path = env_file or Path(__file__).resolve().with_name(".env")
    file_values = dotenv_values(path)
    load_dotenv(path, override=False)
    for name in KMAS_ENV_KEYS:
        if os.environ.get(name, "").strip():
            continue
        value = file_values.get(name)
        if value is not None and str(value).strip():
            os.environ[name] = str(value).strip()


@dataclass(frozen=True)
class KmasSettings:
    mode: str
    approved: bool
    api_key: str
    base_url: str
    page_size: int
    max_pages: int
    synopsis_display_allowed: bool
    cover_display_allowed: bool

    @classmethod
    def from_env(cls) -> "KmasSettings":
        load_kmas_environment()
        mode = os.getenv("KMAS_API_MODE", "mock").strip().lower()
        if mode not in {"mock", "live"}:
            raise KmasProviderError("KMAS_API_MODE must be mock or live")
        return cls(
            mode=mode,
            approved=os.getenv("KMAS_API_APPROVED", "false").strip().lower() == "true",
            api_key=os.getenv("KMAS_API_KEY", "").strip(),
            base_url=os.getenv("KMAS_API_BASE_URL", "").strip(),
            page_size=_bounded_int("KMAS_PAGE_SIZE", 100, 1, MAX_PAGE_SIZE),
            max_pages=_bounded_int("KMAS_MAX_PAGES", 10, 1, DAILY_REQUEST_LIMIT),
            synopsis_display_allowed=os.getenv("KMAS_SYNOPSIS_DISPLAY_ALLOWED", "false").lower() == "true",
            cover_display_allowed=os.getenv("KMAS_COVER_DISPLAY_ALLOWED", "false").lower() == "true",
        )

    def validate_live_access(self) -> str:
        if self.mode != "live":
            raise KmasProviderError("KMAS live access is disabled; set KMAS_API_MODE=live after approval")
        if not self.approved:
            raise KmasProviderError("KMAS administrator approval is not confirmed")
        if not self.api_key:
            raise KmasProviderError("KMAS_API_KEY is not configured")
        parsed = urllib.parse.urlsplit(self.base_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}):
            raise KmasProviderError("KMAS_API_BASE_URL must be the verified HTTPS service root")
        return self.base_url.rstrip("/") + ENDPOINT_PATH


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise KmasProviderError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise KmasProviderError(f"{name} must be between {minimum} and {maximum}")
    return value


def _text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _safe_source_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or len(value.strip()) > 2048:
        return None
    return value.strip()


def parse_response(payload: Any) -> tuple[int, list[dict[str, Any]]]:
    """Validate the documented {result: {resultState, totalCount, itemlist}} envelope."""
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        raise KmasProviderError("KMAS response schema is not recognized")
    if str(result.get("resultState", "")).strip().lower() != "success":
        raise KmasProviderError("KMAS reported an unsuccessful response")
    rows = result.get("itemlist")
    try:
        total = int(result.get("totalCount", 0))
    except (TypeError, ValueError) as exc:
        raise KmasProviderError("KMAS response totalCount is invalid") from exc
    if total < 0 or not isinstance(rows, list):
        raise KmasProviderError("KMAS response catalog fields are invalid")
    accepted = []
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise KmasProviderError("KMAS response contains an invalid catalog row")
        # The docs' sample response contains a book (listSeCd=2) despite being
        # shown on the shared endpoint page, so require the requested webtoon code.
        if str(row.get("listSeCd", "")).strip() != "1":
            continue
        external_id = _text(row, "mastrId")
        title = _text(row, "prdctNm", "title")
        if not external_id or not title:
            raise KmasProviderError("KMAS webtoon row is missing its documented ID or title")
        if len(external_id) > 191 or len(title) > 255:
            raise KmasProviderError("KMAS webtoon ID or title exceeds the catalog column limit")
        normalized = {
            "external_id": external_id,
            "title": title,
            "authors": list(dict.fromkeys(filter(None, [
                _text(row, "sntncWritrNm"), _text(row, "pictrWritrNm")
            ]))),
            "genre": _text(row, "mainGenreCdNm"),
            "synopsis": _text(row, "outline"),
            "cover_source_url": _safe_source_url(row.get("imageDownloadUrl")),
            "serial_status": "완결" if str(row.get("fnshYn", "")).strip().upper() == "Y" else "연재 정보 미확인",
            "platform": (_text(row, "pltfomCdNm", "pltfomCmpnyIdNm") or "KMAS 제공 정보")[:80],
        }
        prior = seen.get(external_id)
        if prior is not None and prior != normalized:
            raise KmasProviderError("KMAS response has conflicting duplicate provider IDs")
        seen[external_id] = normalized
    accepted.extend(seen.values())
    return total, accepted


def parse_title_search(payload: Any, title: str) -> tuple[int, dict[str, Any] | None]:
    """Accept a uniquely identified serialized work from the live title-search format."""
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict) or result.get("resultState") != "success":
        raise KmasProviderError("KMAS title search was unsuccessful")
    try:
        total = int(result["totalCount"])
    except (KeyError, TypeError, ValueError):
        raise KmasProviderError("KMAS title search count is invalid") from None
    # KMAS has returned both itemlist/item and itemlist arrays. Only walk the
    # documented envelope keys; never recursively inspect arbitrary record fields.
    record_keys = {"prdctNm", "pltfomCdNm", "mainGenreCdNm", "pictrWritrNm",
                   "sntncWritrNm", "mastrId", "isbn", "setIsbn", "listSeCd"}
    container_keys = ("result", "itemlist", "itemList", "items", "item")
    rows: list[dict[str, Any]] = []
    containers_seen = False
    def collect(node: Any, depth: int = 0) -> None:
        nonlocal containers_seen
        if node is None:
            return
        if depth > 12 or len(rows) >= 500:
            raise KmasProviderError("KMAS title search response structure exceeds safe limits")
        if isinstance(node, list):
            containers_seen = True
            for child in node:
                collect(child, depth + 1)
            return
        if not isinstance(node, dict):
            return
        if record_keys.intersection(node):
            rows.append(node)
            return
        followed = False
        for key in container_keys:
            if key in node:
                containers_seen = True
                followed = True
                collect(node[key], depth + 1)
        if not followed and not containers_seen:
            return

    collect(payload)
    if not containers_seen or (total and not rows):
        raise KmasProviderError("KMAS title search response structure is invalid")
    if len(rows) != total:
        raise KmasProviderError("KMAS title search results are incomplete")

    def normalized(value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split())

    target = normalized(title)
    candidates = {}
    ambiguous_identity = False
    for row in rows:
        if not isinstance(row, dict):
            raise KmasProviderError("KMAS title search contains an invalid row")
        work_title = _text(row, "prdctNm")
        platform = _text(row, "pltfomCdNm")
        authors = list(dict.fromkeys(filter(None, [
            _text(row, "sntncWritrNm"), _text(row, "pictrWritrNm"),
        ])))
        if (not platform or not authors or not target
                or normalized(work_title) != target or normalized(_text(row, "title")) != target
                or _text(row, "isbn", "setIsbn", "edtn", "plscmpnIdNm")):
            continue
        # Naver Series is a separate product. When KMAS returns both it and
        # Naver Webtoon for one title, keep the Webtoon row as the selected work.
        if normalized(platform) == normalized("네이버시리즈"):
            continue
        # Title search omits the documented mastrId field in its live response.
        # Keep a deterministic internal identity, but never put it in the
        # provider external-ID mapping as though KMAS issued it.
        try:
            internal_identity = internal_identity_for(work_title, platform, authors)
        except KmasProviderError:
            continue
        record = {
            "external_id": None, "internal_identity": internal_identity,
            "title": work_title, "authors": authors,
            "genre": _text(row, "mainGenreCdNm"), "synopsis": "", "cover_source_url": None,
            "serial_status": None, "platform": platform[:80],
        }
        prior = candidates.get(internal_identity)
        if prior is not None and prior != record:
            raise KmasProviderError("KMAS title search has conflicting rows without provider IDs")
        if prior is not None:
            ambiguous_identity = True
        candidates[internal_identity] = record
    if ambiguous_identity:
        return total, None
    naver_webtoon = {
        external_id: record for external_id, record in candidates.items()
        if normalized(record["platform"]) == normalized("네이버웹툰")
    }
    if len(naver_webtoon) == 1:
        return total, next(iter(naver_webtoon.values()))
    if len(naver_webtoon) > 1:
        return total, None
    if len(candidates) == 1:
        return total, next(iter(candidates.values()))
    return total, None


def internal_identity_for(title: str, platform: str, authors: list[str]) -> str:
    """Return a deterministic internal key; this value is never a provider ID."""
    normalize = lambda value: " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    placeholders = {"네이버웹툰작가", "작가미상", "미상", "unknown", "n/a"}
    if (not title.strip() or not platform.strip() or not authors
            or any(normalize(author) in placeholders for author in authors)):
        raise KmasProviderError("Internal work identity requires title, platform, and author evidence")
    identity = _json([
        normalize(title), normalize(platform), sorted(normalize(author) for author in authors),
    ])
    return "title-search:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def internal_authors_match(existing: Any, expected: list[str]) -> bool:
    """Compare credited authors as an order-independent identity component."""
    if isinstance(existing, str):
        try:
            existing = json.loads(existing)
        except json.JSONDecodeError:
            return False
    if not isinstance(existing, list) or not isinstance(expected, list):
        return False
    normalize = lambda value: " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    if not all(isinstance(author, str) and author.strip() for author in existing + expected):
        return False
    return {normalize(author) for author in existing} == {normalize(author) for author in expected}


def request_page(settings: KmasSettings, page: int, *, title: str | None = None) -> Any:
    endpoint = settings.validate_live_access()
    query = {
        "prvKey": settings.api_key,
        "listSeCd": "1",
        "pageNo": str(page),
        "viewItemCnt": str(settings.page_size),
    }
    if title is not None:
        query["title"] = title
    params = urllib.parse.urlencode(query)
    request = urllib.request.Request(
        endpoint + "?" + params,
        headers={"Accept": "application/json", "User-Agent": "AIContentLab/1.0"},
    )
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, new_url):
            return None

    try:
        opener = urllib.request.build_opener(NoRedirect)
        with opener.open(request, timeout=12) as response:
            if response.status != 200:
                raise KmasProviderError(f"KMAS returned HTTP {response.status}")
            if "json" not in response.headers.get("Content-Type", "").lower():
                raise KmasProviderError("KMAS response content type is not JSON")
            return json.loads(response.read(4_000_001))
    except urllib.error.HTTPError as exc:
        # Do not include exc URL: query string carries prvKey.
        raise KmasProviderError(f"KMAS returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise KmasProviderError(f"KMAS request failed ({type(exc).__name__})") from None


def fetch_catalog(settings: KmasSettings, page_fetch: Callable[[int], Any] | None = None) -> list[dict[str, Any]]:
    if settings.mode == "live":
        settings.validate_live_access()
        page_fetch = page_fetch or (lambda page: request_page(settings, page))
    elif page_fetch is None:
        raise KmasProviderError("Mock mode requires a test response provider")
    assert page_fetch is not None

    records: dict[str, dict[str, Any]] = {}
    page_count = 0
    total_count = 0
    for page in range(settings.max_pages):
        total_count, rows = parse_response(page_fetch(page))
        page_count += 1
        for row in rows:
            previous = records.get(row["external_id"])
            if previous is not None and previous != row:
                raise KmasProviderError("KMAS pages contain conflicting duplicate provider IDs")
            records[row["external_id"]] = row
        if not rows and len(records) < total_count:
            raise KmasProviderError("KMAS pages ended before the declared catalog count; existing data was not changed")
        if len(records) >= total_count:
            break
    if len(records) < total_count:
        raise KmasProviderError("KMAS catalog exceeds the configured page limit; existing data was not changed")
    return list(records.values())


def _content_id(external_id: str, provider: str = PROVIDER_CODE) -> int:
    digest = hashlib.sha256((provider + ":" + external_id).encode("utf-8")).hexdigest()
    # New IDs in both ranges must round-trip as exact browser JSON numbers.
    if external_id.startswith("title-search:"):
        return 8_000_000_000_000_000 + int(digest[:15], 16) % 1_000_000_000_000_000
    return CONTENT_ID_BASE + (int(digest[:15], 16) % CONTENT_ID_HASH_MODULUS)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def required_schema_ready(
    cursor, *, require_cover_source: bool = True, require_external_ids: bool = True
) -> bool:
    cursor.execute("""
        SELECT table_name AS table_name, column_name AS column_name
        FROM information_schema.columns
        WHERE table_schema=DATABASE()
          AND ((table_name='content_external_ids' AND column_name IN ('provider_code','external_id','content_type','content_id','source_url'))
            OR (table_name='webtoon_metadata' AND column_name IN ('content_id','content_type','service_platform','cover_source_url','authors','genre_tags','story_tags','mood_tags','pacing','serial_status','source_provider')))
    """)
    found = {(row["table_name"], row["column_name"]) for row in cursor.fetchall()}
    required = {
        ("webtoon_metadata", name) for name in
        ("content_id", "content_type", "service_platform", "cover_source_url", "authors", "genre_tags",
         "story_tags", "mood_tags", "pacing", "serial_status", "source_provider")
    }
    if require_external_ids:
        required.update({
            ("content_external_ids", name) for name in
            ("provider_code", "external_id", "content_type", "content_id", "source_url")
        })
    if not require_cover_source:
        required.discard(("webtoon_metadata", "cover_source_url"))
    if not required.issubset(found):
        return False
    if not require_external_ids:
        cursor.execute("""
            SELECT COUNT(*) AS external_mapping_foreign_keys
            FROM information_schema.key_column_usage
            WHERE table_schema=DATABASE()
              AND table_name='webtoon_metadata'
              AND referenced_table_name='content_external_ids'
        """)
        if cursor.fetchone()["external_mapping_foreign_keys"] != 0:
            return False
    return True


def sync_schema_ready(
    connection, *, require_cover_source: bool = True, require_external_ids: bool = True
) -> bool:
    cursor = connection.cursor(dictionary=True)
    try:
        if not required_schema_ready(
            cursor, require_cover_source=require_cover_source,
            require_external_ids=require_external_ids,
        ):
            return False
        cursor.execute("""
            SELECT COUNT(*) AS table_count FROM information_schema.tables
            WHERE table_schema=DATABASE()
              AND table_name IN ('contents','kmas_api_daily_usage')
        """)
        if cursor.fetchone()["table_count"] != 2:
            return False
        cursor.execute("""
            SELECT COUNT(*) AS column_count FROM information_schema.columns
            WHERE table_schema=DATABASE() AND table_name='kmas_api_daily_usage'
              AND column_name IN ('usage_date','request_count')
        """)
        return cursor.fetchone()["column_count"] == 2
    finally:
        cursor.close()


def persist_catalog(
    connection, records: list[dict[str, Any]], settings: KmasSettings, *, before_write=None
) -> int:
    """Idempotently upsert only provider-owned webtoon catalog rows in one transaction."""
    if not records:
        return 0
    require_cover_source = any(
        row.get("external_id")
        and (not row.get("preserve_missing_metadata") or row.get("cover_source_url"))
        for row in records
    )
    cover_column = "cover_source_url, " if require_cover_source else ""
    cover_value = "%s, " if require_cover_source else ""
    cursor = connection.cursor(dictionary=True)
    try:
        require_external_ids = any(row.get("external_id") for row in records)
        if not required_schema_ready(
            cursor, require_cover_source=require_cover_source,
            require_external_ids=require_external_ids,
        ):
            raise KmasProviderError("KMAS catalog schema is missing; apply the reviewed additive migration first")
        cursor.execute("SELECT GET_LOCK('contentlab_kmas_catalog_sync', 0) AS acquired")
        if cursor.fetchone()["acquired"] != 1:
            raise KmasProviderError("Another KMAS catalog sync is already running")
        connection.commit()
        connection.start_transaction()
        if before_write is not None:
            before_write(cursor)
        for row in records:
            external_id = row["external_id"]
            internal_identity = row.get("internal_identity")
            if not external_id and not internal_identity:
                raise KmasProviderError("KMAS catalog row has no official or internal identity")
            provider = row.get("provider", PROVIDER_CODE)
            official_url = row.get("official_url")
            identity = None
            if external_id:
                cursor.execute("""
                    SELECT content_id, content_type FROM content_external_ids
                    WHERE provider_code=%s AND external_id=%s
                    FOR UPDATE
                """, (provider, external_id))
                identity = cursor.fetchone()
            if identity and identity["content_type"] != "webtoon":
                raise KmasProviderError("KMAS provider ID is already assigned to another content type")
            stable_identity = external_id or internal_identity
            content_id = int(identity["content_id"]) if identity else _content_id(stable_identity, provider)
            if not identity:
                cursor.execute("""
                    SELECT c.type, c.title, m.service_platform, m.authors, m.source_provider
                    FROM contents c
                    LEFT JOIN webtoon_metadata m
                      ON m.content_id=c.id AND m.content_type='webtoon'
                    WHERE c.id=%s FOR UPDATE
                """, (content_id,))
                collision = cursor.fetchone()
                if collision:
                    same_internal_work = (
                        not external_id
                        and collision.get("type") == "webtoon"
                        and collision.get("title") == row["title"]
                        and collision.get("service_platform") == row["platform"]
                        and collision.get("source_provider") == provider
                    )
                    if same_internal_work:
                        existing_authors = collision.get("authors")
                        same_internal_work = internal_authors_match(existing_authors, row["authors"])
                    if not same_internal_work:
                        raise KmasProviderError("Generated KMAS catalog ID collides with a different content row; no catalog changes committed")
                    identity = {"content_id": content_id, "content_type": "webtoon"}
            if not identity:
                cursor.execute(
                    "SELECT id, title FROM contents WHERE type='webtoon' AND title=%s FOR UPDATE",
                    (row["title"],),
                )
                if cursor.fetchall():
                    raise KmasProviderError(
                        "Existing webtoon title requires identity review; no catalog changes committed"
                    )

            genres = [row["genre"]] if row.get("genre") else []
            synopsis = row.get("synopsis", "") if settings.synopsis_display_allowed else ""
            display_cover = row.get("cover_source_url") if settings.cover_display_allowed else None
            poster_url = display_cover or "/posters/webtoon-cover-unavailable.svg"
            preserve = row.get("preserve_missing_metadata", False)
            content_update = ["title=VALUES(title)"]
            if not preserve or synopsis:
                content_update.append("overview=VALUES(overview)")
            if not preserve or display_cover:
                content_update.append("poster_url=VALUES(poster_url)")
            cursor.execute(f"""
                INSERT INTO contents (id, type, title, overview, genre_ids, rating, popularity, ott, poster_url, is_excluded)
                VALUES (%s, 'webtoon', %s, %s, JSON_ARRAY(), NULL, 0, JSON_ARRAY(), %s, FALSE)
                ON DUPLICATE KEY UPDATE {", ".join(content_update)}
            """, (content_id, row["title"], synopsis, poster_url))
            if external_id:
                cursor.execute("""
                    INSERT INTO content_external_ids (provider_code, external_id, content_type, content_id, source_url)
                    VALUES (%s, %s, 'webtoon', %s, %s)
                    ON DUPLICATE KEY UPDATE content_id=VALUES(content_id), source_url=COALESCE(VALUES(source_url),source_url)
                """, (provider, external_id, content_id, official_url))
            cover_params = (row.get("cover_source_url"),) if require_cover_source else ()
            metadata_update = [
                "service_platform=VALUES(service_platform)", "authors=VALUES(authors)",
                "source_provider=VALUES(source_provider)",
            ]
            if require_cover_source and (not preserve or row.get("cover_source_url")):
                metadata_update.append("cover_source_url=VALUES(cover_source_url)")
            if not preserve or genres:
                metadata_update.append("genre_tags=VALUES(genre_tags)")
            if not preserve or row["serial_status"]:
                metadata_update.append("serial_status=VALUES(serial_status)")
            if official_url:
                metadata_update.append("official_url=VALUES(official_url)")
            cursor.execute(f"""
                INSERT INTO webtoon_metadata
                    (content_id, content_type, service_platform, official_url, {cover_column}authors,
                     genre_tags, story_tags, mood_tags, pacing, serial_status, source_provider)
                VALUES (%s, 'webtoon', %s, %s, {cover_value}%s, %s, JSON_ARRAY(), JSON_ARRAY(), NULL, %s, %s)
                ON DUPLICATE KEY UPDATE {", ".join(metadata_update)}
            """, (content_id, row["platform"], official_url, *cover_params, _json(row["authors"]),
                  _json(genres), row["serial_status"], provider))
        connection.commit()
        return len(records)
    except Exception:
        connection.rollback()
        raise
    finally:
        try:
            cursor.execute("SELECT RELEASE_LOCK('contentlab_kmas_catalog_sync')")
            cursor.fetchone()
        except Exception:
            pass
        cursor.close()


def reserve_daily_request(connection) -> None:
    """Atomically consume one of the documented 1,000 daily requests."""
    cursor = connection.cursor()
    try:
        connection.start_transaction()
        cursor.execute("""
            INSERT INTO kmas_api_daily_usage (usage_date, request_count)
            VALUES (CURRENT_DATE(), 0)
            ON DUPLICATE KEY UPDATE usage_date=VALUES(usage_date)
        """)
        cursor.execute("""
            UPDATE kmas_api_daily_usage SET request_count=request_count+1
            WHERE usage_date=CURRENT_DATE() AND request_count < %s
        """, (DAILY_REQUEST_LIMIT,))
        if cursor.rowcount != 1:
            raise KmasProviderError("KMAS daily request allowance (1,000) has been reached")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def main(argv: list[str] | None = None) -> None:
    """One explicit, approval-gated sync command; never runs at app startup."""
    parser = argparse.ArgumentParser(description="Import approved KMAS webtoon metadata")
    parser.add_argument("--title", action="append", default=[], help="Search for one exact webtoon title (repeatable)")
    parser.add_argument(
        "--approved-db-write", action="store_true",
        help="Explicitly allow the catalog transaction after the KMAS request has been approved",
    )
    args = parser.parse_args(argv)
    if not args.approved_db_write:
        parser.error("Catalog writes require explicit --approved-db-write after separate DryRun review")
    titles = list(dict.fromkeys(title.strip() for title in args.title))
    if "" in titles:
        parser.error("--title cannot be blank")

    settings = KmasSettings.from_env()
    settings.validate_live_access()
    if len(titles) > settings.max_pages:
        parser.error("the number of titles exceeds KMAS_MAX_PAGES")
    from database import get_connection

    connection = get_connection()
    try:
        if not sync_schema_ready(
            connection, require_cover_source=not titles,
            require_external_ids=not bool(titles),
        ):
            raise KmasProviderError("KMAS sync schema is missing; apply the reviewed additive migrations first")
        connection.commit()

        def fetch_page(page: int, *, title: str | None = None) -> Any:
            reserve_daily_request(connection)
            return request_page(settings, page, title=title)

        if titles:
            by_id = {}
            skipped = 0
            for title in titles:
                _, record = parse_title_search(fetch_page(0, title=title), title)
                if record is None:
                    skipped += 1
                    continue
                identity_key = record["external_id"] or record["internal_identity"]
                if by_id.setdefault(identity_key, record) != record:
                    raise KmasProviderError("KMAS title searches returned conflicting records")
            records = list(by_id.values())
            print(f"KMAS title searches: {len(titles)} checked, {skipped} without a unique exact match")
        else:
            records = fetch_catalog(settings, fetch_page)
        count = persist_catalog(connection, records, settings)
        print(f"KMAS catalog sync complete: {count} validated webtoon records")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
