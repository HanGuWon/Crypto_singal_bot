from __future__ import annotations

import math


def summarize_returns(returns: list[float]) -> dict[str, float]:
    if not returns:
        return {
            "trades": 0,
            "hit_rate": 0.0,
            "average_return": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
        }
    wins = [ret for ret in returns if ret > 0]
    losses = [ret for ret in returns if ret < 0]
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for ret in returns:
        equity *= 1 + ret
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1)
    mean = sum(returns) / len(returns)
    variance = sum((ret - mean) ** 2 for ret in returns) / len(returns)
    sharpe = 0.0 if variance == 0 else mean / math.sqrt(variance)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "trades": float(len(returns)),
        "hit_rate": len(wins) / len(returns),
        "average_return": mean,
        "profit_factor": gross_win / gross_loss if gross_loss else float("inf"),
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
    }
