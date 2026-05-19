"""SQLite 交易记录存储"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from duant.core.event import (
    Market,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    RiskAction,
    RiskEvent,
    RiskLevel,
    Trade,
)

_DDL = """
CREATE TABLE IF NOT EXISTS orders (
    order_id    TEXT PRIMARY KEY,
    symbol      TEXT NOT NULL,
    market      TEXT NOT NULL,
    side        TEXT NOT NULL,
    order_type  TEXT NOT NULL,
    price       REAL NOT NULL DEFAULT 0,
    amount      REAL NOT NULL,
    filled      REAL NOT NULL DEFAULT 0,
    status      TEXT NOT NULL,
    strategy    TEXT NOT NULL,
    reject_reason TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id    TEXT PRIMARY KEY,
    order_id    TEXT NOT NULL REFERENCES orders(order_id),
    symbol      TEXT NOT NULL,
    market      TEXT NOT NULL,
    side        TEXT NOT NULL,
    price       REAL NOT NULL,
    amount      REAL NOT NULL,
    commission  REAL NOT NULL DEFAULT 0,
    slippage    REAL NOT NULL DEFAULT 0,
    traded_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    market      TEXT NOT NULL,
    quantity    REAL NOT NULL,
    avg_price   REAL NOT NULL,
    current_price REAL NOT NULL,
    unrealized_pnl REAL NOT NULL DEFAULT 0,
    market_value REAL NOT NULL DEFAULT 0,
    snapshot_at TEXT NOT NULL,
    UNIQUE(symbol, market, snapshot_at)
);

CREATE TABLE IF NOT EXISTS risk_events (
    event_id    TEXT PRIMARY KEY,
    level       TEXT NOT NULL,
    rule_name   TEXT NOT NULL,
    action      TEXT NOT NULL,
    symbol      TEXT,
    detail      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_state (
    name        TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    mode        TEXT NOT NULL,
    config      TEXT NOT NULL,
    started_at  TEXT,
    stopped_at  TEXT,
    error_count INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_equity (
    date        TEXT NOT NULL,
    mode        TEXT NOT NULL,
    cash        REAL NOT NULL,
    market_value REAL NOT NULL,
    total_value REAL NOT NULL,
    realized_pnl REAL NOT NULL DEFAULT 0,
    PRIMARY KEY(date, mode)
);

CREATE TABLE IF NOT EXISTS data_sync (
    symbol      TEXT NOT NULL,
    market      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    last_date   TEXT NOT NULL,
    row_count   INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY(symbol, market, timeframe)
);
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_orders_strategy ON orders(strategy);
CREATE INDEX IF NOT EXISTS idx_trades_order ON trades(order_id);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_traded ON trades(traded_at);
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);
CREATE INDEX IF NOT EXISTS idx_positions_snapshot ON positions(snapshot_at);
CREATE INDEX IF NOT EXISTS idx_risk_level ON risk_events(level);
CREATE INDEX IF NOT EXISTS idx_risk_rule ON risk_events(rule_name);
CREATE INDEX IF NOT EXISTS idx_risk_created ON risk_events(created_at);
CREATE INDEX IF NOT EXISTS idx_equity_date ON daily_equity(date);
"""


class SqliteStore:
    """SQLite 读写，存交易记录、持仓、风控事件等"""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(_DDL)
            conn.executescript(_INDEXES)

    # --- 订单 ---

    def save_order(self, order: Order) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    order.order_id, order.symbol, order.market.value,
                    order.side.value, order.order_type.value, order.price,
                    order.amount, 0.0, order.status.value, order.strategy_name,
                    "", order.created_at.isoformat(), order.updated_at.isoformat(),
                ),
            )

    def update_order_status(
        self, order_id: str, status: OrderStatus, filled: float = 0, reject_reason: str = ""
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE orders SET status=?, filled=?, reject_reason=?, updated_at=? WHERE order_id=?",
                (status.value, filled, reject_reason, datetime.now().isoformat(), order_id),
            )

    def get_orders(
        self,
        symbol: str | None = None,
        status: OrderStatus | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Order]:
        query = "SELECT * FROM orders WHERE 1=1"
        params: list = []
        if symbol:
            query += " AND symbol=?"
            params.append(symbol)
        if status:
            query += " AND status=?"
            params.append(status.value)
        if start:
            query += " AND created_at>=?"
            params.append(start.isoformat())
        if end:
            query += " AND created_at<=?"
            params.append(end.isoformat())
        query += " ORDER BY created_at"

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_order(r) for r in rows]

    @staticmethod
    def _row_to_order(r: sqlite3.Row) -> Order:
        return Order(
            order_id=r["order_id"],
            symbol=r["symbol"],
            market=Market(r["market"]),
            side=OrderSide(r["side"]),
            order_type=OrderType(r["order_type"]),
            price=r["price"],
            amount=r["amount"],
            status=OrderStatus(r["status"]),
            strategy_name=r["strategy"],
            created_at=datetime.fromisoformat(r["created_at"]),
            updated_at=datetime.fromisoformat(r["updated_at"]),
        )

    # --- 成交 ---

    def save_trade(self, trade: Trade) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    trade.trade_id, trade.order_id, trade.symbol,
                    trade.market.value, trade.side.value, trade.price,
                    trade.amount, trade.commission, trade.slippage,
                    trade.traded_at.isoformat(),
                ),
            )

    def get_trades(
        self, symbol: str | None = None, start: datetime | None = None, end: datetime | None = None
    ) -> list[Trade]:
        query = "SELECT * FROM trades WHERE 1=1"
        params: list = []
        if symbol:
            query += " AND symbol=?"
            params.append(symbol)
        if start:
            query += " AND traded_at>=?"
            params.append(start.isoformat())
        if end:
            query += " AND traded_at<=?"
            params.append(end.isoformat())
        query += " ORDER BY traded_at"

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_trade(r) for r in rows]

    @staticmethod
    def _row_to_trade(r: sqlite3.Row) -> Trade:
        return Trade(
            trade_id=r["trade_id"],
            order_id=r["order_id"],
            symbol=r["symbol"],
            market=Market(r["market"]),
            side=OrderSide(r["side"]),
            price=r["price"],
            amount=r["amount"],
            commission=r["commission"],
            slippage=r["slippage"],
            traded_at=datetime.fromisoformat(r["traded_at"]),
        )

    # --- 持仓快照 ---

    def save_position_snapshot(self, positions: list[Position], snapshot_at: datetime) -> None:
        with self._conn() as conn:
            for p in positions:
                conn.execute(
                    "INSERT OR REPLACE INTO positions (symbol, market, quantity, avg_price, current_price, unrealized_pnl, market_value, snapshot_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        p.symbol, p.market.value, p.quantity, p.avg_price,
                        p.current_price, p.unrealized_pnl, p.market_value,
                        snapshot_at.isoformat(),
                    ),
                )

    def get_latest_positions(self) -> list[Position]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT p1.* FROM positions p1 "
                "INNER JOIN (SELECT symbol, market, MAX(snapshot_at) as max_at FROM positions GROUP BY symbol, market) p2 "
                "ON p1.symbol=p2.symbol AND p1.market=p2.market AND p1.snapshot_at=p2.max_at"
            ).fetchall()
        now = datetime.now()
        return [
            Position(
                symbol=r["symbol"], market=Market(r["market"]),
                quantity=r["quantity"], avg_price=r["avg_price"],
                current_price=r["current_price"], unrealized_pnl=r["unrealized_pnl"],
                market_value=r["market_value"], updated_at=now,
            )
            for r in rows
        ]

    # --- 风控事件 ---

    def save_risk_event(self, event: RiskEvent) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO risk_events VALUES (?,?,?,?,?,?,?)",
                (
                    event.event_id, event.level.value, event.rule_name,
                    event.action.value, event.symbol, event.detail,
                    event.created_at.isoformat(),
                ),
            )

    def get_risk_events(
        self, level: RiskLevel | None = None, start: datetime | None = None
    ) -> list[RiskEvent]:
        query = "SELECT * FROM risk_events WHERE 1=1"
        params: list = []
        if level:
            query += " AND level=?"
            params.append(level.value)
        if start:
            query += " AND created_at>=?"
            params.append(start.isoformat())
        query += " ORDER BY created_at DESC"

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            RiskEvent(
                event_id=r["event_id"], level=RiskLevel(r["level"]),
                rule_name=r["rule_name"], action=RiskAction(r["action"]),
                symbol=r["symbol"], detail=r["detail"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    # --- 策略状态 ---

    def save_strategy_state(self, name: str, status: str, mode: str, config: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO strategy_state (name, status, mode, config, updated_at) VALUES (?,?,?,?,?)",
                (name, status, mode, json.dumps(config, ensure_ascii=False), datetime.now().isoformat()),
            )

    def get_strategy_state(self, name: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM strategy_state WHERE name=?", (name,)).fetchone()
        if not row:
            return None
        return {
            "name": row["name"],
            "status": row["status"],
            "mode": row["mode"],
            "config": json.loads(row["config"]),
            "started_at": row["started_at"],
            "stopped_at": row["stopped_at"],
            "error_count": row["error_count"],
        }

    # --- 每日净值 ---

    def save_daily_equity(
        self, date: str, mode: str, cash: float, market_value: float,
        total_value: float, realized_pnl: float,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO daily_equity VALUES (?,?,?,?,?,?)",
                (date, mode, cash, market_value, total_value, realized_pnl),
            )

    def get_equity_curve(self, mode: str, start: str | None = None) -> pd.DataFrame:
        query = "SELECT * FROM daily_equity WHERE mode=?"
        params: list = [mode]
        if start:
            query += " AND date>=?"
            params.append(start)
        query += " ORDER BY date"

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([dict(r) for r in rows])

    # --- 数据同步 ---

    def get_sync_record(self, symbol: str, market: str, timeframe: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM data_sync WHERE symbol=? AND market=? AND timeframe=?",
                (symbol, market, timeframe),
            ).fetchone()
        if not row:
            return None
        return {"last_date": row["last_date"], "row_count": row["row_count"]}

    def update_sync_record(self, symbol: str, market: str, timeframe: str, last_date: str, row_count: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO data_sync VALUES (?,?,?,?,?,?)",
                (symbol, market, timeframe, last_date, row_count, datetime.now().isoformat()),
            )
