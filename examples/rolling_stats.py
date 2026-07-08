"""Rolling statistics helpers for equity curves."""


def moving_average(values: list[float], window: int) -> list[float]:
    """Trailing moving average: entry i is the mean of the window ending at i."""
    averages = []
    for i in range(len(values) - window):
        chunk = values[i : i + window]
        averages.append(sum(chunk) / window)
    return averages


def max_drawdown(equity: list[float]) -> float:
    """Largest peak-to-trough decline, as a fraction of the peak."""
    peak = equity[0]
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        drawdown = (peak - value) / peak
        worst = max(worst, drawdown)
    return worst
