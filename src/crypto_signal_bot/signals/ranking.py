from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from crypto_signal_bot.signals.schemas import RankingResult, SignalCandidate


def rank_candidates(candidates: list[SignalCandidate], *, top: int | None = None) -> RankingResult:
    source_run_id = candidates[0].source_run_id if candidates else str(uuid4())
    sorted_candidates = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    ranked = [candidate.with_rank(index) for index, candidate in enumerate(sorted_candidates, start=1)]
    if top is not None:
        ranked = ranked[:top]
    return RankingResult(
        source_run_id=source_run_id,
        generated_at_utc=datetime.now(tz=UTC).isoformat(),
        candidates=ranked,
    )
