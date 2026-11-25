"""Stage and review previously resolved KMAS webtoons without contacting KMAS."""

import argparse
import csv
import hashlib
import io
import json
import os
import re
from collections import Counter
from pathlib import Path
import unicodedata
from urllib.parse import urlsplit

from kmas_webtoon_provider import (
    KmasProviderError, KmasSettings, PROVIDER_CODE, _content_id, _safe_source_url,
    persist_catalog, required_schema_ready,
)


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def stage(source):
    data = source.read_bytes()
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    columns = {
        "Title", "Platform", "Genre", "AuthorsJson", "KMASExternalId", "ListSeCd",
        "ISBN", "SetISBN", "Synopsis", "CoverSourceUrl", "IsMock", "ResolutionStatus",
    }
    headers = reader.fieldnames or []
    if not columns.issubset(headers) or len(headers) != len(set(headers)):
        raise KmasProviderError("Resolution CSV columns are missing")
    outcomes = []
    candidates = []
    for row in reader:
        title = (row["Title"] or "").strip()
        external_id = (row["KMASExternalId"] or "").strip()
        platform = (row["Platform"] or "").strip()
        genre = (row["Genre"] or "").strip()
        synopsis = (row["Synopsis"] or "").strip()
        raw_cover = (row["CoverSourceUrl"] or "").strip()
        try:
            authors = json.loads(row["AuthorsJson"] or "[]")
        except ValueError:
            authors = None
        valid_authors = isinstance(authors, list) and bool(authors) and all(
            isinstance(author, str) and author.strip() for author in authors
        )
        try:
            cover = _safe_source_url(raw_cover)
        except ValueError:
            cover = None
        blockers = []
        if None in row or any(row[column] is None for column in columns):
            blockers.append("malformed_csv_row")
        if row["IsMock"] != "false" or row["ResolutionStatus"] != "VERIFIED":
            blockers.append("not_verified_live_resolution")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,190}", external_id):
            blockers.append("invalid_provider_id")
        if row["ListSeCd"] != "1" or row["ISBN"] or row["SetISBN"]:
            blockers.append("missing_webtoon_code_or_book_indicator")
        if not title or len(title) > 255:
            blockers.append("invalid_title")
        normalized_platform = normalized(platform).replace(" ", "")
        if not platform or len(platform) > 80 or any(
            marker in normalized_platform for marker in ("네이버시리즈", "naverseries", "단행본")
        ) or normalized_platform == "book":
            blockers.append("unsupported_platform")
        if not valid_authors:
            blockers.append("invalid_authors")
        if raw_cover and not cover:
            blockers.append("invalid_cover_source")
        missing = [name for name, value in (
            ("authors", valid_authors), ("genre", genre), ("synopsis", synopsis), ("cover_source", cover),
            ("serial_start_date", (row.get("SerialStartDate") or "").strip()),
        ) if not value]
        outcome = {"title": title, "external_id": external_id, "missing": missing, "blockers": blockers}
        outcomes.append(outcome)
        if blockers:
            continue
        record = {
            "external_id": external_id, "title": title, "platform": platform,
            "authors": list(dict.fromkeys(author.strip() for author in authors)),
            "genre": genre, "synopsis": synopsis, "cover_source_url": cover, "serial_status": None,
            "preserve_missing_metadata": True,
        }
        candidates.append((outcome, record))
    identifiers = Counter(record["external_id"].casefold() for _, record in candidates)
    work_keys = Counter(work_key(record) for _, record in candidates)
    staged = []
    for outcome, record in candidates:
        if identifiers[record["external_id"].casefold()] > 1:
            outcome["blockers"].append("duplicate_provider_id")
        if work_keys[work_key(record)] > 1:
            outcome["blockers"].append("duplicate_work_identity")
        if not outcome["blockers"]:
            staged.append(record)
    return hashlib.sha256(data).hexdigest(), outcomes, staged


def stage_naver(source, metadata=None, additions=None):
    source_data = source.read_bytes()
    text = source_data.decode("utf-8-sig")
    if source.suffix == ".js":
        registry = re.search(r"Object\.freeze\((\{.*?\})\);", text, re.S)
        if not registry:
            raise KmasProviderError("Official review registry format changed")
        reviewed = json.loads(re.sub(r",\s*}$", "}", registry[1]))
        entries = [
            {**item, "authors": item["officialCredit"].split("·"), "original_ref": key}
            for key, item in reviewed.items() if item.get("status") == "verified"
        ]
    else:
        manifest = json.loads(text)
        entries = naver_manifest_entries(manifest)
    supplemental = {}
    digest = hashlib.sha256(source_data)
    if additions:
        extra_data = additions.read_bytes()
        digest.update(b"\0" + extra_data)
        entries.extend(naver_manifest_entries(json.loads(extra_data)))
    if metadata:
        metadata_data = metadata.read_bytes()
        digest.update(b"\0" + metadata_data)
        supplemental = {row["external_id"]: row for row in json.loads(metadata_data)}
    outcomes, candidates = [], []
    for row in entries:
        title = row["title"].strip()
        platform = row.get("platform", "네이버웹툰")
        official_url = row.get("official_url") or row.get("url") or ""
        url = urlsplit(official_url)
        match = re.fullmatch(r"titleId=([1-9][0-9]{0,18})", url.query)
        reference = row.get("original_ref") or official_url
        extra = supplemental.get(reference, {})
        genre = row.get("genre") or (
            extra.get("genre") if extra.get("title") == title and extra.get("platform") == platform else ""
        )
        authors = list(dict.fromkeys(author.strip() for author in row["authors"] if author.strip()))
        external_id = match[1] if match else ""
        valid = (
            url.scheme == "https" and url.netloc in ("comic.naver.com", "m.comic.naver.com")
            and url.path == "/webtoon/list" and not url.fragment and match
            and platform == "네이버웹툰" and 0 < len(title) <= 255 and authors
        )
        outcome = {
            "title": title, "normalized_title": normalized(title), "external_id": external_id,
            "provider": "naver_webtoon", "platform": platform, "authors": authors, "genre": genre,
            "original_ref": reference, "official_url": official_url,
            "reviewed_at": row.get("reviewed_at") or ("2026-11-23" if source.suffix == ".js" else None),
            "blockers": [] if valid else ["unverified_naver_work_identity"],
            "missing": ["synopsis", "cover_source"] + ([] if genre else ["genre"]),
        }
        outcomes.append(outcome)
        if valid:
            candidates.append((outcome, {
                "title": title, "platform": platform, "external_id": external_id,
                "provider": "naver_webtoon", "official_url": official_url, "authors": authors,
                "genre": genre, "serial_status": None, "preserve_missing_metadata": True,
            }))
    identifiers = Counter(row["external_id"] for _, row in candidates)
    keys = Counter(work_key(row) for _, row in candidates)
    for outcome, row in candidates:
        if identifiers[row["external_id"]] > 1 or keys[work_key(row)] > 1:
            outcome["blockers"].append("duplicate_reviewed_work_identity")
    return digest.hexdigest(), outcomes, [row for outcome, row in candidates if not outcome["blockers"]]


def naver_manifest_entries(manifest):
    if manifest.get("source") != "naver_webtoon" or not manifest.get("review_date"):
        raise KmasProviderError("Naver review manifest provenance is missing")
    return [{**row, "reviewed_at": manifest["review_date"]} for row in manifest["works"]]


def work_key(record):
    return (
        normalized(record["title"]), normalized(record["platform"]).replace(" ", ""),
        tuple(sorted({normalized(author) for author in record["authors"]})),
    )


def pack(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"


def write_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(pack(value))
        output.flush()
        os.fsync(output.fileno())


def verify_backup(path, database_review, snapshots):
    write_new(path, {"database": database_review, "snapshots": snapshots})
    saved = json.loads(path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(pack(saved["snapshots"]).encode("utf-8")).hexdigest()
    if saved["database"] != database_review or digest != database_review["state_sha256"]:
        raise KmasProviderError("Backup verification failed")


def examine_database(cursor, records, *, lock=False):
    if not required_schema_ready(cursor, require_cover_source=any(row.get("cover_source_url") for row in records)):
        raise KmasProviderError("Required webtoon catalog tables or columns are missing")
    cursor.execute("SELECT DATABASE() AS schema_name, @@server_uuid AS server_uuid")
    target = cursor.fetchone()
    if not target["schema_name"]:
        raise KmasProviderError("Select a database explicitly before importing")
    rows = []
    snapshots = []
    suffix = " FOR UPDATE" if lock else ""
    for record in records:
        external_id = record["external_id"]
        provider = record.get("provider", PROVIDER_CODE)
        cursor.execute(
            "SELECT * FROM content_external_ids WHERE provider_code=%s AND external_id=%s" + suffix,
            (provider, external_id),
        )
        identity = cursor.fetchone()
        content_id = int(identity["content_id"]) if identity else _content_id(external_id, provider)
        cursor.execute("SELECT * FROM contents WHERE id=%s ORDER BY type" + suffix, (content_id,))
        contents = cursor.fetchall()
        cursor.execute(
            "SELECT * FROM webtoon_metadata WHERE content_id=%s AND content_type='webtoon'" + suffix,
            (content_id,),
        )
        metadata = cursor.fetchone()
        blockers = []
        if identity and (identity["content_type"] != "webtoon" or not any(
            content["type"] == "webtoon" for content in contents
        ) or (metadata and metadata["source_provider"] != provider)):
            blockers.append("existing_provider_identity_conflict")
        if not identity and contents:
            blockers.append("internal_id_collision")
        if not identity:
            cursor.execute(
                """
                SELECT c.id, c.title, w.service_platform, x.external_id
                FROM contents c
                LEFT JOIN webtoon_metadata w ON w.content_id=c.id AND w.content_type=c.type
                LEFT JOIN content_external_ids x ON x.content_id=c.id AND x.content_type=c.type
                WHERE c.type='webtoon' AND (c.title=%s
                    OR w.official_url IN (%s, %s) OR x.source_url IN (%s, %s))
                ORDER BY c.id, x.provider_code, x.external_id
                """ + suffix, (
                    record["title"],
                    record.get("official_url"),
                    alternate_naver_url(record.get("official_url")),
                    record.get("official_url"),
                    alternate_naver_url(record.get("official_url")),
                ),
            )
            if cursor.fetchall():
                blockers.append("existing_title_requires_identity_review")
        rows.append({
            "external_id": external_id, "content_id": content_id,
            "action": "blocked" if blockers else "update" if identity else "insert", "blockers": blockers,
        })
        snapshots.append({"external_id": external_id, "identity": identity, "contents": contents, "metadata": metadata})
    internal_ids = Counter(row["content_id"] for row in rows)
    for row in rows:
        if internal_ids[row["content_id"]] > 1:
            row["action"] = "blocked"
            row["blockers"].append("duplicate_internal_id")
    return {
        "target": target, "actions": rows,
        "state_sha256": hashlib.sha256(pack(snapshots).encode("utf-8")).hexdigest(),
    }, snapshots


def alternate_naver_url(url):
    if url and url.startswith("https://m.comic.naver.com/"):
        return url.replace("https://m.comic.naver.com/", "https://comic.naver.com/", 1)
    if url and url.startswith("https://comic.naver.com/"):
        return url.replace("https://comic.naver.com/", "https://m.comic.naver.com/", 1)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["Stage", "DryRun", "ReviewBackup", "Apply"])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--resolution", type=Path)
    source.add_argument("--naver-evidence", type=Path)
    parser.add_argument("--genre-evidence", type=Path)
    parser.add_argument("--naver-reviewed-additions", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--approved-db-write", action="store_true")
    args = parser.parse_args()
    if args.mode == "Apply" and not (args.approved_db_write and args.backup):
        parser.error("Apply requires --approved-db-write and a new --backup path")
    if args.mode == "ReviewBackup" and not args.backup:
        parser.error("ReviewBackup requires a new --backup path")
    try:
        input_hash, outcomes, records = (
            stage_naver(args.naver_evidence, args.genre_evidence, args.naver_reviewed_additions)
            if args.naver_evidence else stage(args.resolution)
        )
        summary = {
            "input_sha256": input_hash, "verified_import_candidates": len(records), "outcomes": outcomes,
        }
        if args.mode == "Stage":
            write_new(args.report, summary)
            print(f"Staged {len(records)} of {len(outcomes)} resolution rows")
            return
        if not records and args.mode != "DryRun":
            raise KmasProviderError("No verified rows to back up or apply")
        from database import get_connection
        # The existing provider settings control whether descriptions and cover URLs may be displayed.
        settings = KmasSettings.from_env()
        summary["display"] = {
            "synopsis": settings.synopsis_display_allowed, "cover": settings.cover_display_allowed,
        }
        connection = get_connection()
        try:
            if args.mode in ("DryRun", "ReviewBackup"):
                connection.start_transaction(readonly=True)
                cursor = connection.cursor(dictionary=True)
                try:
                    summary["database"], snapshots = examine_database(cursor, records)
                finally:
                    cursor.close()
                    connection.rollback()
                if args.mode == "ReviewBackup":
                    if summary != json.loads(args.report.read_text(encoding="utf-8")) or any(
                        row["blockers"] for row in summary["database"]["actions"]
                    ):
                        raise KmasProviderError("Reviewed DryRun is stale or has DB conflicts; run DryRun again")
                    verify_backup(args.backup, summary["database"], snapshots)
                    print("Read-only review backup verified")
                    return
                write_new(args.report, summary)
                actions = Counter(row["action"] for row in summary["database"]["actions"])
                print(f"DryRun: {actions['insert']} insert, {actions['update']} update, {actions['blocked']} blocked")
                return
            reviewed = json.loads(args.report.read_text(encoding="utf-8"))

            def backup_reviewed_rows(cursor):
                summary["database"], snapshots = examine_database(cursor, records, lock=True)
                if summary != reviewed or any(row["blockers"] for row in summary["database"]["actions"]):
                    raise KmasProviderError("Reviewed DryRun is stale or has DB conflicts; run DryRun again")
                verify_backup(args.backup, summary["database"], snapshots)

            count = persist_catalog(connection, records, settings, before_write=backup_reviewed_rows)
            print(f"Committed {count} webtoon rows")
        finally:
            connection.close()
    except (OSError, ValueError, KmasProviderError) as error:
        parser.exit(1, f"Webtoon staging failed: {error}\n")
    except Exception as error:
        parser.exit(1, f"Webtoon staging failed ({type(error).__name__}); consult local DB configuration\n")


if __name__ == "__main__":
    main()
