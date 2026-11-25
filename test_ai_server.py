import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from fastapi.testclient import TestClient

with patch("google.genai.Client"):
    import ai_server


def content(content_id, kind, title, genres):
    item = {"id": content_id, "type": kind, "title": title,
            "genre_ids": genres, "rating": 8}
    if kind == "webtoon":
        item.update(source_provider="kmas", external_id=f"fixture-{content_id}")
    return item


class RecommendationTest(unittest.TestCase):
    def test_gemini_selects_only_verified_webtoon_explanations(self):
        rows = [{"title": "Fixture", "reason": "정해진 이유", "id": 123, "match_score": 80}]
        choices = [["정해진 이유", "확인된 장르"]]
        model = SimpleNamespace(models=SimpleNamespace())
        model.models.generate_content = unittest.mock.Mock()
        with patch.dict("os.environ", {"WEBTOON_GEMINI_REASON_SELECTION": "true"}), \
                patch.object(ai_server, "ai_mode", "gemini"), patch.object(ai_server, "client", model):
            model.models.generate_content.return_value = SimpleNamespace(text='{"choices":[1]}')
            ai_server.select_webtoon_reasons(rows, choices)
            self.assertEqual(rows[0]["reason"], "확인된 장르")
            self.assertNotIn("123", model.models.generate_content.call_args.kwargs["contents"])
            model.models.generate_content.return_value = SimpleNamespace(text='{"choices":["가짜 설명"]}')
            ai_server.select_webtoon_reasons(rows, choices)
            model.models.generate_content.side_effect = TimeoutError
            ai_server.select_webtoon_reasons(rows, choices)
        self.assertEqual(rows, [{"title": "Fixture", "reason": "확인된 장르", "id": 123, "match_score": 80}])

    def test_webtoon_cross_provider_link_deduplication_and_legacy_exclusion(self):
        catalog = [
            {**content(1, "webtoon", "Fixture source one", []),
             "official_url": "https://m.comic.naver.com/webtoon/list?titleId=123",
             "taste_features": {"genres": ["fantasy"]}},
            {**content(2, "webtoon", "Fixture source two", []),
             "source_provider": "naver_webtoon", "external_id": "123",
             "taste_features": {"genres": ["fantasy"]}},
            {**content(3, "webtoon", "Fixture legacy", []),
             "external_id": "title-search:historical",
             "taste_features": {"genres": ["fantasy"]}},
        ]
        with patch.object(ai_server, "get_contents", return_value=catalog):
            response = self.client.post("/recommend", json={"taste": "추천", "contentType": "webtoon"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()["recommendations"]], [1])

    def test_local_mode_returns_scored_movie_and_tv_top_five_without_gemini(self):
        catalog = [
            {"id": index, "type": kind, "title": f"작품{index}",
             "genre_ids": genres, "rating": 7 + index / 10,
             "overview": "우주 모험과 미스터리 이야기", "poster_url": f"https://img/{index}.jpg",
             "ott": ["검증 OTT"]}
            for kind, genres, start in (("movie", [878], 100), ("tv", [18], 200))
            for index in range(start, start + 6)
        ]
        for kind, preference in (("movie", "영화"), ("tv", "드라마")):
            with self.subTest(kind=kind), \
                    patch.object(ai_server, "ai_mode", "local"), \
                    patch.object(ai_server, "get_contents", return_value=catalog), \
                    patch.object(ai_server, "generate_with_retry") as gemini:
                response = self.client.post("/recommend", json={
                    "taste": "우주 모험 미스터리 추천", "contentType": kind,
                    "preference": preference, "preferredGenres": [878] if kind == "movie" else [18],
                })
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertIn("Gemini API는 호출하지 않았습니다", payload["taste_analysis"])
            self.assertEqual(len(payload["recommendations"]), 5)
            self.assertTrue(all(item["type"] == kind for item in payload["recommendations"]))
            self.assertTrue(all(0 <= item["match_score"] <= 100 for item in payload["recommendations"]))
            self.assertTrue(all(item["poster_url"] and item["ott"] for item in payload["recommendations"]))
            self.assertTrue(all(item["genre_ids"] for item in payload["recommendations"]))
            self.assertTrue(all(item["reason"] for item in payload["recommendations"]))
            self.assertEqual(payload["recommendation_source"], "local")
            gemini.assert_not_called()

    def test_tv_drama_expands_only_to_related_variety_when_direct_matches_are_missing(self):
        catalog = [
            {"id": 10, "type": "tv", "title": "두뇌 예능", "genre_ids": [10764],
             "overview": "참가자들이 두뇌 게임에서 숨겨진 패턴을 찾는다"},
            {"id": 11, "type": "tv", "title": "두뇌게임 쇼", "genre_ids": [10764],
             "overview": "참가자들의 두뇌게임과 전략적인 선택을 다룬다"},
            {"id": 12, "type": "tv", "title": "가족 드라마", "genre_ids": [18],
             "overview": "가족의 일상과 성장을 그린 이야기"},
            {"id": 13, "type": "tv", "title": "좀비 감염", "genre_ids": [27],
             "overview": "공포와 감염에서 살아남으려는 사람들"},
            *[{"id": index, "type": "tv", "title": f"경쟁 드라마 {index}",
               "genre_ids": [18], "overview": "참가자들이 경쟁에서 우승하기 위해 겨룬다"}
              for index in range(14, 20)],
        ]
        with patch.object(ai_server, "ai_mode", "local"), \
                patch.object(ai_server, "get_contents", return_value=catalog):
            response = self.client.post("/recommend", json={
                "taste": "추천", "liked": "두뇌 예능", "disliked": "공포",
                "contentType": "tv", "preference": "드라마",
            })
        self.assertEqual(response.status_code, 200)
        rows = response.json()["recommendations"]
        self.assertEqual(rows[0]["id"], 11)
        # Broad mentions of competition in unrelated dramas are not enough to
        # fill a specific mind-game request with five works.
        self.assertEqual(len(rows), 1)
        self.assertGreater(rows[0]["match_score"], 0)
        self.assertLessEqual(rows[0]["match_score"], 100)
        self.assertFalse({12, 13, 14, 15, 16, 17, 18, 19}.intersection(
            row["id"] for row in rows
        ))
        self.assertIn("두뇌게임", rows[0]["reason"])

    def test_gemini_cannot_return_weak_generic_matches_for_specific_taste(self):
        catalog = [
            {"id": 1, "type": "tv", "title": "선호 서바이벌", "genre_ids": [10764],
             "overview": "두뇌게임 전략 심리전 경쟁 서바이벌"},
            {"id": 2, "type": "tv", "title": "관련 게임", "genre_ids": [10764],
             "overview": "참가자들이 두뇌게임과 전략, 심리전으로 경쟁한다"},
            {"id": 3, "type": "tv", "title": "약한 형사 후보", "genre_ids": [18],
             "overview": "형사가 조직 범죄와 경쟁을 다루는 드라마"},
            {"id": 4, "type": "tv", "title": "공포 후보", "genre_ids": [27],
             "overview": "서바이벌 참가자들이 괴물과 싸운다"},
        ]
        model_result = SimpleNamespace(text=json.dumps({"recommendations": [
            {"id": 3, "type": "tv", "match_score": 99},
            {"id": 4, "type": "tv", "match_score": 100},
            {"id": 2, "type": "tv", "match_score": 50},
        ]}))
        with patch.object(ai_server, "ai_mode", "gemini"), \
                patch.object(ai_server, "get_contents", return_value=catalog), \
                patch.object(ai_server, "generate_with_retry", return_value=model_result) as gemini:
            response = self.client.post("/recommend", json={
                "taste": "추천", "liked": "선호 서바이벌", "disliked": "공포",
                "contentType": "tv", "preference": "드라마",
            })

        self.assertEqual(response.status_code, 200, response.text)
        prompt = gemini.call_args.args[0]
        self.assertNotIn('"id": 3', prompt)
        self.assertNotIn('"id": 4', prompt)
        self.assertEqual([row["id"] for row in response.json()["recommendations"]], [2])

    def test_brain_game_liked_work_features_drive_relevance_and_horror_exclusion(self):
        catalog = [
            {"id": 1, "type": "tv", "title": "데블스 플랜", "genre_ids": [10764],
             "overview": "최고의 두뇌 플레이어 자리를 두고 참가자들이 일주일간 대결을 펼치는 브레인 서바이벌"},
            {"id": 2, "type": "tv", "title": "전략 대결", "genre_ids": [10764],
             "overview": "참가자들이 두뇌 플레이와 전략을 사용해 경쟁하는 서바이벌"},
            {"id": 3, "type": "tv", "title": "두뇌 경쟁", "genre_ids": [10764],
             "overview": "참가자들이 대결에서 우승을 겨룬다"},
            {"id": 7, "type": "tv", "title": "두뇌 퍼즐", "genre_ids": [18],
             "overview": "참가자들이 두뇌 게임의 퍼즐을 푼다"},
            {"id": 4, "type": "tv", "title": "로맨스 드라마", "genre_ids": [18],
             "overview": "연인들의 사랑과 일상을 그린 이야기"},
            {"id": 5, "type": "tv", "title": "좀비 감염", "genre_ids": [10759, 18],
             "overview": "감염된 좀비와 생존자들의 이야기"},
            {"id": 6, "type": "tv", "title": "괴물의 밤", "genre_ids": [10765],
             "overview": "정체를 알 수 없는 괴물들이 나타난다"},
        ]
        request = {"taste": "추천", "liked": "데블스 플랜", "disliked": "공포",
                   "contentType": "tv", "preference": "전체"}

        with patch.object(ai_server, "ai_mode", "local"), \
                patch.object(ai_server, "get_contents", return_value=catalog), \
                patch.object(ai_server, "generate_with_retry") as gemini:
            result = self.client.post("/recommend", json=request).json()["recommendations"]
        self.assertEqual([row["id"] for row in result], [2, 7, 3])
        scores = [row["match_score"] for row in result]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(0 <= score <= 100 for score in scores))
        result_by_id = {row["id"]: row for row in result}
        self.assertIn("두뇌게임", result_by_id[2]["reason"])
        self.assertIn("두뇌게임", result_by_id[7]["reason"])
        self.assertFalse({4, 5, 6}.intersection(row["id"] for row in result))
        gemini.assert_not_called()

    def test_gemini_scores_are_replaced_with_absolute_verified_fit_and_sorted(self):
        catalog = [
            {"id": 1, "type": "tv", "title": "데블스 플랜", "genre_ids": [10764],
             "overview": "두뇌 플레이어들이 대결하는 브레인 서바이벌"},
            {"id": 2, "type": "tv", "title": "전략 대결", "genre_ids": [10764],
             "overview": "참가자들이 두뇌 플레이와 전략을 사용해 경쟁하는 서바이벌"},
            {"id": 3, "type": "tv", "title": "경쟁", "genre_ids": [10764],
             "overview": "참가자들이 대결에서 우승을 겨룬다"},
            {"id": 7, "type": "tv", "title": "두뇌 퍼즐", "genre_ids": [18],
             "overview": "참가자들이 두뇌 게임의 퍼즐을 푼다"},
            {"id": 4, "type": "tv", "title": "공포 후보", "genre_ids": [18],
             "overview": "좀비 감염 재난"},
        ]
        model_result = SimpleNamespace(text=json.dumps({"recommendations": [
            {"id": 3, "type": "tv", "match_score": 94, "reason": "모델이 만든 설명"},
            {"id": 7, "type": "tv", "match_score": 94, "reason": "모델이 만든 설명"},
            {"id": 2, "type": "tv", "match_score": 94, "reason": "모델이 만든 설명"},
            {"id": 4, "type": "tv", "match_score": 100, "reason": "공포"},
        ]}))
        with patch.object(ai_server, "ai_mode", "gemini"), \
                patch.object(ai_server, "get_contents", return_value=catalog), \
                patch.object(ai_server, "generate_with_retry", return_value=model_result) as gemini:
            result = self.client.post("/recommend", json={
                "taste": "추천", "liked": "데블스 플랜", "disliked": "공포",
                "contentType": "tv", "preference": "전체",
            }).json()["recommendations"]
        self.assertEqual([row["id"] for row in result], [2, 7, 3])
        scores = [row["match_score"] for row in result]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(0 <= score <= 100 for score in scores))
        self.assertTrue(all("모델이 만든 설명" not in row["reason"] for row in result))
        prompt = gemini.call_args.args[0]
        self.assertIn('"id": 2', prompt)
        self.assertNotIn('"id": 4', prompt)

    def test_five_distinct_survey_intents_change_ranked_recommendations(self):
        catalog = [
            {"id": 1, "type": "movie", "title": "로맨스 작품", "genre_ids": [10749], "overview": "로맨스와 연애 이야기"},
            {"id": 2, "type": "movie", "title": "코미디 작품", "genre_ids": [35], "overview": "유쾌한 코미디와 웃음"},
            {"id": 3, "type": "movie", "title": "추리 작품", "genre_ids": [9648], "overview": "단서와 미스터리를 추리한다"},
            {"id": 4, "type": "movie", "title": "액션 작품", "genre_ids": [28], "overview": "전투와 액션을 다룬다"},
            {"id": 5, "type": "movie", "title": "공포 제외", "genre_ids": [27], "overview": "공포 귀신 괴담"},
        ]
        surveys = [
            ("로맨스", 1), ("코미디", 2), ("미스터리", 3), ("액션", 4),
        ]
        first_ids = []
        with patch.object(ai_server, "ai_mode", "local"), \
                patch.object(ai_server, "get_contents", return_value=catalog):
            for liked, expected_id in surveys:
                response = self.client.post("/recommend", json={
                    "taste": "추천", "liked": liked, "disliked": "공포",
                    "contentType": "movie", "preference": "영화",
                })
                self.assertEqual(response.status_code, 200)
                rows = response.json()["recommendations"]
                self.assertTrue(rows)
                self.assertEqual(rows[0]["id"], expected_id)
                self.assertNotIn(5, [row["id"] for row in rows])
                first_ids.append(rows[0]["id"])
        self.assertEqual(len(set(first_ids)), len(surveys))

    def test_variety_tv_action_adventure_metadata_does_not_match_action_preference(self):
        catalog = [
            {"id": 1, "type": "tv", "title": "버라이어티", "genre_ids": [18, 35, 10764, 10759],
             "overview": "출연자들이 게임을 하며 여행하는 예능"},
            {"id": 2, "type": "tv", "title": "액션 드라마", "genre_ids": [10759, 18],
             "overview": "범죄를 쫓는 액션 수사극"},
        ]
        with patch.object(ai_server, "ai_mode", "local"), \
                patch.object(ai_server, "get_contents", return_value=catalog):
            response = self.client.post("/recommend", json={
                "taste": "추천", "liked": "액션", "disliked": "공포",
                "contentType": "tv", "preference": "전체",
                "preferredGenres": [10759],
            })
        self.assertEqual(response.status_code, 200)
        rows = response.json()["recommendations"]
        self.assertEqual([row["id"] for row in rows], [2])

    def test_unresolved_or_ambiguous_liked_title_does_not_fill_with_unrelated_work(self):
        catalog = [
            {"id": 1, "type": "tv", "title": "동명이작", "genre_ids": [10764],
             "overview": "두뇌 게임과 전략 대결"},
            {"id": 2, "type": "tv", "title": "동명이작", "genre_ids": [18],
             "overview": "가족의 성장 이야기"},
            {"id": 3, "type": "tv", "title": "무관한 작품", "genre_ids": [10764],
             "overview": "요리와 여행"},
        ]
        with patch.object(ai_server, "ai_mode", "local"), \
                patch.object(ai_server, "get_contents", return_value=catalog), \
                patch.object(ai_server, "generate_with_retry") as gemini:
            response = self.client.post("/recommend", json={
                "taste": "추천", "liked": "동명이작", "contentType": "tv",
                "preference": "전체",
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommendations"], [])
        gemini.assert_not_called()

    def test_transient_gemini_503_uses_ranked_catalog_fallback_for_movie_and_tv(self):
        for kind, preference, preferred_genres, start in (
            ("movie", "영화", [10749], 100),
            ("tv", "드라마", [10749], 200),
        ):
            with self.subTest(kind=kind):
                catalog = []
                for index in range(7):
                    relevant = index < 4
                    catalog.append({
                        "id": start + index,
                        "type": kind,
                        "title": f"{kind}-{index}",
                        "overview": "로맨스 연애 사랑" if relevant else "코미디 개그 웃음",
                        "genre_ids": [10749] if relevant else [35],
                        "rating": 9.0 - index / 10,
                        "poster_url": f"https://images.example/{start + index}.jpg",
                        "ott": ["검증된 OTT"],
                    })
                catalog.append({
                    "id": start + 99, "type": kind, "title": "excluded-horror",
                    "overview": "공포 귀신 괴담", "genre_ids": [27], "rating": 10,
                    "poster_url": "https://images.example/horror.jpg", "ott": [],
                })
                unavailable = RuntimeError("private provider detail")
                unavailable.code = 503
                with patch.object(ai_server, "ai_mode", "gemini"), \
                        patch.object(ai_server, "get_contents", return_value=catalog), \
                        patch.object(ai_server, "generate_with_retry", side_effect=unavailable) as gemini:
                    response = self.client.post("/recommend", json={
                        "taste": "로맨스 추천", "liked": "로맨스", "disliked": "공포",
                        "preference": preference, "contentType": kind,
                        "preferredGenres": preferred_genres,
                    })
                self.assertEqual(response.status_code, 200)
                result = response.json()
                rows = result["recommendations"]
                self.assertEqual(result["recommendation_source"], "local_fallback")
                self.assertIn("Gemini 추천이 일시적으로 중단", result["taste_analysis"])
                self.assertEqual(len(rows), 4)
                self.assertEqual(len({row["id"] for row in rows}), 4)
                self.assertTrue(all(row["type"] == kind and row["poster_url"]
                                    and row["genre_ids"] and row["reason"] for row in rows))
                self.assertNotIn(start + 99, [row["id"] for row in rows])
                self.assertTrue(all(row["id"] < start + 4 for row in rows[:4]))
                scores = [row["match_score"] for row in rows]
                self.assertEqual(scores, sorted(scores, reverse=True))
                gemini.assert_called_once()

    def test_genai_transport_connect_error_uses_tv_catalog_fallback(self):
        # Google GenAI may wrap httpx transport errors in a different
        # ConnectError class, so exercise the exact exception shape from logs.
        transport_error = type("ConnectError", (Exception,), {})("upstream unavailable")
        catalog = [
            {"id": index, "type": "tv", "title": f"strategy-{index}",
             "overview": "strategy competition", "genre_ids": [18],
             "rating": 8.0, "poster_url": f"https://img/{index}.jpg"}
            for index in range(1, 7)
        ]
        with patch.object(ai_server, "ai_mode", "gemini"), \
                patch.object(ai_server, "get_contents", return_value=catalog), \
                patch.object(ai_server, "generate_with_retry", side_effect=transport_error) as gemini:
            response = self.client.post("/recommend", json={
                "taste": "\uCD94\uCC9C", "liked": "\uB370\uBE14\uC2A4 \uD50C\uB79C",
                "disliked": "\uACF5\uD3EC", "preference": "\uB4DC\uB77C\uB9C8",
                "contentType": "tv", "preferredGenres": [18],
            })

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["recommendation_source"], "local_fallback")
        self.assertEqual(len(payload["recommendations"]), 5)
        self.assertEqual([row["match_score"] for row in payload["recommendations"]],
                         sorted((row["match_score"] for row in payload["recommendations"]),
                                reverse=True))
        self.assertTrue(all(row["type"] == "tv" for row in payload["recommendations"]))
        gemini.assert_called_once()

    def test_short_gemini_response_is_supplemented_and_sorted_by_display_score(self):
        catalog = [
            {"id": 316702, "type": "tv", "title": "파이널 테이블", "overview": "요리 경쟁",
             "genre_ids": [18], "poster_url": "https://images.example/final-table.jpg", "rating": 8.1},
            {"id": 197067, "type": "tv", "title": "이상한 변호사 우영우", "overview": "법정 드라마",
             "genre_ids": [18], "poster_url": "https://images.example/woo.jpg", "rating": 8.5},
            *[{"id": 300 + index, "type": "tv", "title": f"보충 작품 {index}",
               "overview": "법정 드라마", "genre_ids": [18], "poster_url": f"https://images.example/{index}.jpg",
               "rating": 7.0 + index / 10} for index in range(1, 7)],
        ]
        gemini = SimpleNamespace(text=json.dumps({"taste_analysis": "verified analysis", "recommendations": [
            {"id": 316702, "type": "tv", "match_score": 85, "reason": "verified reason"},
            {"id": 197067, "type": "tv", "match_score": 90, "reason": "verified reason"},
        ]}))
        with patch.object(ai_server, "ai_mode", "gemini"), \
                patch.object(ai_server, "get_contents", return_value=catalog), \
                patch.object(ai_server, "generate_with_retry", return_value=gemini):
            response = self.client.post("/recommend", json={
                "taste": "드라마 추천", "liked": "드라마", "contentType": "tv",
                "preference": "드라마", "preferredGenres": [18],
                "recentHistory": ["tv:197067"],
            })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        rows = payload["recommendations"]
        self.assertEqual(payload["recommendation_source"], "gemini_supplemented")
        self.assertEqual(payload["gemini_recommendation_count"], 2, payload)
        self.assertEqual(len(rows), 5)
        self.assertEqual([row["match_score"] for row in rows],
                         sorted((row["match_score"] for row in rows), reverse=True))
        self.assertTrue(all(row["match_score"] == 100 for row in rows))
        gemini_rows = [row for row in rows if "recommendation_source" not in row]
        self.assertEqual({row["id"] for row in gemini_rows}, {197067, 316702})
        for row in gemini_rows:
            original = next(item for item in catalog if item["id"] == row["id"])
            self.assertEqual(row["poster_url"], original["poster_url"])
            self.assertEqual(row["genre_ids"], original["genre_ids"])
        self.assertEqual(sum(row.get("recommendation_source") == "local_supplement" for row in rows), 3)

    def test_disabled_gemini_and_unavailable_catalog(self):
        with patch.object(ai_server, "ai_mode", "disabled"), patch.object(
            ai_server, "get_contents", side_effect=ai_server.MySqlError("private diagnostic")
        ) as get_contents:
            response = self.client.post("/recommend", json={"taste": "추천", "contentType": "movie"})
            self.assertEqual(response.status_code, 503)
            get_contents.assert_not_called()

            response = self.client.post("/recommend", json={"taste": "추천", "contentType": "webtoon"})
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("private diagnostic", response.text)
            get_contents.assert_called_once()

    def setUp(self):
        environment = self.enterContext(patch.dict("os.environ", {}))
        environment.pop("WEBTOON_RECOMMENDATION_PROVIDERS", None)
        self.catalog = [
            content(1, "movie", "첫 작품", [35]),
            content(1, "tv", "다른 유형", [35]),
            content(2, "movie", "둘째 작품", [35]),
            content(3, "movie", "셋째 작품", [27]),
            content(4, "movie", "넷째 작품", [18]),
        ]
        self.client = TestClient(ai_server.app)

    def recommend(self, candidates, **fields):
        response = SimpleNamespace(text=json.dumps({
            "taste_analysis": "테스트",
            "recommendations": [
                {"type": kind, "id": item_id, "match_score": 80}
                for kind, item_id in candidates
            ]
        }))
        with patch.object(ai_server, "get_contents", return_value=self.catalog):
            with patch.object(ai_server, "generate_with_retry", return_value=response) as gemini:
                result = self.client.post("/recommend", json={"taste": "추천", **fields})
        self.assertEqual(result.status_code, 200)
        return result.json()["recommendations"], gemini.call_args.args[0]

    def test_new_member_and_candidate_validation(self):
        recommendations, prompt = self.recommend([
            ("movie", 2), ("movie", 2), ("movie", 99)
        ])
        self.assertEqual([item["id"] for item in recommendations], [2])
        self.assertIn('"favorite_titles": []', prompt)

    def test_movie_gemini_prompt_uses_relevant_bounded_candidates(self):
        rows = [
            {**content(1, "movie", "Excluded marker", [35]),
             "overview": "contains blocked-marker"},
        ]
        # Put relevant candidates after more than 50 irrelevant catalog rows so
        # a naive first-N slice would omit them entirely.
        rows.extend(content(100 + index, "movie", f"Irrelevant {index:02d}", [27])
                    for index in range(55))
        rows.extend(content(200 + index, "movie", f"Preferred {index:02d}", [35])
                    for index in range(8))
        selected = rows[-1]
        response = SimpleNamespace(text=json.dumps({
            "taste_analysis": "verified candidate",
            "recommendations": [
                {"type": "movie", "id": selected["id"], "match_score": 80},
                {"type": "movie", "id": 154, "match_score": 80},
            ],
        }))
        with patch.object(ai_server, "get_contents", return_value=rows), \
                patch.object(ai_server, "generate_with_retry", return_value=response) as gemini:
            result = self.client.post("/recommend", json={
                "taste": "genre shortlist", "contentType": "movie",
                "disliked": "blocked-marker", "preferredGenres": [35],
            })

        self.assertEqual(result.status_code, 200)
        prompt = gemini.call_args.args[0]
        candidate_start = prompt.rfind("\n[") + 1
        candidate_json = prompt[candidate_start:].split("\n\n", 1)[0]
        prompted = json.loads(candidate_json)
        self.assertEqual(len(prompted), 8)
        prompted_ids = {item["id"] for item in prompted}
        self.assertNotIn(1, prompted_ids)
        self.assertTrue({item["id"] for item in rows[-8:]}.issubset(prompted_ids))
        self.assertEqual([item["id"] for item in result.json()["recommendations"]],
                         [200, 201, 202, 203, selected["id"]])

    def test_tv_gemini_prompt_uses_relevant_bounded_candidates(self):
        rows = [
            {**content(1, "tv", "Excluded marker", [35]),
             "overview": "contains blocked-marker"},
        ]
        rows.extend(content(100 + index, "tv", f"Irrelevant {index:02d}", [27])
                    for index in range(55))
        rows.extend(content(200 + index, "tv", f"Preferred {index:02d}", [35])
                    for index in range(8))
        selected = rows[-1]
        response = SimpleNamespace(text=json.dumps({
            "taste_analysis": "verified candidate",
            "recommendations": [
                {"type": "tv", "id": selected["id"], "match_score": 80},
                {"type": "tv", "id": 154, "match_score": 80},
            ],
        }))
        with patch.object(ai_server, "get_contents", return_value=rows), \
                patch.object(ai_server, "generate_with_retry", return_value=response) as gemini:
            result = self.client.post("/recommend", json={
                "taste": "genre shortlist", "contentType": "tv",
                "disliked": "blocked-marker", "preferredGenres": [35],
            })

        self.assertEqual(result.status_code, 200)
        prompt = gemini.call_args.args[0]
        candidate_start = prompt.rfind("\n[") + 1
        prompted = json.loads(prompt[candidate_start:].split("\n\n", 1)[0])
        self.assertEqual(len(prompted), 8)
        prompted_ids = {item["id"] for item in prompted}
        self.assertNotIn(1, prompted_ids)
        self.assertTrue({item["id"] for item in rows[-8:]}.issubset(prompted_ids))
        self.assertEqual([item["id"] for item in result.json()["recommendations"]],
                         [200, 201, 202, 203, selected["id"]])

    def test_malformed_catalog_genres_do_not_break_recommendations(self):
        self.catalog = [
            content(1, "movie", "스칼라 장르", 18),
            content(2, "movie", "배열 속 잘못된 장르", [[], {"id": 18}, 35]),
            content(3, "movie", "정상 장르", [18]),
        ]
        recommendations, prompt = self.recommend(
            [("movie", 1), ("movie", 2), ("movie", 3)],
            contentType="movie",
            liked="웃기는 작품",
            preferredGenres=[35],
        )
        self.assertEqual({item["id"] for item in recommendations}, {2})
        options = json.loads(prompt.split("\n콘텐츠 데이터:\n", 1)[1].splitlines()[0])
        by_id = {item["id"]: item for item in options}
        self.assertEqual(set(by_id), {2})
        self.assertEqual(by_id[2]["personalization_score"], 5)

    def test_ott_recommendations_are_limited_to_five_for_each_selection(self):
        self.catalog = [
            content(start + offset, kind, f"Fixture {start + offset}", [genre])
            for start, kind, genre in [(10, "movie", 18), (20, "tv", 18), (30, "tv", 10764)]
            for offset in range(6)
        ]
        candidates = [(row["type"], row["id"]) for row in self.catalog]
        for start, kind, preference in [(10, "movie", "영화"), (20, "tv", "드라마"), (30, "tv", "예능")]:
            with self.subTest(preference=preference):
                recommendations, _ = self.recommend(candidates, contentType=kind, preference=preference)
                self.assertEqual(len(recommendations), 5)
                self.assertTrue(all(item["type"] == kind and start <= item["id"] < start + 6
                                    for item in recommendations))

    def test_current_filters_take_priority_over_profile(self):
        recommendations, _ = self.recommend(
            [("movie", 3), ("tv", 1), ("movie", 1), ("movie", 2)],
            liked="첫 작품", disliked="공포", preference="영화",
            favorites=[{"id": 3, "type": "movie", "title": "셋째 작품"}],
            preferredGenres=[27]
        )
        self.assertEqual([item["id"] for item in recommendations], [2])

    def test_genre_and_favorite_scoring_and_recent_type_key(self):
        recommendations, prompt = self.recommend(
            [("movie", 1), ("movie", 4), ("movie", 2), ("tv", 1)],
            favorites=[{"id": 1, "type": "movie", "title": "첫 작품"}],
            preferredGenres=[35], recentHistory=["movie:1"]
        )
        self.assertEqual({(item["type"], item["id"]) for item in recommendations},
                         {("movie", 2), ("tv", 1), ("movie", 1)})
        self.assertIn('"favorite_tags": ["코미디"]', prompt)
        self.assertIn('"personalization_score": 13', prompt)
        self.assertEqual(prompt.count('"recently_recommended": true'), 1)

    def test_recent_work_remains_eligible(self):
        recommendations, _ = self.recommend([("movie", 1)], recentHistory=["movie:1"])
        self.assertEqual([item["id"] for item in recommendations], [1])

    def test_profile_is_scoped_to_each_request(self):
        _, first_prompt = self.recommend(
            [("movie", 2)], favorites=[{"id": 1, "type": "movie", "title": "회원 A의 찜"}],
            preferredGenres=[35], recentHistory=["movie:2"]
        )
        _, next_prompt = self.recommend(
            [("movie", 2)], favorites=[{"id": 4, "type": "movie", "title": "회원 B의 찜"}],
            preferredGenres=[]
        )
        self.assertIn("회원 A의 찜", first_prompt)
        self.assertIn('"recently_recommended": true', first_prompt)
        self.assertIn("회원 B의 찜", next_prompt)
        self.assertNotIn("회원 A의 찜", next_prompt)
        self.assertNotIn('"recently_recommended": true', next_prompt)

    def test_webtoon_uses_structured_profile_and_returns_fit_reasons(self):
        synthetic = {
            **content(700001, "webtoon", "합성 테스트 작품", [9001]),
            "overview": "테스트용 성장 서사",
            "genre_ids": [9001],
            "rating": None,
            "taste_features": {
                "genres": ["fantasy"],
                "story": ["growth"],
                "mood": ["warm"],
                "pacing": "fast",
            },
            "service_platform": "synthetic-platform",
            "authors": ["synthetic-author"],
        }
        with patch.object(ai_server, "get_contents", return_value=self.catalog + [synthetic]):
            with patch.object(ai_server, "generate_with_retry") as gemini:
                response = self.client.post("/recommend", json={
                    "taste": "설문 취향",
                    "contentType": "webtoon",
                    "tasteProfile": {"dimensions": {
                        "genres": {"fantasy": 1.0}, "story": {"growth": 1.0},
                        "mood": {}, "pacing": {},
                    }},
                })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["profile_summary"]["genres"]["fantasy"], 1.0)
        self.assertIn("선호 장르: fantasy", payload["taste_analysis"])
        self.assertEqual(len(payload["recommendations"]), 1)
        recommendation = payload["recommendations"][0]
        self.assertEqual((recommendation["type"], recommendation["id"]), ("webtoon", 700001))
        self.assertGreater(recommendation["personal_fit_score"], 50)
        self.assertIn("fit_reasons", recommendation)
        self.assertTrue(recommendation["reason"])
        gemini.assert_not_called()

    def test_liked_webtoon_seeds_verified_features_and_excludes_horror_or_unknown_genres(self):
        def real_work(work_id, title, genres, official_tags=()):
            return {
                **content(work_id, "webtoon", title, []),
                "source_provider": "naver_webtoon",
                "external_id": str(work_id),
                "official_url": f"https://comic.naver.com/webtoon/list?titleId={work_id}",
                "genre_tags": list(genres),
                "official_tags": list(official_tags),
                "taste_features": {"genres": list(genres), "official_tags": list(official_tags)},
            }

        catalog = [
            real_work(100, "화산귀환", ["무협/사극"], ["회귀", "동양풍판타지"]),
            real_work(101, "무협 후보", ["무협/사극"], ["회귀", "동양풍판타지"]),
            real_work(102, "회귀 후보", ["무협/사극"], ["회귀"]),
            real_work(103, "공포 후보", ["스릴러/공포"], ["회귀"]),
            real_work(104, "장르 미확인 후보", [], ["회귀"]),
            real_work(105, "일반 판타지 후보", ["판타지"], ["모험"]),
        ]
        with patch.object(ai_server, "get_contents", return_value=catalog), \
                patch.object(ai_server, "ai_mode", "disabled"):
            response = self.client.post("/recommend", json={
                "taste": "선호작 기반 웹툰 추천",
                "liked": "화산귀환",
                "disliked": "공포",
                "contentType": "webtoon",
                "tasteProfile": {"dimensions": {"genres": {}, "official_tags": {}}},
            })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        recommendations = payload["recommendations"]
        self.assertEqual([item["id"] for item in recommendations], [101, 102])
        self.assertTrue(all(item["personal_fit_score"] > 50 for item in recommendations))
        self.assertTrue(all(item["fit_reasons"] for item in recommendations))
        self.assertTrue(all("공식 태그" in item["reason"] or "장르" in item["reason"]
                            for item in recommendations))
        self.assertNotIn(103, [item["id"] for item in recommendations])
        self.assertNotIn(104, [item["id"] for item in recommendations])
        self.assertNotIn(105, [item["id"] for item in recommendations])
        self.assertIn(1.0, payload["profile_summary"]["genres"].values())
        self.assertIn(-1.0, payload["profile_summary"]["genres"].values())

    def test_webtoon_positive_story_match_can_use_verified_official_tags(self):
        verified = {
            **content(901, "webtoon", "검증된 회귀 태그 작품", []),
            "source_provider": "naver_webtoon", "external_id": "901",
            "official_url": "https://comic.naver.com/webtoon/list?titleId=901",
            "taste_features": {"genres": [], "story": [], "mood": [], "pacing": "",
                               "official_tags": ["회귀"]},
        }
        with patch.object(ai_server, "get_contents", return_value=[verified]), \
                patch.object(ai_server, "ai_mode", "disabled"):
            response = self.client.post("/recommend", json={
                "taste": "스토리 선호 추천", "contentType": "webtoon",
                "tasteProfile": {"dimensions": {"story": {"회귀": 1.0}}},
            })
        self.assertEqual(response.status_code, 200)
        recommendations = response.json()["recommendations"]
        self.assertEqual([item["id"] for item in recommendations], [901])
        self.assertGreater(recommendations[0]["personal_fit_score"], 50)
        self.assertEqual(recommendations[0]["fit_reasons"], [
            {"dimension": "story", "feature": "회귀", "signal": "match"}
        ])

    def test_webtoon_positive_preference_never_fills_top_five_with_unmatched_neutral_rows(self):
        catalog = [
            {
                **content(index, "webtoon", f"중립 작품 {index}", []),
                "taste_features": {"genres": ["액션"], "story": [], "mood": [], "pacing": "",
                                   "official_tags": ["전투"]},
            }
            for index in range(910, 916)
        ]
        with patch.object(ai_server, "get_contents", return_value=catalog), \
                patch.object(ai_server, "ai_mode", "disabled"):
            response = self.client.post("/recommend", json={
                "taste": "스토리 선호 추천", "contentType": "webtoon",
                "tasteProfile": {"dimensions": {"story": {"회귀": 1.0}}},
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommendations"], [])
        self.assertIn("조건에 맞는 새 웹툰", response.json()["taste_analysis"])

    def test_same_title_from_multiple_catalog_rows_is_not_merged_into_one_seed(self):
        title = "화산귀환"
        rows = [
            {**content(100, "webtoon", title, []), "source_provider": "naver_webtoon",
             "external_id": "769209", "taste_features": {"genres": ["무협/사극"]}},
            {**content(101, "webtoon", title, []), "source_provider": "kmas",
             "external_id": "different-edition", "taste_features": {"genres": ["로맨스"]}},
        ]
        request = SimpleNamespace(tasteProfile={"dimensions": {}})
        profile = ai_server.build_webtoon_request_profile(
            request, rows, {ai_server.normalize(title)}, ""
        )
        self.assertEqual(profile["dimensions"]["genres"], {})

    def test_webtoon_provider_allowlist_excludes_test_catalog_from_real_results(self):
        real = {
            "id": 990000000011, "type": "webtoon", "title": "화산귀환",
            "genre_ids": [], "source_provider": "naver_webtoon", "external_id": "769209",
            "official_url": "https://comic.naver.com/webtoon/list?titleId=769209",
            "cover_source_url": "https://shared-comic.pstatic.net/verified-cover-url.jpg",
            "authors": ["ARCHE", "LICO", "원작: 비가"],
            "genre_tags": ["무협", "사극"], "taste_features": {"genres": ["무협", "사극"]},
            "poster_url": "/posters/webtoon-cover-unavailable.svg",
        }
        fictional = {
            **content(990000000001, "webtoon", "[가상 웹툰] 테스트", []),
            "source_provider": "contentlab_demo_fictional",
            "taste_features": {"genres": ["무협"]},
        }
        with patch.dict("os.environ", {"WEBTOON_RECOMMENDATION_PROVIDERS": "naver_webtoon"}), \
                patch.object(ai_server, "get_contents", return_value=[fictional, real]), \
                patch.object(ai_server, "generate_with_retry") as gemini:
            response = self.client.post("/recommend", json={
                "taste": "무협", "contentType": "webtoon",
                "tasteProfile": {"dimensions": {"genres": {"무협": 1.0}}},
            })
        self.assertEqual(response.status_code, 200)
        recommendations = response.json()["recommendations"]
        self.assertEqual([item["title"] for item in recommendations], ["화산귀환"])
        self.assertEqual(recommendations[0]["source_provider"], "naver_webtoon")
        self.assertEqual(recommendations[0]["external_id"], "769209")
        self.assertEqual(recommendations[0]["official_url"], real["official_url"])
        self.assertNotIn("cover_source_url", recommendations[0], "Unlicensed cover URLs must not be sent to the browser")
        self.assertEqual(recommendations[0]["authors"], real["authors"])
        self.assertEqual(recommendations[0]["genre_tags"], real["genre_tags"])
        gemini.assert_not_called()

    def test_kmas_provider_catalog_uses_existing_personalized_top_five_path(self):
        catalog = [
            {**content(8_000_000_000_000_000_000 + item_id, "webtoon", f"KMAS 승인 전 모의작 {item_id}", []),
             "source_provider": "kmas", "external_id": f"mock-{item_id}",
             "poster_url": "/posters/webtoon-cover-unavailable.svg",
             "cover_source_url": "https://api.example.invalid/rights-pending.jpg",
             "genre_tags": ["판타지"],
             "taste_features": {"genres": ["판타지"], "story": [], "mood": [], "pacing": ""}}
            for item_id in range(30)
        ]
        with patch.dict("os.environ", {"WEBTOON_RECOMMENDATION_PROVIDERS": "kmas"}), \
                patch.object(ai_server, "get_contents", return_value=catalog), \
                patch.object(ai_server, "generate_with_retry") as gemini:
            response = self.client.post("/recommend", json={
                "taste": "판타지 선호", "contentType": "webtoon",
                "tasteProfile": {"dimensions": {"genres": {"판타지": 1.0}}},
            })
        self.assertEqual(response.status_code, 200)
        results = response.json()["recommendations"]
        self.assertEqual(len(results), 5)
        self.assertTrue(all(item["source_provider"] == "kmas" for item in results))
        self.assertTrue(all(item["personal_fit_score"] == 100 for item in results))
        self.assertTrue(all(item["poster_url"] == "/posters/webtoon-cover-unavailable.svg" for item in results))
        self.assertTrue(all("cover_source_url" not in item for item in results))
        gemini.assert_not_called()

    def test_webtoon_prefers_new_works_and_excludes_known_or_incompatible_candidates(self):
        def webtoon(content_id, genre="fantasy", **fields):
            return {**content(content_id, "webtoon", f"작품 {content_id}", []),
                    "taste_features": {"genres": [genre]}, **fields}

        self.catalog.extend([
            webtoon(1), webtoon(1), webtoon(2), webtoon(3), webtoon(4, "dark"),
            webtoon(5, overview="금지소재"), webtoon(6, is_excluded=True),
            webtoon(7, taste_features="invalid"), webtoon(8, "unknown"),
        ])
        with patch.object(ai_server, "get_contents", return_value=self.catalog):
            with patch.object(ai_server, "generate_with_retry") as gemini:
                response = self.client.post("/recommend", json={
                    "taste": "추천", "contentType": "webtoon", "disliked": "금지소재",
                    "favorites": [{"id": 1, "type": "movie", "title": "첫 작품"},
                                  {"id": 2, "type": "webtoon", "title": "작품 2"}],
                    "recentHistory": ["webtoon:3"],
                    "tasteProfile": {"dimensions": {"genres": {"fantasy": 1, "dark": -1}}},
                })
        self.assertEqual(response.status_code, 200)
        recommendations = response.json()["recommendations"]
        self.assertEqual([item["id"] for item in recommendations], [1, 3])
        self.assertIn("장르 ‘fantasy’", recommendations[0]["reason"])
        self.assertIn("선호와 일치", recommendations[1]["reason"])
        gemini.assert_not_called()

    def test_webtoon_explains_starting_without_a_saved_survey(self):
        synthetic = {**content(700001, "webtoon", "합성 테스트 작품", []),
                     "taste_features": {"genres": ["fantasy"]}}
        for liked, expected_basis in [
            ("", "작품 정보를 바탕으로"),
            ("판타지", "이번에 입력한 취향과 작품 정보를 바탕으로"),
        ]:
            with self.subTest(liked=liked), patch.object(ai_server, "get_contents", return_value=[synthetic]):
                response = self.client.post("/recommend", json={
                    "taste": "웹툰 추천",
                    "contentType": "webtoon",
                    "liked": liked,
                })
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["profile_summary"], {})
                self.assertEqual(len(payload["recommendations"]), 1)
                self.assertTrue(payload["taste_analysis"].startswith(expected_basis))
                self.assertIn("웹툰 취향 설문과 작품 평가", payload["taste_analysis"])

    def test_webtoon_default_catalog_deduplicates_identity_and_changes_with_survey(self):
        rows = [
            {**content(1, "webtoon", "테스트 1", []), "taste_features": {"genres": ["fantasy"]}},
            {**content(2, "webtoon", "테스트 2", []), "taste_features": {"genres": ["romance"]}},
            {**content(3, "webtoon", "테스트 3", []), "taste_features": {"genres": ["fantasy"]},
             "external_id": "fixture-1"},
            {**content(4, "webtoon", "가상 시연", []), "taste_features": {"genres": ["fantasy", "romance"]},
             "source_provider": "contentlab_demo_fictional"},
            {**content(5, "webtoon", "외부 ID 없음", []), "taste_features": {"genres": ["fantasy"]},
             "external_id": None},
        ]
        with patch.object(ai_server, "get_contents", return_value=rows):
            for liked, disliked, expected in [("fantasy", "romance", 1), ("romance", "fantasy", 2)]:
                with self.subTest(liked=liked):
                    response = self.client.post("/recommend", json={
                        "taste": "추천", "contentType": "webtoon",
                        "tasteProfile": {"dimensions": {"genres": {liked: 1, disliked: -1}}},
                    })
                    self.assertEqual(response.status_code, 200)
                    results = response.json()["recommendations"]
                    self.assertEqual([item["id"] for item in results], [expected])
                    self.assertEqual(results[0]["match_score"], 75)
                    self.assertIn(liked, results[0]["reason"])

    def test_webtoon_returns_five_ranked_results_without_ott_taste_signals(self):
        webtoons = [
            {**content(item_id, "webtoon", f"합성 작품 {item_id}", []),
             "taste_features": {"genres": ["other" if item_id == 14 else "fantasy"]}}
            for item_id in range(16, 9, -1)
        ]
        webtoons[0]["overview"] = "추리"
        movie = {**content(16, "movie", "선호작", []), "overview": "추리"}
        for signals in (
            {},
            {"liked": "선호작"},
            {"favorites": [{"id": 16, "type": "movie", "title": "선호작"}]},
        ):
            with self.subTest(signals=signals):
                with patch.object(ai_server, "get_contents", return_value=[movie, *webtoons]):
                    with patch.object(ai_server, "generate_with_retry") as gemini:
                        response = self.client.post("/recommend", json={
                            "taste": "추천", "contentType": "webtoon",
                            "recentHistory": ["webtoon:11", "movie:10"],
                            "tasteProfile": {"dimensions": {"genres": {"fantasy": 1}}},
                            **signals,
                        })
                self.assertEqual(response.status_code, 200)
                results = response.json()["recommendations"]
                self.assertEqual([(item["type"], item["id"]) for item in results],
                                 [("webtoon", item_id) for item_id in (10, 12, 13, 15, 16)])
                for item in results:
                    self.assertEqual(item["match_score"], 100)
                    self.assertEqual(item["personal_fit_score"], 100)
                    self.assertIn("장르 ‘fantasy’", item["reason"])
                gemini.assert_not_called()

    def test_ott_prompt_and_result_exclude_webtoon_candidates(self):
        self.catalog.append({
            **content(1, "webtoon", "합성웹툰제목", []),
            "taste_features": {"genres": ["개인화전용장르"]},
        })
        recommendations, prompt = self.recommend(
            [("webtoon", 1), ("movie", 1)],
            favorites=[{"id": 1, "type": "webtoon", "title": "합성웹툰제목"}],
        )
        self.assertEqual([(item["type"], item["id"]) for item in recommendations], [("movie", 1)])
        self.assertNotIn("합성웹툰제목", prompt)
        self.assertNotIn("개인화전용장르", prompt)

    def test_invalid_gemini_envelope_returns_bad_gateway(self):
        for body in ("invalid JSON", "[]", "{}", '{"recommendations": null}',
                     '{"taste_analysis": [], "recommendations": []}'):
            with self.subTest(body=body):
                with patch.object(ai_server, "get_contents", return_value=self.catalog):
                    with patch.object(ai_server, "generate_with_retry",
                                      return_value=SimpleNamespace(text=body)):
                        result = self.client.post("/recommend", json={"taste": "추천"})
                self.assertEqual(result.status_code, 502)
                self.assertEqual(set(result.json()), {"detail"})

    def test_invalid_rows_are_discarded_and_model_fields_are_limited(self):
        payload = {"recommendations": [
            None,
            {"id": 1, "type": "movie", "match_score": 99.5},
            {"id": 1, "type": "movie", "match_score": 101},
            {"id": 1, "type": "movie", "match_score": "90",
             "title": "generated title", "reason": "valid", "private": "unexpected"},
            {"id": 2, "type": "movie", "match_score": 80, "reason": {}},
        ]}
        with patch.object(ai_server, "get_contents", return_value=self.catalog):
            with patch.object(ai_server, "generate_with_retry",
                              return_value=SimpleNamespace(text=json.dumps(payload))):
                result = self.client.post("/recommend", json={"taste": "추천"})
        self.assertEqual(result.status_code, 200)
        rows = result.json()["recommendations"]
        by_id = {item["id"]: item for item in rows}
        self.assertEqual(set(by_id), {1, 2})
        self.assertEqual(by_id[1]["title"], self.catalog[0]["title"])
        self.assertEqual(by_id[1]["match_score"], 0)
        self.assertNotIn("generated title", json.dumps(rows, ensure_ascii=False))
        self.assertNotIn("private", json.dumps(rows, ensure_ascii=False))
        self.assertNotIn('"reason": "valid"', json.dumps(rows, ensure_ascii=False))
        self.assertTrue(all(item["match_score"] == 0 for item in rows))

    def test_gemini_timeout_and_failure_do_not_expose_upstream_errors(self):
        for error, status in ((httpx.ReadTimeout("internal timeout"), 504),
                              (RuntimeError("internal error"), 503)):
            with self.subTest(status=status):
                with patch.object(ai_server, "get_contents", return_value=self.catalog):
                    with patch.object(ai_server, "generate_with_retry", side_effect=error):
                        result = self.client.post("/recommend", json={"taste": "추천"})
                self.assertEqual(result.status_code, status)
                self.assertNotIn(str(error), result.text)

    def test_unknown_gemini_error_does_not_silently_fallback(self):
        with patch.object(ai_server, "get_contents", return_value=self.catalog), \
                patch.object(ai_server, "generate_with_retry",
                             side_effect=RuntimeError("internal implementation failure")):
            response = self.client.post("/recommend", json={
                "taste": "추천", "contentType": "movie", "liked": "첫 작품"
            })
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("internal implementation failure", response.text)

    def test_gemini_retries_only_unavailable_errors(self):
        unavailable = RuntimeError("dependency unavailable")
        unavailable.code = 503
        with patch.object(ai_server.client.models, "generate_content",
                          side_effect=[unavailable, unavailable, "result"]) as model:
            with patch.object(ai_server.time, "sleep") as sleep:
                self.assertEqual(ai_server.generate_with_retry("prompt"), "result")
        self.assertEqual(model.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4])

        with patch.object(ai_server.client.models, "generate_content",
                          side_effect=RuntimeError("unrelated 503 in body")) as model:
            with self.assertRaises(RuntimeError):
                ai_server.generate_with_retry("prompt")
        model.assert_called_once()

    def test_gemini_attempt_limit_can_disable_retries_for_approved_single_call(self):
        unavailable = RuntimeError("temporary unavailable")
        unavailable.code = 503
        with patch.dict("os.environ", {"CONTENTLAB_GEMINI_MAX_ATTEMPTS": "1"}), \
                patch.object(ai_server.client.models, "generate_content",
                             side_effect=unavailable) as model, \
                patch.object(ai_server.time, "sleep") as sleep:
            with self.assertRaises(RuntimeError):
                ai_server.generate_with_retry("prompt")
        model.assert_called_once()
        sleep.assert_not_called()

    def test_exhausted_gemini_503_retries_return_catalog_fallback_without_provider_details(self):
        unavailable = RuntimeError("private upstream response")
        unavailable.code = 503
        with patch.object(ai_server, "get_contents", return_value=self.catalog), \
                patch.object(ai_server.client.models, "generate_content",
                             side_effect=[unavailable, unavailable, unavailable]) as model, \
                patch.object(ai_server.time, "sleep") as sleep, \
                self.assertLogs(ai_server.logger, level="WARNING") as captured:
            response = self.client.post("/recommend", json={"taste": "test", "contentType": "movie"})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("private upstream response", response.text)
        self.assertEqual(response.json()["recommendation_source"], "local_fallback")
        self.assertTrue(response.json()["recommendations"])
        scores = [row["match_score"] for row in response.json()["recommendations"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(model.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4])
        logs = " ".join(captured.output)
        self.assertIn("Gemini generation failed", logs)
        self.assertIn("RuntimeError", logs)
        self.assertIn("503", logs)
        self.assertNotIn("private upstream response", logs)
