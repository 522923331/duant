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
@click.option("--risk/--no-risk", default=True, help="是否启用风控检查")
def backtest(strategy, symbol, market, timeframe, start, end, cash, risk):
    """运行回测"""
    from duant.core.event import Market, TimeFrame
    from duant.backtest.engine import BacktestEngine
    from duant.backtest.report import print_report
    from duant.strategy.loader import StrategyLoader
    from duant.position.sizer import create_sizer

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

    # 接入风控
    if risk:
        from duant.risk.manager import RiskManager
        from duant.data.sqlite_store import SqliteStore
        sqlite = SqliteStore(config.data.db_path)
        risk_manager = RiskManager(config.risk, sqlite)
        engine.set_risk_manager(risk_manager)

    # 接入仓位管理
    sizer = create_sizer({
        "sizer": config.position.sizer,
        config.position.sizer: getattr(config.position, config.position.sizer, {}),
    })
    engine.set_position_sizer(sizer)

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
@click.option("--symbol", default="000001.SZ", help="交易标的")
@click.option("--market", default="a_stock", type=click.Choice(["a_stock", "crypto"]), help="市场")
@click.option("--timeframe", default="1d", help="K线周期")
@click.option("--cash", default=1000000, type=float, help="初始资金")
def paper(strategy, symbol, market, timeframe, cash):
    """启动模拟盘"""
    from duant.core.event import Market, TimeFrame
    from duant.paper.engine import PaperEngine
    from duant.strategy.loader import StrategyLoader

    config = load_config()
    _setup_logging(config)

    project_root = Path.cwd()
    loader = StrategyLoader(
        yaml_dir=project_root / "config" / "strategies",
        python_dir=project_root / "strategies",
    )
    strat = loader.load(strategy)

    engine = PaperEngine(config=config, initial_cash=cash)
    engine.start(strat, symbol, Market(market), TimeFrame(timeframe))

    click.echo(f"模拟盘已启动: {strategy} {symbol}")
    click.echo("按 Ctrl+C 停止")

    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        engine.stop(strategy)
        click.echo("模拟盘已停止")


@cli.command()
@click.option("--strategy", "-s", required=True, help="策略名称")
@click.option("--symbol", default="000001.SZ", help="交易标的")
@click.option("--market", default="a_stock", type=click.Choice(["a_stock", "crypto"]), help="市场")
@click.option("--timeframe", default="1d", help="K线周期")
def live(strategy, symbol, market, timeframe):
    """启动实盘交易"""
    from duant.core.event import Market, TimeFrame
    from duant.trade.gateway import GatewayFactory
    from duant.strategy.loader import StrategyLoader
    from duant.risk.manager import RiskManager
    from duant.data.sqlite_store import SqliteStore
    from duant.notify.webhook import Notifier

    config = load_config()
    _setup_logging(config)

    if not config.trade.live_mode:
        click.echo("实盘模式未开启，请在配置中设置 trade.live_mode: true")
        return

    # 加载策略
    project_root = Path.cwd()
    loader = StrategyLoader(
        yaml_dir=project_root / "config" / "strategies",
        python_dir=project_root / "strategies",
    )
    strat = loader.load(strategy)

    # 连接交易网关
    try:
        gateway = GatewayFactory.create(config.trade)
        gateway.connect()
        click.echo(f"实盘网关已连接: {config.trade.gateway}")
    except Exception as e:
        click.echo(f"网关连接失败: {e}")
        return

    # 初始化风控
    sqlite = SqliteStore(config.data.db_path)
    notifier = Notifier(config.notify.webhooks if config.notify.webhooks else None)
    risk_manager = RiskManager(config.risk, sqlite, notifier)

    # 初始化仓位管理
    from duant.position.sizer import create_sizer
    sizer = create_sizer({
        "sizer": config.position.sizer,
        config.position.sizer: getattr(config.position, config.position.sizer, {}),
    })

    click.echo(f"实盘交易已启动: {strategy} {symbol}")
    click.echo("风控、通知、仓位管理已加载")
    click.echo("按 Ctrl+C 停止")

    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        try:
            gateway.disconnect()
        except Exception:
            pass
        click.echo("实盘交易已停止")


@cli.command()
@click.option("--port", default=8501, help="端口号")
def web(port):
    """启动 Web UI"""
    import subprocess
    import sys

    app_path = Path(__file__).parent / "web" / "app.py"
    click.echo(f"启动 Web UI: http://localhost:{port}")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", str(port)],
    )


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


@cli.command()
@click.option("--symbol", required=True, help="标的代码")
@click.option("--market", default="a_stock", type=click.Choice(["a_stock", "crypto"]), help="市场")
@click.option("--timeframe", default="1d", help="K线周期")
def validate(symbol, market, timeframe):
    """校验行情数据"""
    from duant.core.event import Market, TimeFrame
    from duant.data.parquet_store import ParquetStore
    from duant.data.validator import DataValidator

    config = load_config()
    _setup_logging(config)

    store = ParquetStore(config.data.data_path)
    validator = DataValidator(store)

    issues = validator.validate(symbol, Market(market), TimeFrame(timeframe))
    validator.print_report()


@cli.command()
@click.option("--url", required=True, help="Webhook URL")
@click.option("--type", "wh_type", default="wecom", type=click.Choice(["wecom", "telegram"]), help="Webhook 类型")
@click.option("--secret", default="", help="签名密钥（企业微信）")
def test_notify(url, wh_type, secret):
    """测试通知"""
    from duant.notify.webhook import Notifier, WebhookConfig

    notifier = Notifier([{"type": wh_type, "url": url, "secret": secret}])
    notifier.send("duant 测试通知", "如果你收到这条消息，说明通知配置正确！")
    click.echo("测试通知已发送")


if __name__ == "__main__":
    cli()
