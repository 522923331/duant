"""CLI 入口"""

from datetime import datetime
from pathlib import Path

import click
from loguru import logger

from duant.core.config import load_config


def _setup_logging(config) -> None:
    """配置日志"""
    logger.add(
        f"{config.log.path}/duant_{{time}}.log",
        rotation=config.log.rotation,
        retention=config.log.retention,
        level=config.log.level,
    )


@click.group()
def cli():
    """duant - 个人量化交易系统"""
    pass


@cli.command()
@click.option("--strategy", "-s", required=True, help="策略名称")
@click.option("--symbol", multiple=True, help="交易标的")
@click.option("--market", default="a_stock", type=click.Choice(["a_stock", "crypto"]), help="市场")
@click.option("--timeframe", default="1d", help="K线周期")
@click.option("--start", default="2024-01-01", help="开始日期 YYYY-MM-DD")
@click.option("--end", default=None, help="结束日期 YYYY-MM-DD")
@click.option("--cash", default=1000000, type=float, help="初始资金")
def backtest(strategy, symbol, market, timeframe, start, end, cash):
    """运行回测"""
    from duant.core.event import Market, TimeFrame
    from duant.backtest.engine import BacktestEngine
    from duant.backtest.report import print_report
    from duant.strategy.loader import StrategyLoader

    config = load_config()
    _setup_logging(config)

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now()

    # 加载策略
    project_root = Path.cwd()
    loader = StrategyLoader(
        yaml_dir=project_root / "config" / "strategies",
        python_dir=project_root / "strategies",
    )
    strat = loader.load(strategy)

    # 运行回测
    bt_config = config.backtest
    bt_config.initial_cash = cash
    engine = BacktestEngine(bt_config, data_path=config.data.data_path)
    result = engine.run(
        strategy=strat,
        symbols=list(symbol) if symbol else ["000001.SZ"],
        start=start_dt,
        end=end_dt,
        market=Market(market),
        timeframe=TimeFrame(timeframe),
    )

    print_report(result)


@cli.command()
@click.option("--strategy", "-s", required=True, help="策略名称")
def paper(strategy):
    """启动模拟盘"""
    click.echo("模拟盘功能开发中...")


@cli.command()
@click.option("--strategy", "-s", required=True, help="策略名称")
def live(strategy):
    """启动实盘交易"""
    click.echo("实盘交易功能开发中...")


@cli.command()
@click.option("--port", default=8501, help="端口号")
def web(port):
    """启动 Web UI"""
    click.echo("Web UI 功能开发中...")


@cli.command()
@click.option("--symbol", multiple=True, help="标的代码")
@click.option("--market", default="a_stock", type=click.Choice(["a_stock", "crypto"]), help="市场")
@click.option("--timeframe", default="1d", help="K线周期")
@click.option("--start", default=None, help="开始日期 YYYY-MM-DD")
@click.option("--end", default=None, help="结束日期 YYYY-MM-DD")
def update(symbol, market, timeframe, start, end):
    """增量更新行情数据"""
    from duant.core.event import Market, TimeFrame
    from duant.data.fetcher import DataFetcher
    from duant.data.parquet_store import ParquetStore

    config = load_config()
    _setup_logging(config)

    fetcher = DataFetcher(tushare_token=config.data.tushare_token)
    store = ParquetStore(config.data.data_path)

    symbols = list(symbol) if symbol else ["000001.SZ"]
    start_dt = datetime.strptime(start, "%Y-%m-%d") if start else None
    end_dt = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now()

    for sym in symbols:
        # 增量更新：从上次最后日期开始
        if not start_dt:
            last = store.get_last_date(sym, Market(market), TimeFrame(timeframe))
            if last:
                from datetime import timedelta
                start_dt = last + timedelta(days=1)
            else:
                start_dt = datetime(2020, 1, 1)

        click.echo(f"更新 {sym} {market} {timeframe} ({start_dt.date()} ~ {end_dt.date()})")
        df = fetcher.fetch_bars(sym, Market(market), TimeFrame(timeframe), start_dt, end_dt)
        if not df.empty:
            store.save(df, sym, Market(market), TimeFrame(timeframe))
            click.echo(f"  写入 {len(df)} 条数据")
        else:
            click.echo("  无新数据")

    click.echo("更新完成")


if __name__ == "__main__":
    cli()
