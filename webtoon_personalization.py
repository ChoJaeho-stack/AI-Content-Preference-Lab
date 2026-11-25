"""Deterministic taste profile and candidate scoring for catalog recommendations.

This module is deliberately independent of any provider data or database. The
Spring service supplies only catalog features belonging to the authenticated
member's survey and evaluations.
"""

from __future__ import annotations

from collections import defaultdict
from math import isfinite
import re
from typing import Any, Iterable


DIMENSIONS = ("genres", "story", "mood", "pacing", "official_tags")
SURVEY_WEIGHT = 1.0
FEEDBACK_WEIGHT = 3.0
FEATURE_ALIASES = {"호러": "공포", "horror": "공포"}


def _values(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    return list(dict.fromkeys(
        str(item).strip().casefold()
        for item in value
        if isinstance(item, (str, int, float)) and str(item).strip()
    ))


def _canonical(value: str) -> str:
    normalized = value.strip().casefold()
    return FEATURE_ALIASES.get(normalized, normalized)


def _candidate_values(value: Any, split_compounds: bool) -> set[str]:
    values = {_canonical(item) for item in _values(value)}
    if split_compounds:
        for item in tuple(values):
            values.update(_canonical(part) for part in re.split(r"[/／|]", item) if part.strip())
    return values


def extend_taste_profile(
    profile: dict[str, Any] | None,
    positive_features: Iterable[dict[str, Any]],
    negative_features: dict[str, Iterable[str]],
) -> dict[str, Any]:
    """Merge current liked works and explicit exclusions into the request profile.

    Features must come from the verified catalog or the user's explicit dislike
    field. This does not infer genres from a title or generate feature labels.
    Current explicit inputs take precedence over older profile values.
    """
    base_dimensions = profile.get("dimensions", {}) if isinstance(profile, dict) else {}
    dimensions: dict[str, dict[str, float]] = {}
    for dimension in DIMENSIONS:
        source = base_dimensions.get(dimension, {}) if isinstance(base_dimensions, dict) else {}
        dimensions[dimension] = {
            _canonical(name): max(-1.0, min(1.0, float(value)))
            for name, value in source.items()
            if isinstance(name, str) and name.strip()
            and type(value) in (int, float) and isfinite(value) and value != 0
        } if isinstance(source, dict) else {}

    for features in positive_features:
        if not isinstance(features, dict):
            continue
        for dimension in DIMENSIONS:
            for feature in _values(features.get(dimension)):
                name = _canonical(feature)
                if name:
                    dimensions[dimension][name] = 1.0

    for dimension, values in negative_features.items():
        if dimension not in dimensions:
            continue
        for feature in _values(values):
            name = _canonical(feature)
            if name:
                dimensions[dimension][name] = -1.0

    return {"version": 1, "dimensions": dimensions}


def build_taste_profile(
    survey: dict[str, Any] | None,
    evaluations: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Blend survey preferences with explicit work feedback.

    Survey selections are positive baseline signals. A later like/dislike has
    three times the weight. Neutral feedback is retained by the caller but
    does not push any dimension in either direction.
    """
    totals: dict[str, dict[str, float]] = {dimension: defaultdict(float) for dimension in DIMENSIONS}
    weights: dict[str, dict[str, float]] = {dimension: defaultdict(float) for dimension in DIMENSIONS}

    if isinstance(survey, dict):
        for dimension in DIMENSIONS:
            for feature in _values(survey.get(dimension)):
                totals[dimension][feature] += SURVEY_WEIGHT
                weights[dimension][feature] += SURVEY_WEIGHT

    for evaluation in evaluations:
        if not isinstance(evaluation, dict):
            continue
        try:
            rating = int(evaluation.get("rating"))
        except (TypeError, ValueError):
            continue
        if rating not in (-1, 0, 1) or rating == 0:
            continue
        features = evaluation.get("features")
        if not isinstance(features, dict):
            continue
        for dimension in DIMENSIONS:
            for feature in _values(features.get(dimension)):
                totals[dimension][feature] += rating * FEEDBACK_WEIGHT
                weights[dimension][feature] += FEEDBACK_WEIGHT

    dimensions: dict[str, dict[str, float]] = {}
    for dimension in DIMENSIONS:
        dimensions[dimension] = {
            feature: round(totals[dimension][feature] / weights[dimension][feature], 4)
            for feature in sorted(weights[dimension])
            if weights[dimension][feature] > 0
        }

    return {
        "version": 1,
        "dimensions": dimensions,
        "summary": _summarize(dimensions),
    }


def _summarize(dimensions: dict[str, dict[str, float]]) -> list[str]:
    summary = []
    for dimension in DIMENSIONS:
        positives = [name for name, score in dimensions[dimension].items() if score > 0]
        negatives = [name for name, score in dimensions[dimension].items() if score < 0]
        if positives:
            summary.append(f"{dimension}: " + ", ".join(positives[:3]))
        if negatives:
            summary.append(f"avoid {dimension}: " + ", ".join(negatives[:3]))
    return summary


def score_candidate(
    profile: dict[str, Any],
    features: dict[str, Any],
    algorithm_score: float = 0.0,
) -> dict[str, Any]:
    """Add deterministic profile fit, score contributions, and explanations."""
    dimensions = profile.get("dimensions", {}) if isinstance(profile, dict) else {}
    contributions: list[tuple[float, dict[str, Any]]] = []
    weighted_total = 0.0
    available_weight = 0.0

    for dimension in DIMENSIONS:
        preference = dimensions.get(dimension, {}) if isinstance(dimensions, dict) else {}
        if not isinstance(preference, dict):
            continue
        active_preferences = {
            _canonical(name): max(-1.0, min(1.0, value))
            for name, value in preference.items()
            if isinstance(name, str) and name.strip()
            and type(value) in (int, float) and isfinite(value) and value != 0
        }
        if not active_preferences:
            continue
        candidate_values = _candidate_values(
            features.get(dimension), dimension in ("genres", "official_tags")
        )
        if dimension == "pacing" and not candidate_values:
            candidate_values = set(_values(features.get("pace")))
        matched = [(name, value) for name, value in active_preferences.items()
                   if name in candidate_values]
        dimension_weight = 1.5 if dimension == "genres" else 1.0
        mean = sum(value for _, value in matched) / len(active_preferences)
        weighted_total += mean * dimension_weight
        available_weight += dimension_weight
        for name, value in matched:
            magnitude = abs(value) * dimension_weight / len(active_preferences)
            contributions.append((magnitude, {
                "dimension": dimension, "feature": name,
                "signal": "match" if value > 0 else "mismatch",
            }))

    fit = 50 if available_weight == 0 else round(max(0, min(100, 50 + 50 * weighted_total / available_weight)))
    personalization_points = 0 if available_weight == 0 else round((fit - 50) * 0.4, 2)
    return {
        "personal_fit_score": fit,
        "personalization_points": personalization_points,
        "rank_score": float(algorithm_score) + personalization_points,
        "fit_reasons": [
            reason for _, reason in sorted(
                contributions,
                key=lambda item: (-item[0], item[1]["signal"], item[1]["dimension"], item[1]["feature"]),
            )
        ],
    }
