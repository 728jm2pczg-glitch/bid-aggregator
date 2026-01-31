"""
通知（Notify）モジュール

Slack/メール通知と保存検索の実行を提供する。
"""

from bid_aggregator.notify.runner import SavedSearchRunner, run_saved_search
from bid_aggregator.notify.sender import (
    NotificationError,
    format_item_slack,
    format_item_text,
    format_items_for_email,
    format_items_for_slack,
    generate_dedupe_key,
    send_email_notification,
    send_notification,
    send_slack_notification,
)

__all__ = [
    "NotificationError",
    "send_notification",
    "send_slack_notification",
    "send_email_notification",
    "format_item_text",
    "format_item_slack",
    "format_items_for_slack",
    "format_items_for_email",
    "generate_dedupe_key",
    "SavedSearchRunner",
    "run_saved_search",
]
