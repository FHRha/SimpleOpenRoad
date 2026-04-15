from app.core.types import RouteCandidate
from app.router.context_limits import CandidateContextLimit, filter_candidates_by_context


def test_context_filter_keeps_candidate_when_limit_is_unknown() -> None:
    candidates = [RouteCandidate(provider="openrouter", model="unknown-context-model")]

    kept, skipped = filter_candidates_by_context(candidates, token_estimate=1_000_000, limits={})

    assert kept == candidates
    assert skipped == []


def test_context_filter_skips_only_known_insufficient_limits() -> None:
    small = RouteCandidate(provider="openrouter", model="small")
    unknown = RouteCandidate(provider="openrouter", model="unknown")
    large = RouteCandidate(provider="openrouter", model="large")

    kept, skipped = filter_candidates_by_context(
        [small, unknown, large],
        token_estimate=50_000,
        limits={
            ("openrouter", "small"): CandidateContextLimit(max_context_tokens=8_000),
            ("openrouter", "large"): CandidateContextLimit(max_context_tokens=128_000),
        },
    )

    assert kept == [unknown, large]
    assert skipped == [
        {
            "provider": "openrouter",
            "model": "small",
            "status": "skipped",
            "reason": "context_too_large",
            "token_estimate": 50_000,
            "max_context_tokens": 8_000,
        }
    ]
