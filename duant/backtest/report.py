"""回测报告生成"""

import numpy as np
from dataclasses import dataclass

from duant.core.event import BacktestMetrics, OrderSide, Trade


@dataclass(frozen=True)
class BacktestResult:
    metrics: BacktestMetrics
    trades: tuple
    equity_curve: "pd.DataFrame"
    positions: tuple


def calculate_metrics(portfolio, initial_cash: float) -> BacktestMetrics:
    """计算回测指标"""
    trades = portfolio.trades
    equity = portfolio.equity_records

    if not equity:
        return BacktestMetrics(0, 0, 0, 0, 0, 0, 0)

    # 总收益率
    final_value = equity[-1]["total_value"] if equity else initial_cash
    total_return = (final_value - initial_cash) / initial_cash

    # 年化收益率（按 252 个交易日）
    trading_days = len(equity)
    annual_return = (1 + total_return) ** (252 / max(trading_days, 1)) - 1 if trading_days > 0 else 0

    # 最大回撤
    max_drawdown = _calc_max_drawdown(equity)

    # 夏普比率（无风险利率 2%）
    daily_returns = _calc_daily_returns(equity)
    sharpe_ratio = _calc_sharpe(daily_returns, risk_free=0.02)

    # 胜率和盈亏比（基于配对买卖计算真实盈亏）
    win_rate, profit_loss_ratio = _calc_win_stats(trades)

    return BacktestMetrics(
        total_return=total_return,
        annual_return=annual_return,
        max_drawdown=max_drawdown,
        sharpe_ratio=sharpe_ratio,
        win_rate=win_rate,
        profit_loss_ratio=profit_loss_ratio,
        trade_count=len(trades),
    )


def _calc_max_drawdown(equity_records: list[dict]) -> float:
    """最大回撤"""
    if len(equity_records) < 2:
        return 0.0

    values = [r["total_value"] for r in equity_records]
    peak = values[0]
    max_dd = 0.0

    for v in values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        max_dd = max(max_dd, dd)

    return max_dd


def _calc_daily_returns(equity_records: list[dict]) -> list[float]:
    """日收益率序列"""
    if len(equity_records) < 2:
        return []

    values = [r["total_value"] for r in equity_records]
    returns = []
    for i in range(1, len(values)):
        if values[i - 1] > 0:
            returns.append((values[i] - values[i - 1]) / values[i - 1])
    return returns


def _calc_sharpe(daily_returns: list[float], risk_free: float = 0.02) -> float:
    """夏普比率"""
    if len(daily_returns) < 2:
        return 0.0

    arr = np.array(daily_returns)
    mean_return = arr.mean()
    std_return = arr.std()

    if std_return == 0:
        return 0.0

    daily_rf = risk_free / 252
    sharpe = (mean_return - daily_rf) / std_return * np.sqrt(252)
    return round(sharpe, 2)


def _calc_win_stats(trades: list[Trade]) -> tuple[float, float]:
    """基于买卖配对计算胜率和盈亏比

    用 FIFO 匹配：买入建仓，卖出平仓，计算每笔平仓的真实盈亏
    """
    # 按标的分组，FIFO 匹配买卖
    open_positions: dict[str, list[tuple[float, float]]] = {}  # symbol -> [(price, qty)]
    realized_pnls: list[float] = []

    for t in trades:
        sym = t.symbol
        if sym not in open_positions:
            open_positions[sym] = []

        if t.side == OrderSide.BUY:
            open_positions[sym].append((t.price, t.amount))
        elif t.side == OrderSide.SELL:
            remaining = t.amount
            # FIFO 匹配已买入的仓位
            while remaining > 0 and open_positions[sym]:
                buy_price, buy_qty = open_positions[sym][0]
                matched = min(remaining, buy_qty)
                # 真实盈亏 = (卖出价 - 买入价) * 匹配数量 - 手续费摊销
                pnl = (t.price - buy_price) * matched
                realized_pnls.append(pnl)

                remaining -= matched
                if matched >= buy_qty:
                    open_positions[sym].pop(0)
                else:
                    open_positions[sym][0] = (buy_price, buy_qty - matched)

    if not realized_pnls:
        return 0.0, 0.0

    wins = [p for p in realized_pnls if p > 0]
    losses = [p for p in realized_pnls if p < 0]

    win_rate = len(wins) / len(realized_pnls)
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0

    return win_rate, profit_loss_ratio


def print_report(result: BacktestResult) -> None:
    """打印回测报告到控制台"""
    m = result.metrics
    print("\n" + "=" * 50)
    print("  回测报告")
    print("=" * 50)
    print(f"  总收益率:   {m.total_return:>10.2%}")
    print(f"  年化收益率: {m.annual_return:>10.2%}")
    print(f"  最大回撤:   {m.max_drawdown:>10.2%}")
    print(f"  夏普比率:   {m.sharpe_ratio:>10.2f}")
    print(f"  胜率:       {m.win_rate:>10.2%}")
    print(f"  盈亏比:     {m.profit_loss_ratio:>10.2f}")
    print(f"  交易次数:   {m.trade_count:>10d}")
    print("=" * 50)

    if result.trades:
        print(f"\n  最近 5 笔交易:")
        for t in result.trades[-5:]:
            print(f"    {t.traded_at.strftime('%Y-%m-%d')} {t.side.value:4s} "
                  f"{t.symbol} 价格={t.price:.2f} 数量={t.amount:.0f} "
                  f"手续费={t.commission:.2f}")
