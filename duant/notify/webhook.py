"""Webhook 通知，支持企业微信和 Telegram"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass

import requests
from loguru import logger

from duant.core.event import Account, RiskEvent, Trade


@dataclass
class WebhookConfig:
    type: str          # wecom / telegram
    url: str           # webhook URL
    secret: str = ""   # 企业微信签名密钥


class Notifier:
    """Webhook 通知"""

    def __init__(self, webhooks: list[dict] | None = None):
        self.webhooks: list[WebhookConfig] = []
        if webhooks:
            for wh in webhooks:
                self.webhooks.append(WebhookConfig(
                    type=wh.get("type", "wecom"),
                    url=wh.get("url", ""),
                    secret=wh.get("secret", ""),
                ))

    def send(self, title: str, content: str, level: str = "info") -> None:
        """发送通知到所有配置的 webhook"""
        for wh in self.webhooks:
            try:
                if wh.type == "wecom":
                    self._send_wecom(wh, title, content, level)
                elif wh.type == "telegram":
                    self._send_telegram(wh, title, content, level)
                else:
                    logger.warning(f"未知 webhook 类型: {wh.type}")
            except Exception as e:
                logger.error(f"发送 {wh.type} 通知失败: {e}")

    def send_trade(self, trade: Trade) -> None:
        """成交通知"""
        side_text = "买入" if trade.side.value == "buy" else "卖出"
        title = f"成交通知: {side_text} {trade.symbol}"
        content = (
            f"标的: {trade.symbol}\n"
            f"方向: {side_text}\n"
            f"价格: {trade.price:.2f}\n"
            f"数量: {trade.amount:.0f}\n"
            f"手续费: {trade.commission:.2f}\n"
            f"时间: {trade.traded_at.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.send(title, content, "info")

    def send_risk(self, event: RiskEvent) -> None:
        """风控通知（高优先级）"""
        level_text = "账户级" if event.level.value == "account" else "策略级"
        action_text = {
            "reject": "拒绝订单",
            "close": "强制平仓",
            "pause": "暂停策略",
            "halt": "暂停所有策略",
        }.get(event.action.value, event.action.value)

        title = f"[风控警告] {event.rule_name} - {action_text}"
        content = (
            f"级别: {level_text}\n"
            f"规则: {event.rule_name}\n"
            f"动作: {action_text}\n"
            f"标的: {event.symbol or '全账户'}\n"
            f"详情: {event.detail}\n"
            f"时间: {event.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.send(title, content, "warning")

    def send_daily_report(self, account: Account) -> None:
        """每日报告"""
        total_pnl = account.total_value - 1_000_000  # 简化：用初始资金
        total_pnl_pct = total_pnl / 1_000_000 if 1_000_000 > 0 else 0

        pos_text = ""
        for p in account.positions:
            pnl_pct = (p.current_price - p.avg_price) / p.avg_price if p.avg_price > 0 else 0
            pos_text += f"\n  {p.symbol}: {p.quantity:.0f}股 盈亏{pnl_pct:+.2%}"

        title = "每日收盘报告"
        content = (
            f"总资产: ¥{account.total_value:,.0f}\n"
            f"现金: ¥{account.cash:,.0f}\n"
            f"累计盈亏: ¥{total_pnl:,.0f} ({total_pnl_pct:+.2%})\n"
            f"持仓数: {len(account.positions)}"
            f"{pos_text}"
        )
        self.send(title, content, "info")

    def _send_wecom(self, wh: WebhookConfig, title: str, content: str, level: str) -> None:
        """企业微信 webhook"""
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": f"**{title}**\n{content}",
            },
        }

        url = wh.url
        if wh.secret:
            timestamp = str(int(time.time()))
            sign = self._wecom_sign(timestamp, wh.secret)
            url = f"{url}&timestamp={timestamp}&sign={sign}"

        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200 or resp.json().get("errcode", 0) != 0:
            logger.warning(f"企业微信通知失败: {resp.text}")

    def _send_telegram(self, wh: WebhookConfig, title: str, content: str, level: str) -> None:
        """Telegram Bot webhook"""
        text = f"*{title}*\n{content}"
        payload = {
            "text": text,
            "parse_mode": "Markdown",
        }

        resp = requests.post(wh.url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"Telegram 通知失败: {resp.text}")

    @staticmethod
    def _wecom_sign(timestamp: str, secret: str) -> str:
        """企业微信签名"""
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        import base64
        return base64.b64encode(hmac_code).decode("utf-8")
