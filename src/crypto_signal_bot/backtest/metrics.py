from __future__ import annotations

import math


def summarize_returns(returns: list[float]) -> dict[str, float]:
    if not returns:
        return {
            "trades": 0,
            "hit_rate": 0.0,
            "average_return": 0.0,
            "average_win": 0.0,
            "average_loss": 0.0,
            "gain_loss_factor": 0.0,
            "profit_factor": 0.0,
            "win_loss_ratio": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "worst_return": 0.0,
            "tail_loss_5pct": 0.0,
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
    downside_variance = sum(ret**2 for ret in losses) / len(returns)
    sortino = 0.0 if downside_variance == 0 else mean / math.sqrt(downside_variance)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    average_win = sum(wins) / len(wins) if wins else 0.0
    average_loss = sum(losses) / len(losses) if losses else 0.0
    gain_loss_factor = gross_win / gross_loss if gross_loss else 0.0
    return {
        "trades": float(len(returns)),
        "hit_rate": len(wins) / len(returns),
        "average_return": mean,
        "average_win": average_win,
        "average_loss": average_loss,
        "gain_loss_factor": gain_loss_factor,
        "profit_factor": gain_loss_factor,
        "win_loss_ratio": average_win / abs(average_loss) if average_loss else 0.0,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "sortino": sortino,
        "worst_return": min(returns),
        "tail_loss_5pct": _percentile(sorted(returns), 0.05),
    }


def _percentile(sorted_values: list[float], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    index = max(0, min(len(sorted_values) - 1, math.ceil(percentile * len(sorted_values)) - 1))
    return sorted_values[index]
