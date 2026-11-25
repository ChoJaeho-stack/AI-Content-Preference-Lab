import unittest
import urllib.parse
import os
import io
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from contextlib import redirect_stderr

import kmas_webtoon_provider as provider

from kmas_webtoon_provider import (
    KmasProviderError,
    KmasSettings,
    fetch_catalog,
    load_kmas_environment,
    parse_response,
    request_page,
)


def response(*items, total=None):
    return {"result": {
        "resultState": "success",
        "resultMessage": "성공",
        "totalCount": len(items) if total is None else total,
        "itemlist": list(items),
    }}


def webtoon(work_id="kmas-1", title="가상 검증작", **fields):
    return {
        "mastrId": work_id,
        "listSeCd": "1",
        "listSeCdNm": "웹툰",
        "prdctNm": title,
        "pictrWritrNm": "그림 작가",
        "sntncWritrNm": "글 작가",
        "mainGenreCdNm": "판타지",
        "outline": "권리 확인 전 비공개 줄거리",
        "imageDownloadUrl": "https://api.example.invalid/cover/1",
        **fields,
    }


class KmasProviderTests(unittest.TestCase):
    def settings(self, **overrides):
        defaults = dict(
            mode="mock", approved=False, api_key="", base_url="",
            page_size=100, max_pages=10,
            synopsis_display_allowed=False, cover_display_allowed=False,
        )
        defaults.update(overrides)
        return KmasSettings(**defaults)

    def test_live_calls_require_explicit_approval_key_and_verified_https_root(self):
        settings = self.settings(mode="live", approved=True, api_key="secret")
        with self.assertRaisesRegex(KmasProviderError, "BASE_URL"):
            settings.validate_live_access()
        with self.assertRaisesRegex(KmasProviderError, "approval"):
            self.settings(mode="live", base_url="https://api.example.invalid").validate_live_access()
        self.assertTrue(settings.api_key == "secret")

    def test_live_title_search_quarantines_duplicate_internal_identity_and_filters_editions(self):
        serial = {"prdctNm": "Test Webtoon", "title": "Test Webtoon",
                  "pltfomCdNm": "Webtoon Platform", "pictrWritrNm": "Test Artist",
                  "outline": "Restricted synopsis", "imageDownloadUrl": "https://example.invalid/cover"}
        rows = [serial, dict(serial), dict(serial, isbn="123"),
                dict(serial, title="Test Webtoon 2"), dict(serial, pltfomCdNm="")]
        total, item = provider.parse_title_search(
            {"result": {"resultState": "success", "totalCount": len(rows)}, "itemList": rows},
            "Test Webtoon",
        )
        self.assertEqual(total, 5)
        self.assertIsNone(item)
        unique_total, item = provider.parse_title_search(
            {"result": {"resultState": "success", "totalCount": 1}, "itemList": [serial]},
            "Test Webtoon",
        )
        self.assertEqual(unique_total, 1)
        self.assertEqual(item["title"], "Test Webtoon")
        self.assertEqual(item["authors"], ["Test Artist"])
        self.assertEqual(item["synopsis"], "")
        self.assertIsNone(item["cover_source_url"])
        self.assertIsNone(item["external_id"])
        self.assertTrue(item["internal_identity"].startswith("title-search:"))
        self.assertLess(provider._content_id(item["internal_identity"]), 2**53)

    def test_title_search_rejects_placeholder_author_for_internal_identity(self):
        payload = {"result": {"resultState": "success", "totalCount": 1}, "itemList": [{
            "prdctNm": "Test Webtoon", "title": "Test Webtoon", "pltfomCdNm": "네이버웹툰",
            "pictrWritrNm": "네이버웹툰작가",
        }]}
        self.assertEqual(provider.parse_title_search(payload, "Test Webtoon"), (1, None))

    def test_title_search_prefers_webtoon_over_series_and_nested_book_editions(self):
        rows = [
            {"prdctNm": "화산귀환", "title": "화산귀환 " + str(index),
             "isbn": "book-" + str(index), "pltfomCdNm": "", "pictrWritrNm": "스튜디오 리코"}
            for index in range(1, 9)
        ]
        rows.extend([
            {"prdctNm": "화산귀환", "title": "화산귀환", "pltfomCdNm": "네이버시리즈",
             "pictrWritrNm": "스튜디오 리코", "mainGenreCdNm": "판타지"},
            {"prdctNm": "화산귀환", "title": "화산귀환", "pltfomCdNm": "네이버웹툰",
             "pictrWritrNm": "스튜디오 리코", "mainGenreCdNm": "판타지"},
        ])
        payload = {"result": {"resultState": "success", "totalCount": 10,
                              "itemlist": {"item": [[rows[:4]], rows[4:]]}}}
        total, item = provider.parse_title_search(payload, " 화산귀환 ")
        self.assertEqual(total, 10)
        self.assertIsNotNone(item)
        self.assertEqual(item["platform"], "네이버웹툰")
        self.assertEqual(item["genre"], "판타지")

    def test_title_search_does_not_promote_naver_series_to_webtoon(self):
        row = {"prdctNm": "제목", "title": "제목", "pltfomCdNm": "네이버시리즈",
               "pictrWritrNm": "작가"}
        _, item = provider.parse_title_search(response(row), "제목")
        self.assertIsNone(item)

    def test_title_search_prefers_exact_naver_webtoon_over_other_platform(self):
        base = {"prdctNm": "제목", "title": "제목", "pictrWritrNm": "작가"}
        rows = [dict(base, pltfomCdNm="다른 웹툰 플랫폼"),
                dict(base, pltfomCdNm="네이버웹툰")]
        _, item = provider.parse_title_search(response(*rows), "제목")
        self.assertEqual(item["platform"], "네이버웹툰")

    def test_title_cli_reserves_each_request_and_saves_unique_matches_together(self):
        settings = self.settings(mode="live", approved=True, api_key="test-key",
                                 base_url="https://api.example.invalid")
        connection = MagicMock()
        serial = {"prdctNm": "Test Webtoon", "title": "Test Webtoon",
                  "pltfomCdNm": "Test Platform", "pictrWritrNm": "Test Artist"}
        payloads = [
            {"result": {"resultState": "success", "totalCount": 1}, "itemList": [serial]},
            {"result": {"resultState": "success", "totalCount": 0}},
        ]
        calls = MagicMock()
        calls.request.side_effect = payloads
        calls.persist.return_value = 1
        with patch.object(KmasSettings, "from_env", return_value=settings), \
                patch("database.get_connection", return_value=connection), \
                patch.object(provider, "sync_schema_ready", return_value=True) as schema, \
                patch.object(provider, "reserve_daily_request", calls.reserve), \
                patch.object(provider, "request_page", calls.request), \
                patch.object(provider, "persist_catalog", calls.persist), \
                patch("builtins.print"):
            provider.main(["--title", "Test Webtoon", "--title", "Missing",
                           "--title", "Test Webtoon", "--approved-db-write"])
        _, record = provider.parse_title_search(payloads[0], "Test Webtoon")
        schema.assert_called_once_with(
            connection, require_cover_source=False, require_external_ids=False
        )
        self.assertEqual([call[0] for call in calls.mock_calls],
                         ["reserve", "request", "reserve", "request", "persist"])
        self.assertEqual([call.kwargs["title"] for call in calls.request.call_args_list],
                         ["Test Webtoon", "Missing"])
        calls.persist.assert_called_once_with(connection, [record], settings)
        connection.close.assert_called_once()

    def test_title_cli_requires_explicit_database_write_approval_before_side_effects(self):
        with patch.object(KmasSettings, "from_env") as settings, \
                patch("database.get_connection") as get_connection, \
                redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                provider.main(["--title", "Test Webtoon"])
        settings.assert_not_called()
        get_connection.assert_not_called()

    def test_title_cli_does_not_save_a_partial_batch(self):
        settings = self.settings(mode="live", approved=True, api_key="test-key",
                                 base_url="https://api.example.invalid")
        connection = MagicMock()
        complete = {"result": {"resultState": "success", "totalCount": 1}, "itemList": [
            {"prdctNm": "First", "title": "First", "pltfomCdNm": "Test Platform",
             "pictrWritrNm": "Test Artist"},
        ]}
        incomplete = {"result": {"resultState": "success", "totalCount": 2},
                      "itemList": complete["itemList"]}
        with patch.object(KmasSettings, "from_env", return_value=settings), \
                patch("database.get_connection", return_value=connection), \
                patch.object(provider, "sync_schema_ready", return_value=True), \
                patch.object(provider, "reserve_daily_request"), \
                patch.object(provider, "request_page", side_effect=[complete, incomplete]), \
                patch.object(provider, "persist_catalog") as persist:
            with self.assertRaisesRegex(KmasProviderError, "incomplete"):
                provider.main(["--title", "First", "--title", "Incomplete", "--approved-db-write"])
        persist.assert_not_called()
        connection.close.assert_called_once()

    def test_uses_documented_envelope_and_excludes_book_rows(self):
        total, rows = parse_response(response(
            webtoon(),
            {"mastrId": "book-1", "listSeCd": "2", "prdctNm": "만화책"},
        ))
        self.assertEqual(total, 2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["external_id"], "kmas-1")
        self.assertEqual(rows[0]["authors"], ["글 작가", "그림 작가"])
        self.assertEqual(rows[0]["cover_source_url"], "https://api.example.invalid/cover/1")

    def test_live_request_uses_documented_webtoon_selector_and_never_follows_redirects(self):
        settings = self.settings(mode="live", approved=True, api_key="mock-secret",
                                 base_url="https://api.example.invalid")
        http_response = MagicMock()
        http_response.status = 200
        http_response.headers.get.return_value = "application/json"
        http_response.read.return_value = b'{"result":{"resultState":"success","totalCount":0,"itemlist":[]}}'
        http_response.__enter__.return_value = http_response
        opener = MagicMock()
        opener.open.return_value = http_response
        with patch("kmas_webtoon_provider.urllib.request.build_opener", return_value=opener) as build_opener:
            payload = request_page(settings, 3)
        request = opener.open.call_args.args[0]
        parsed_url = urllib.parse.urlsplit(request.full_url)
        query = urllib.parse.parse_qs(parsed_url.query)
        self.assertEqual(parsed_url.path, "/openapi/search/bookAndWebtoonList")
        self.assertEqual(query["listSeCd"], ["1"])
        self.assertEqual(query["pageNo"], ["3"])
        self.assertEqual(query["viewItemCnt"], ["100"])
        self.assertEqual(query["prvKey"], ["mock-secret"])
        self.assertEqual(payload["result"]["resultState"], "success")
        opener.open.assert_called_once()
        redirect_handler = build_opener.call_args.args[0]()
        self.assertIsNone(redirect_handler.redirect_request(None, None, 302, "Found", {}, "https://other.invalid"))

    def test_mock_pages_dedupe_by_provider_id_and_stop_at_total(self):
        pages = [response(webtoon(), total=2), response(webtoon("kmas-2", "두 번째"), total=2)]
        rows = fetch_catalog(self.settings(), lambda page: pages[page])
        self.assertEqual([row["external_id"] for row in rows], ["kmas-1", "kmas-2"])

    def test_empty_catalog_is_valid_but_premature_empty_page_is_rejected(self):
        self.assertEqual(fetch_catalog(self.settings(), lambda page: response(total=0)), [])
        with self.assertRaisesRegex(KmasProviderError, "ended before"):
            fetch_catalog(self.settings(), lambda page: response(total=1))

    def test_rejects_unknown_schema_unsuccessful_response_and_conflicting_duplicate(self):
        for payload in ({"items": []}, {"result": {"resultState": "error", "itemlist": []}}):
            with self.subTest(payload=payload), self.assertRaises(KmasProviderError):
                parse_response(payload)
        pages = [response(webtoon(), total=2), response(webtoon(title="충돌 제목"), total=2)]
        with self.assertRaisesRegex(KmasProviderError, "conflicting duplicate"):
            fetch_catalog(self.settings(), lambda page: pages[page])

    def test_missing_identifier_or_title_is_rejected_and_source_url_is_not_trusted(self):
        with self.assertRaisesRegex(KmasProviderError, "ID or title"):
            parse_response(response({"listSeCd": "1", "mastrId": "x"}))
        _, rows = parse_response(response(webtoon(imageDownloadUrl="javascript:alert(1)")))
        self.assertIsNone(rows[0]["cover_source_url"])

    def test_environment_defaults_to_mock_and_rights_are_closed(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(provider, "load_kmas_environment"):
            settings = KmasSettings.from_env()
        self.assertEqual(settings.mode, "mock")
        self.assertFalse(settings.approved)
        self.assertFalse(settings.cover_display_allowed)
        self.assertFalse(settings.synopsis_display_allowed)

    def test_dotenv_fills_blank_environment_and_recognizes_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "KMAS_API_KEY=local-test-key\n"
                "KMAS_API_APPROVED=true\n"
                "KMAS_API_BASE_URL=https://api.example.test\n"
                "KMAS_API_MODE=live\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {
                "KMAS_API_KEY": "", "KMAS_API_APPROVED": "",
                "KMAS_API_BASE_URL": "", "KMAS_API_MODE": "",
            }, clear=True):
                load_kmas_environment(env_file)
                settings = KmasSettings.from_env()
                self.assertEqual(settings.api_key, "local-test-key")
                self.assertTrue(settings.approved)
                self.assertEqual(settings.base_url, "https://api.example.test")
                self.assertEqual(settings.mode, "live")

    def test_nonempty_process_environment_takes_precedence_over_dotenv(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("KMAS_API_APPROVED=false\n", encoding="utf-8")
            with patch.dict(os.environ, {"KMAS_API_APPROVED": "true"}, clear=True):
                load_kmas_environment(env_file)
                self.assertTrue(KmasSettings.from_env().approved)

    def test_internal_id_is_stable_for_existing_member_content_references(self):
        first = provider._content_id("kmas-record-42")
        self.assertEqual(first, provider._content_id("kmas-record-42"))
        self.assertNotEqual(first, provider._content_id("kmas-record-43"))

    def test_persistence_keeps_cover_source_private_and_rights_closed_by_default(self):
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value = cursor
        cursor.fetchone.side_effect = [
            {"acquired": 1},  # advisory lock
            None,             # no existing provider ID
            None,             # no internal ID collision
        ]
        cursor.fetchall.return_value = []
        with patch.object(provider, "required_schema_ready", return_value=True):
            inserted = provider.persist_catalog(connection, [{
                "external_id": "mock-1", "title": "가상 검증작", "authors": ["작가"],
                "genre": "판타지", "synopsis": "권리 미확인 줄거리", "cover_source_url": "https://api.example.invalid/cover",
                "platform": "KMAS", "serial_status": "연재 정보 미확인",
            }], self.settings())
        self.assertEqual(inserted, 1)
        self.assertTrue(connection.commit.called)
        content_insert = next(call for call in cursor.execute.call_args_list
                              if "INSERT INTO contents" in call.args[0])
        self.assertEqual(content_insert.args[1][2], "")
        self.assertEqual(content_insert.args[1][3], "/posters/webtoon-cover-unavailable.svg")
        metadata_insert = next(call for call in cursor.execute.call_args_list
                               if "INSERT INTO webtoon_metadata" in call.args[0])
        self.assertEqual(metadata_insert.args[1][3], "https://api.example.invalid/cover")

    def test_title_search_internal_identity_never_becomes_provider_external_id(self):
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value = cursor
        cursor.fetchone.side_effect = [
            {"acquired": 1},  # advisory lock
            None,              # no content ID collision
        ]
        cursor.fetchall.return_value = []
        record = {
            "external_id": None,
            "internal_identity": "title-search:verified-fingerprint",
            "title": "Verified title", "authors": ["Verified author", "Second author"],
            "genre": "Action", "synopsis": "", "cover_source_url": None,
            "platform": "Naver Webtoon", "serial_status": None,
        }
        with patch.object(provider, "required_schema_ready", return_value=True):
            inserted = provider.persist_catalog(connection, [record], self.settings())
        self.assertEqual(inserted, 1)
        self.assertFalse(any("INSERT INTO content_external_ids" in call.args[0]
                             for call in cursor.execute.call_args_list))
        content_insert = next(call for call in cursor.execute.call_args_list
                              if "INSERT INTO contents" in call.args[0])
        expected_internal_id = provider._content_id(record["internal_identity"])
        self.assertEqual(content_insert.args[1][0], expected_internal_id)

    def test_internal_only_metadata_does_not_require_external_id_schema(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"external_mapping_foreign_keys": 0}
        metadata_columns = (
            "content_id", "content_type", "service_platform", "authors", "genre_tags",
            "story_tags", "mood_tags", "pacing", "serial_status", "source_provider",
        )
        cursor.fetchall.return_value = [
            {"table_name": "webtoon_metadata", "column_name": column}
            for column in metadata_columns
        ]
        self.assertTrue(provider.required_schema_ready(
            cursor, require_cover_source=False, require_external_ids=False
        ))
        self.assertFalse(provider.required_schema_ready(
            cursor, require_cover_source=False, require_external_ids=True
        ))

    def test_internal_only_metadata_fails_closed_while_external_id_fk_exists(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {"table_name": "webtoon_metadata", "column_name": column}
            for column in (
                "content_id", "content_type", "service_platform", "authors", "genre_tags",
                "story_tags", "mood_tags", "pacing", "serial_status", "source_provider",
            )
        ]
        cursor.fetchone.return_value = {"external_mapping_foreign_keys": 1}
        self.assertFalse(provider.required_schema_ready(
            cursor, require_cover_source=False, require_external_ids=False
        ))

    def test_title_search_internal_identity_is_idempotent_for_matching_existing_row(self):
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value = cursor
        record = {
            "external_id": None,
            "internal_identity": "title-search:verified-fingerprint",
            "title": "Verified title", "authors": ["Verified author", "Second author"],
            "genre": "Action", "synopsis": "", "cover_source_url": None,
            "platform": "Naver Webtoon", "serial_status": None,
        }
        cursor.fetchone.side_effect = [
            {"acquired": 1},
            {"type": "webtoon", "title": "Verified title", "service_platform": "Naver Webtoon",
             "authors": '["Second author", "Verified author"]', "source_provider": "kmas"},
        ]
        with patch.object(provider, "required_schema_ready", return_value=True):
            inserted = provider.persist_catalog(connection, [record], self.settings())
        self.assertEqual(inserted, 1)
        self.assertFalse(any("INSERT INTO content_external_ids" in call.args[0]
                             for call in cursor.execute.call_args_list))
        self.assertTrue(connection.commit.called)

    def test_new_internal_identity_with_existing_title_is_blocked_for_manual_review(self):
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value = cursor
        cursor.fetchone.side_effect = [{"acquired": 1}, None]
        cursor.fetchall.return_value = [{"id": 991, "title": "Verified title"}]
        record = {
            "external_id": None, "internal_identity": "title-search:verified-fingerprint",
            "title": "Verified title", "authors": ["Another author"], "genre": "Action",
            "synopsis": "", "cover_source_url": None, "platform": "Naver Webtoon",
            "serial_status": None,
        }
        with patch.object(provider, "required_schema_ready", return_value=True):
            with self.assertRaisesRegex(KmasProviderError, "requires identity review"):
                provider.persist_catalog(connection, [record], self.settings())
        connection.rollback.assert_called_once()
        self.assertFalse(any("INSERT INTO contents" in call.args[0]
                             for call in cursor.execute.call_args_list))

    def test_title_search_internal_identity_collision_with_different_work_rolls_back(self):
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value = cursor
        cursor.fetchone.side_effect = [
            {"acquired": 1},
            {"type": "webtoon", "title": "Different title", "service_platform": "Naver Webtoon",
             "authors": '["Verified author"]', "source_provider": "kmas"},
        ]
        with patch.object(provider, "required_schema_ready", return_value=True):
            with self.assertRaisesRegex(KmasProviderError, "collides with a different content row"):
                provider.persist_catalog(connection, [{
                    "external_id": None, "internal_identity": "title-search:verified-fingerprint",
                    "title": "Verified title", "authors": ["Verified author"], "genre": "Action",
                    "synopsis": "", "cover_source_url": None, "platform": "Naver Webtoon",
                    "serial_status": None,
                }], self.settings())
        connection.rollback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
