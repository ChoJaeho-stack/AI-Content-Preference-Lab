"""Unit tests use synthetic fixtures only; no real webtoon records are included."""

import unittest

from webtoon_personalization import build_taste_profile, extend_taste_profile, score_candidate


class WebtoonPersonalizationTests(unittest.TestCase):
    def test_survey_baseline_and_explicit_feedback_combine(self):
        profile = build_taste_profile(
            {"genres": ["fantasy"], "story": ["growth"], "mood": ["warm"], "pacing": "fast"},
            [
                {"rating": 1, "features": {"genres": ["fantasy", "romance"], "mood": ["warm"]}},
                {"rating": -1, "features": {"genres": ["fantasy"], "pacing": ["fast"]}},
                {"rating": 0, "features": {"story": ["growth"], "mood": ["warm"]}},
            ],
        )
        self.assertAlmostEqual(profile["dimensions"]["genres"]["fantasy"], 1 / 7, places=4)
        self.assertEqual(profile["dimensions"]["genres"]["romance"], 1.0)
        self.assertEqual(profile["dimensions"]["pacing"]["fast"], -0.5)
        self.assertEqual(profile["dimensions"]["story"]["growth"], 1.0)

    def test_neutral_evaluation_adds_no_preference(self):
        profile = build_taste_profile(
            None,
            [{"rating": 0, "features": {"genres": ["fantasy"]}}],
        )
        self.assertEqual(profile["dimensions"]["genres"], {})

    def test_fit_score_explains_matches_and_mismatches(self):
        profile = build_taste_profile(
            {"genres": ["fantasy"], "mood": ["dark"]},
            [{"rating": -1, "features": {"mood": ["dark"]}}],
        )
        result = score_candidate(
            profile,
            {"genres": ["fantasy"], "mood": ["dark"]},
            algorithm_score=70,
        )
        self.assertEqual(result["personal_fit_score"], 70)
        self.assertEqual(result["rank_score"], 78)
        self.assertEqual(
            {(item["dimension"], item["feature"], item["signal"]) for item in result["fit_reasons"]},
            {("genres", "fantasy", "match"), ("mood", "dark", "mismatch")},
        )

    def test_empty_profile_has_neutral_fit_and_no_extra_weight(self):
        result = score_candidate({}, {"genres": ["fantasy"]}, algorithm_score=42)
        self.assertEqual(result["personal_fit_score"], 50)
        self.assertEqual(result["rank_score"], 42)
        self.assertEqual(result["fit_reasons"], [])

    def test_partial_match_is_normalized_against_active_preferences(self):
        profile = {"dimensions": {"genres": {
            "fantasy": 1, "romance": 1, "mystery": 1, "slice-of-life": 1,
            "action": 1, "comedy": 1, "drama": 1, "historical": 1,
            "sci-fi": 1, "sports": 1,
        }}}
        result = score_candidate(profile, {"genres": ["fantasy"]})
        self.assertEqual(result["personal_fit_score"], 55)

    def test_compound_catalog_genre_matches_each_component_and_full_label(self):
        features = {"genres": ["스릴러 / 공포"]}
        for genre in ("스릴러", "공포", "스릴러 / 공포"):
            with self.subTest(genre=genre):
                result = score_candidate({"dimensions": {"genres": {genre: 1}}}, features)
                self.assertEqual(result["personal_fit_score"], 100)
                self.assertEqual(result["fit_reasons"][0]["feature"], genre)

        negative = score_candidate({"dimensions": {"genres": {"공포": -1}}}, features)
        self.assertEqual(negative["personal_fit_score"], 0)
        unrelated = score_candidate({"dimensions": {"genres": {"공": 1}}}, features)
        self.assertEqual(unrelated["personal_fit_score"], 50)
        mood = score_candidate({"dimensions": {"mood": {"공포": 1}}}, {"mood": ["긴장 / 공포"]})
        self.assertEqual(mood["personal_fit_score"], 50)

    def test_neutral_signals_do_not_dilute_fit_and_reasons_follow_contribution(self):
        result = score_candidate({"dimensions": {
            "genres": {" Romance ": 0.1, "neutral": 0, "bad": float("nan")},
            "mood": {"warm": 2, "ignored": True},
        }}, {"genres": ["romance", "neutral", "bad"], "mood": ["warm", "ignored"]})
        self.assertEqual(result["personal_fit_score"], 73)
        self.assertEqual([part["feature"] for part in result["fit_reasons"]], ["warm", "romance"])

    def test_liked_catalog_features_and_explicit_genre_exclusion_are_scored(self):
        profile = extend_taste_profile(
            {"dimensions": {"genres": {}, "official_tags": {}}},
            [{"genres": ["무협/사극"], "official_tags": ["회귀", "동양풍판타지"]}],
            {"genres": ["공포"]},
        )
        similar = score_candidate(profile, {
            "genres": ["무협/사극"], "official_tags": ["회귀", "동양풍판타지"]
        })
        horror = score_candidate(profile, {"genres": ["스릴러/공포"]})

        self.assertGreater(similar["personal_fit_score"], 50)
        self.assertTrue(any(reason["signal"] == "match" for reason in similar["fit_reasons"]))
        self.assertTrue(any(reason["signal"] == "mismatch" for reason in horror["fit_reasons"]))
        self.assertIn("공포", profile["dimensions"]["genres"])

    def test_horror_alias_and_compound_genre_components_match(self):
        result = score_candidate(
            {"dimensions": {"genres": {"호러": -1}}},
            {"genres": ["스릴러 / 공포"]},
        )
        self.assertEqual(result["personal_fit_score"], 0)
        self.assertEqual(result["fit_reasons"][0]["signal"], "mismatch")


if __name__ == "__main__":
    unittest.main()
