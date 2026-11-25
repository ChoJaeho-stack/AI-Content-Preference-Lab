import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import kmas_staging_import as staging
from kmas_webtoon_provider import KmasProviderError, KmasSettings, persist_catalog


class StagingImportTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.source = Path(directory.name) / "resolved.csv"
        self.row = {
            "Title": "Fixture title", "Platform": "Naver Webtoon", "Genre": "",
            "AuthorsJson": '["Fixture author"]', "KMASExternalId": "fixture-101", "ListSeCd": "1",
            "ISBN": "", "SetISBN": "", "Synopsis": "", "CoverSourceUrl": "",
            "IsMock": "false", "ResolutionStatus": "VERIFIED",
        }

    def write_rows(self, *rows):
        with self.source.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=self.row)
            writer.writeheader()
            writer.writerows(rows)

    def test_stages_verified_webtoon_and_reports_missing_metadata(self):
        self.write_rows(self.row)
        digest, outcomes, records = staging.stage(self.source)
        self.assertEqual(digest, hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(outcomes[0]["missing"], ["genre", "synopsis", "cover_source", "serial_start_date"])
        self.assertEqual(records[0]["external_id"], "fixture-101")
        self.assertIsNone(records[0]["cover_source_url"])
        self.assertLessEqual(staging._content_id("fixture-101"), 2**53 - 1)

    def test_blocks_series_book_mock_and_synthetic_id(self):
        self.write_rows(
            dict(self.row, Platform="Naver Series"), dict(self.row, ISBN="9780000000000"),
            dict(self.row, IsMock="true"), dict(self.row, KMASExternalId="title-search:abc"),
        )
        _, outcomes, records = staging.stage(self.source)
        self.assertFalse(records)
        self.assertEqual([row["blockers"][0] for row in outcomes], [
            "unsupported_platform", "missing_webtoon_code_or_book_indicator",
            "not_verified_live_resolution", "invalid_provider_id",
        ])

    def test_blocks_duplicate_provider_and_work_identities(self):
        self.write_rows(self.row, dict(self.row, Title="Another work", KMASExternalId="FIXTURE-101"))
        _, outcomes, records = staging.stage(self.source)
        self.assertFalse(records)
        self.assertTrue(all("duplicate_provider_id" in row["blockers"] for row in outcomes))
        self.write_rows(self.row, dict(self.row, KMASExternalId="fixture-102"))
        _, outcomes, records = staging.stage(self.source)
        self.assertFalse(records)
        self.assertTrue(all("duplicate_work_identity" in row["blockers"] for row in outcomes))

    def test_naver_evidence_uses_platform_id_and_rejects_untrusted_urls(self):
        work = {
            "title": "Fixture", "authors": ["Fixture Author"], "genre": "Fantasy",
            "official_url": "https://comic.naver.com/webtoon/list?titleId=123",
        }
        self.source.write_text(json.dumps({
            "source": "naver_webtoon", "review_date": "2026-11-24",
            "works": [work, {**work, "official_url": "https://comic.naver.com.example.invalid/webtoon/list?titleId=123"}],
        }), encoding="utf-8")
        _, outcomes, records = staging.stage_naver(self.source)
        self.assertEqual([row["external_id"] for row in records], ["123"])
        self.assertEqual(records[0]["provider"], "naver_webtoon")
        self.assertEqual(outcomes[1]["blockers"], ["unverified_naver_work_identity"])
        self.assertNotEqual(staging._content_id("123", "naver_webtoon"), staging._content_id("123"))

    def test_database_review_blocks_existing_title_without_mapping(self):
        self.write_rows(self.row)
        _, _, records = staging.stage(self.source)
        cursor = MagicMock()
        cursor.fetchone.side_effect = [{"schema_name": "fixture", "server_uuid": "fixture"}, None, None]
        cursor.fetchall.side_effect = [[], [{"external_id": "title-search:existing"}]]
        with patch.object(staging, "required_schema_ready", return_value=True):
            review, _ = staging.examine_database(cursor, records)
        self.assertEqual(review["actions"][0]["blockers"], ["existing_title_requires_identity_review"])

    def test_rejected_backup_runs_before_any_writes_and_rolls_back(self):
        self.write_rows(self.row)
        _, _, records = staging.stage(self.source)
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.fetchone.return_value = {"acquired": 1}
        settings = KmasSettings("mock", False, "", "", 100, 10, False, False)
        reject_backup = MagicMock(side_effect=KmasProviderError("fixture backup rejection"))
        with patch("kmas_webtoon_provider.required_schema_ready", return_value=True), \
                self.assertRaisesRegex(KmasProviderError, "fixture backup rejection"):
            persist_catalog(connection, records, settings, before_write=reject_backup)
        reject_backup.assert_called_once_with(cursor)
        connection.rollback.assert_called_once()
        self.assertFalse(any("INSERT" in call.args[0] for call in cursor.execute.call_args_list))

    def test_review_backup_verifies_snapshot_and_never_replaces_a_file(self):
        snapshots = [{"identity": None, "contents": [], "metadata": None}]
        review = {"state_sha256": hashlib.sha256(staging.pack(snapshots).encode("utf-8")).hexdigest()}
        backup = self.source.with_name("backup.json")
        staging.verify_backup(backup, review, snapshots)
        self.assertEqual(json.loads(backup.read_text(encoding="utf-8"))["snapshots"], snapshots)
        with self.assertRaises(FileExistsError):
            staging.verify_backup(backup, review, snapshots)
        with self.assertRaisesRegex(KmasProviderError, "Backup verification failed"):
            staging.verify_backup(self.source, review, [])

    def test_reimport_preserves_metadata_missing_from_staging(self):
        self.write_rows(self.row)
        _, _, records = staging.stage(self.source)
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.fetchone.side_effect = [
            {"acquired": 1}, {"content_id": 123, "content_type": "webtoon"}, None,
        ]
        settings = KmasSettings("mock", False, "", "", 100, 10, False, False)
        with patch("kmas_webtoon_provider.required_schema_ready", return_value=True):
            self.assertEqual(persist_catalog(connection, records, settings), 1)
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        content_update = next(sql.split("UPDATE", 1)[1] for sql in statements if "INSERT INTO contents" in sql)
        metadata_update = next(sql.split("UPDATE", 1)[1] for sql in statements if "INSERT INTO webtoon_metadata" in sql)
        self.assertNotIn("overview=", content_update)
        self.assertNotIn("poster_url=", content_update)
        self.assertNotIn("genre_tags=", metadata_update)
        self.assertNotIn("cover_source_url=", metadata_update)


if __name__ == "__main__":
    unittest.main()
