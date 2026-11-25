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
            fields = list(self.row) + sorted({key for row in rows for key in row if key not in self.row})
            writer = csv.DictWriter(output, fieldnames=fields)
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

    def test_stages_internal_identity_without_fabricating_provider_id(self):
        from kmas_webtoon_provider import internal_identity_for
        row = dict(self.row)
        row.update({
            "KMASExternalId": "", "ListSeCd": "", "ResolutionStatus": "VERIFIED_INTERNAL",
            "IdentityKind": "internal", "InternalIdentity": internal_identity_for(
                row["Title"], row["Platform"], ["Fixture author"]
            ),
        })
        self.write_rows(row)
        _, outcomes, records = staging.stage(self.source)
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0]["external_id"])
        self.assertEqual(records[0]["internal_identity"], row["InternalIdentity"])
        self.assertEqual(outcomes[0]["identity_kind"], "internal")

    def test_blocks_fabricated_internal_identity_and_official_id_alias(self):
        row = dict(self.row)
        row.update({
            "KMASExternalId": "", "ListSeCd": "", "ResolutionStatus": "VERIFIED_INTERNAL",
            "IdentityKind": "internal", "InternalIdentity": "title-search:fake",
        })
        self.write_rows(row)
        _, outcomes, records = staging.stage(self.source)
        self.assertFalse(records)
        self.assertIn("invalid_internal_identity", outcomes[0]["blockers"])
        row["InternalIdentity"] = "title-search:" + "a" * 64
        row["KMASExternalId"] = row["InternalIdentity"]
        self.write_rows(row)
        _, outcomes, records = staging.stage(self.source)
        self.assertFalse(records)
        self.assertIn("internal_identity_must_not_claim_provider_id", outcomes[0]["blockers"])

    def test_blocks_internal_duplicate_identity(self):
        from kmas_webtoon_provider import internal_identity_for
        row = dict(self.row)
        row.update({
            "KMASExternalId": "", "ListSeCd": "", "ResolutionStatus": "VERIFIED_INTERNAL",
            "IdentityKind": "internal", "InternalIdentity": internal_identity_for(
                row["Title"], row["Platform"], ["Fixture author"]
            ),
        })
        self.write_rows(row, dict(row))
        _, outcomes, records = staging.stage(self.source)
        self.assertFalse(records)
        self.assertTrue(all("duplicate_internal_identity" in out["blockers"] for out in outcomes))

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

    def test_database_review_supports_internal_identity_insert_and_idempotent_update(self):
        from kmas_webtoon_provider import internal_identity_for
        record = {
            "external_id": None,
            "internal_identity": internal_identity_for(
                "Fixture title", "Naver Webtoon", ["Fixture author", "Second author"]
            ),
            "title": "Fixture title", "platform": "Naver Webtoon",
            "authors": ["Fixture author", "Second author"],
            "genre": "", "synopsis": "", "cover_source_url": None,
        }
        cursor = MagicMock()
        cursor.fetchone.side_effect = [{"schema_name": "fixture", "server_uuid": "fixture"}, None, None]
        cursor.fetchall.side_effect = [[], []]
        with patch.object(staging, "required_schema_ready", return_value=True) as schema_check:
            review, _ = staging.examine_database(cursor, [record])
        self.assertEqual(review["actions"][0]["action"], "insert")
        self.assertIsNone(review["actions"][0]["external_id"])
        self.assertIsNotNone(review["actions"][0]["internal_identity"])
        self.assertFalse(schema_check.call_args.kwargs["require_external_ids"])
        self.assertFalse(any("content_external_ids" in call.args[0] for call in cursor.execute.call_args_list))

        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {"schema_name": "fixture", "server_uuid": "fixture"},
            {"service_platform": "Naver Webtoon", "source_provider": "kmas",
             "authors": '["Second author", "Fixture author"]'},
        ]
        cursor.fetchall.return_value = [{"type": "webtoon", "title": "Fixture title"}]
        with patch.object(staging, "required_schema_ready", return_value=True):
            review, _ = staging.examine_database(cursor, [record])
        self.assertEqual(review["actions"][0]["action"], "update")
        self.assertFalse(review["actions"][0]["blockers"])

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

    def test_internal_identity_apply_path_never_writes_provider_mapping(self):
        from kmas_webtoon_provider import internal_identity_for
        record = {
            "external_id": None,
            "internal_identity": internal_identity_for("Fixture title", "Naver Webtoon", ["Fixture author"]),
            "title": "Fixture title", "platform": "Naver Webtoon", "authors": ["Fixture author"],
            "genre": "", "synopsis": "", "cover_source_url": None, "serial_status": None,
            "preserve_missing_metadata": True,
        }
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.fetchone.side_effect = [{"acquired": 1}, None]
        cursor.fetchall.return_value = []
        settings = KmasSettings("mock", False, "", "", 100, 10, False, False)
        with patch("kmas_webtoon_provider.required_schema_ready", return_value=True) as schema_check:
            self.assertEqual(persist_catalog(connection, [record], settings), 1)
        self.assertFalse(schema_check.call_args.kwargs["require_external_ids"])
        sql = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any("INSERT INTO contents" in statement for statement in sql))
        self.assertTrue(any("INSERT INTO webtoon_metadata" in statement for statement in sql))
        self.assertFalse(any("content_external_ids" in statement for statement in sql))
        connection.commit.assert_called()


if __name__ == "__main__":
    unittest.main()
