"""
通知モジュール

Slack WebhookとSMTPメールによる通知を提供する。
"""

import hashlib
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from bid_aggregator.core.config import settings
from bid_aggregator.core.models import Item

logger = logging.getLogger(__name__)


class NotificationError(Exception):
    """通知エラー"""
    pass


# =============================================================================
# メッセージフォーマット
# =============================================================================


def format_item_text(item: Item) -> str:
    """アイテムをテキスト形式でフォーマット"""
    lines = [
        f"【{item.title}】",
        f"機関: {item.organization_name}",
    ]
    
    if item.deadline_at:
        lines.append(f"締切: {item.deadline_at.strftime('%Y-%m-%d')}")
    elif item.published_at:
        lines.append(f"公開日: {item.published_at.strftime('%Y-%m-%d')}")
    
    if item.url:
        lines.append(f"URL: {item.url}")
    
    return "\n".join(lines)


def format_item_slack(item: Item) -> dict:
    """アイテムをSlack Block形式でフォーマット"""
    # 日付の決定
    if item.deadline_at:
        date_str = f"締切: {item.deadline_at.strftime('%Y-%m-%d')}"
    elif item.published_at:
        date_str = f"公開日: {item.published_at.strftime('%Y-%m-%d')}"
    else:
        date_str = ""
    
    text = f"*{item.title}*\n{item.organization_name}"
    if date_str:
        text += f" / {date_str}"
    if item.url:
        text += f"\n<{item.url}|詳細を見る>"
    
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": text,
        },
    }


def format_items_for_slack(
    items: list[Item],
    saved_search_name: str,
    max_items: int = 100,
) -> dict:
    """複数アイテムをSlackメッセージ形式でフォーマット"""
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🔔 入札情報アラート: {saved_search_name}",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"新着 {len(items)} 件の案件があります",
                },
            ],
        },
        {"type": "divider"},
    ]
    
    # アイテムを追加（上限まで）
    for item in items[:max_items]:
        blocks.append(format_item_slack(item))
        blocks.append({"type": "divider"})
    
    # 上限超過の場合
    if len(items) > max_items:
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"他 {len(items) - max_items} 件は次回通知されます",
                },
            ],
        })
    
    # フッター
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": "出典: <https://www.kkj.go.jp/s/|官公需情報ポータルサイト>",
            },
        ],
    })
    
    return {"blocks": blocks}


def format_items_for_email(
    items: list[Item],
    saved_search_name: str,
    max_items: int = 100,
) -> tuple[str, str]:
    """複数アイテムをメール形式でフォーマット（件名, 本文）"""
    subject = f"[入札情報アラート] {saved_search_name}: {len(items)}件の新着"
    
    lines = [
        f"入札情報アラート: {saved_search_name}",
        f"新着 {len(items)} 件の案件があります",
        "",
        "=" * 50,
        "",
    ]
    
    for i, item in enumerate(items[:max_items], 1):
        lines.append(f"[{i}] {item.title}")
        lines.append(f"    機関: {item.organization_name}")
        
        if item.deadline_at:
            lines.append(f"    締切: {item.deadline_at.strftime('%Y-%m-%d')}")
        elif item.published_at:
            lines.append(f"    公開日: {item.published_at.strftime('%Y-%m-%d')}")
        
        if item.url:
            lines.append(f"    URL: {item.url}")
        
        lines.append("")
    
    if len(items) > max_items:
        lines.append(f"※ 他 {len(items) - max_items} 件は次回通知されます")
        lines.append("")
    
    lines.extend([
        "=" * 50,
        "",
        "出典: 官公需情報ポータルサイト",
        "https://www.kkj.go.jp/s/",
    ])
    
    return subject, "\n".join(lines)


# =============================================================================
# Slack通知
# =============================================================================


def send_slack_notification(
    webhook_url: str,
    items: list[Item],
    saved_search_name: str,
    max_items: int = 100,
) -> None:
    """Slack Webhookで通知を送信"""
    if not items:
        logger.info("通知するアイテムがありません")
        return
    
    payload = format_items_for_slack(items, saved_search_name, max_items)
    
    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(webhook_url, json=payload)
            
            if response.status_code != 200:
                raise NotificationError(
                    f"Slack API error: {response.status_code} - {response.text}"
                )
            
            logger.info(f"Slack通知送信成功: {len(items)}件")
            
    except httpx.RequestError as e:
        raise NotificationError(f"Slack通信エラー: {e}") from e


# =============================================================================
# メール通知
# =============================================================================


def send_email_notification(
    to_address: str,
    items: list[Item],
    saved_search_name: str,
    max_items: int = 100,
) -> None:
    """SMTPでメール通知を送信"""
    if not items:
        logger.info("通知するアイテムがありません")
        return
    
    # SMTP設定の確認
    if not all([settings.smtp_host, settings.smtp_from]):
        raise NotificationError("SMTP設定が不完全です")
    
    subject, body = format_items_for_email(items, saved_search_name, max_items)
    
    # メッセージ作成
    msg = MIMEMultipart()
    msg["From"] = settings.smtp_from
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    
    try:
        if settings.smtp_use_tls:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
            server.starttls()
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
        
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        
        server.send_message(msg)
        server.quit()
        
        logger.info(f"メール通知送信成功: {to_address}, {len(items)}件")
        
    except smtplib.SMTPException as e:
        raise NotificationError(f"SMTPエラー: {e}") from e


# =============================================================================
# 統合通知関数
# =============================================================================


def send_notification(
    channel: str,
    recipient: str,
    items: list[Item],
    saved_search_name: str,
    max_items: int = 100,
) -> None:
    """チャネルに応じて通知を送信"""
    if channel == "slack":
        send_slack_notification(recipient, items, saved_search_name, max_items)
    elif channel == "email":
        send_email_notification(recipient, items, saved_search_name, max_items)
    else:
        raise NotificationError(f"未対応の通知チャネル: {channel}")


def generate_dedupe_key(
    saved_search_id: int,
    run_id: int,
    channel: str,
    recipient: str,
) -> str:
    """通知の重複防止キーを生成"""
    content = f"{saved_search_id}:{run_id}:{channel}:{recipient}"
    return hashlib.sha256(content.encode()).hexdigest()
