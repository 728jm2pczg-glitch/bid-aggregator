"""
保存検索実行モジュール

保存検索を実行し、新規ヒットを検出して通知を送信する。
"""

import json
import logging
from datetime import datetime

from bid_aggregator.core.database import search_items
from bid_aggregator.core.models import Item
from bid_aggregator.core.saved_search_db import (
    create_notification,
    create_saved_search_hit,
    create_saved_search_run,
    get_previous_hit_item_ids,
    get_saved_search,
    mark_hits_notified,
    update_saved_search_last_run,
    update_saved_search_run,
)
from bid_aggregator.notify.sender import NotificationError, generate_dedupe_key, send_notification

logger = logging.getLogger(__name__)


class SavedSearchRunner:
    """保存検索実行クラス"""
    
    def __init__(
        self,
        saved_search: dict,
        notify_config: dict | None = None,
        max_notify_items: int = 100,
    ):
        self.saved_search = saved_search
        self.notify_config = notify_config
        self.max_notify_items = max_notify_items
    
    def run(self, notify: bool = True, dry_run: bool = False) -> dict:
        """
        保存検索を実行
        
        Returns:
            実行結果の辞書
        """
        saved_search_id = self.saved_search["id"]
        name = self.saved_search["name"]
        filters = json.loads(self.saved_search["filters_json"])
        only_new = bool(self.saved_search["only_new"])
        order_by = self.saved_search.get("order_by", "newest")
        
        logger.info(f"保存検索実行: {name}")
        
        # 実行履歴を作成
        run_id = 0
        if not dry_run:
            run_id = create_saved_search_run(
                saved_search_id=saved_search_id,
                query_ref=self.saved_search.get("query_ref"),
                filters_snapshot=filters,
            )
        
        try:
            # 検索実行
            items, total = search_items(
                keyword=filters.get("keyword", ""),
                from_date=filters.get("from"),
                to_date=filters.get("to"),
                org=filters.get("org", ""),
                source=filters.get("source", ""),
                order_by=order_by,
                limit=1000,  # 最大取得
                offset=0,
            )
            
            logger.info(f"検索結果: {total}件 (取得: {len(items)}件)")
            
            # 差分抽出（only_new=True の場合）
            new_items = items
            if only_new and not dry_run:
                previous_ids = get_previous_hit_item_ids(saved_search_id)
                new_items = [item for item in items if item.id not in previous_ids]
                logger.info(f"新規アイテム: {len(new_items)}件 (既存: {len(previous_ids)}件)")
            
            # ヒット結果を保存
            if not dry_run:
                for item in new_items:
                    create_saved_search_hit(
                        run_id=run_id,
                        item_id=item.id or 0,
                        content_hash=item.content_hash,
                    )
            
            # 通知
            notify_status = None
            notify_error = None
            notified_channels = []
            
            if notify and new_items and self.notify_config and self.notify_config.get("enabled"):
                notify_status, notify_error, notified_channels = self._send_notifications(
                    run_id=run_id,
                    saved_search_id=saved_search_id,
                    items=new_items,
                    name=name,
                    dry_run=dry_run,
                )
            
            # 実行履歴を更新
            if not dry_run:
                update_saved_search_run(
                    run_id=run_id,
                    hit_count=len(new_items),
                    status="ok",
                    notified_channels=notified_channels if notified_channels else None,
                    notify_status=notify_status,
                    notify_error=notify_error,
                )
                update_saved_search_last_run(
                    saved_search_id=saved_search_id,
                    last_run_at=datetime.now().isoformat(),
                )
            
            return {
                "name": name,
                "total": total,
                "new": len(new_items),
                "notified": len(notified_channels) > 0,
                "notify_status": notify_status,
                "status": "ok",
            }
            
        except Exception as e:
            logger.error(f"保存検索エラー: {name}, {e}")
            
            if not dry_run and run_id:
                update_saved_search_run(
                    run_id=run_id,
                    hit_count=0,
                    status="failed",
                    error_message=str(e),
                )
            
            return {
                "name": name,
                "total": 0,
                "new": 0,
                "notified": False,
                "status": "failed",
                "error": str(e),
            }
    
    def _send_notifications(
        self,
        run_id: int,
        saved_search_id: int,
        items: list[Item],
        name: str,
        dry_run: bool,
    ) -> tuple[str, str | None, list[str]]:
        """通知を送信"""
        channel = self.notify_config.get("channel", "slack")
        recipients = self.notify_config.get("recipients", [])
        max_items = self.notify_config.get("max_items", self.max_notify_items)
        
        if not recipients:
            return None, "通知先が設定されていません", []
        
        # 通知件数を制限
        notify_items = items[:max_items]
        
        notified_channels = []
        errors = []
        
        for recipient in recipients:
            dedupe_key = generate_dedupe_key(saved_search_id, run_id, channel, recipient)
            
            if dry_run:
                logger.info(f"[ドライラン] 通知スキップ: {channel} -> {recipient}, {len(notify_items)}件")
                notified_channels.append(f"{channel}:{recipient}")
                continue
            
            try:
                send_notification(
                    channel=channel,
                    recipient=recipient,
                    items=notify_items,
                    saved_search_name=name,
                    max_items=max_items,
                )
                
                create_notification(
                    run_id=run_id,
                    channel=channel,
                    recipient=recipient,
                    status="ok",
                    dedupe_key=dedupe_key,
                )
                
                notified_channels.append(f"{channel}:{recipient}")
                
            except NotificationError as e:
                logger.error(f"通知エラー: {channel} -> {recipient}, {e}")
                errors.append(str(e))
                
                create_notification(
                    run_id=run_id,
                    channel=channel,
                    recipient=recipient,
                    status="failed",
                    dedupe_key=dedupe_key,
                    error_message=str(e),
                )
        
        # ヒット結果を通知済みにマーク
        if notified_channels and not dry_run:
            mark_hits_notified(run_id)
        
        if errors:
            return "partial" if notified_channels else "failed", "; ".join(errors), notified_channels
        
        return "ok", None, notified_channels


def run_saved_search(
    name: str,
    notify: bool = True,
    notify_config: dict | None = None,
    max_notify_items: int = 100,
    dry_run: bool = False,
) -> dict:
    """
    保存検索を名前で実行
    """
    saved_search = get_saved_search(name)
    if saved_search is None:
        raise ValueError(f"保存検索が見つかりません: {name}")
    
    runner = SavedSearchRunner(
        saved_search=saved_search,
        notify_config=notify_config,
        max_notify_items=max_notify_items,
    )
    
    return runner.run(notify=notify, dry_run=dry_run)
