"""
正規化モジュール

KKJ APIレスポンスを共通スキーマ（Item）に変換する。
"""

import logging
from datetime import datetime

from bid_aggregator.core.database import generate_body_hash, generate_content_hash
from bid_aggregator.core.models import Item, KKJSearchResult

logger = logging.getLogger(__name__)


class NormalizationError(Exception):
    """正規化エラー"""

    def __init__(self, message: str, source_key: str | None = None):
        super().__init__(message)
        self.source_key = source_key


def parse_iso8601_date(date_str: str | None) -> datetime | None:
    """
    ISO8601形式の日付文字列をパース
    
    KKJ APIは ISO8601 形式（例: 2025-01-30T09:00:00+09:00）を返す
    """
    if not date_str:
        return None
    
    try:
        # Python 3.11+ では fromisoformat が拡張形式をサポート
        return datetime.fromisoformat(date_str)
    except ValueError:
        # 日付のみの場合
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            logger.warning(f"日付パース失敗: {date_str}")
            return None


def normalize_kkj_result(result: KKJSearchResult, source: str = "kkj") -> Item:
    """
    KKJ検索結果を正規化してItemに変換
    
    Raises:
        NormalizationError: 必須フィールドが欠落している場合
    """
    # 必須フィールドのバリデーション
    if not result.project_name:
        raise NormalizationError(
            "project_name（件名）が空です",
            source_key=result.key,
        )
    
    # organization_name は空の場合がある（オプション）
    organization_name = result.organization_name or "不明"
    
    # 日付のパース
    published_at = parse_iso8601_date(result.cft_issue_date)
    deadline_at = parse_iso8601_date(result.period_end_time)
    
    # 地域の構築
    region_parts = []
    if result.prefecture_name:
        region_parts.append(result.prefecture_name)
    if result.city_name:
        region_parts.append(result.city_name)
    region = " ".join(region_parts) if region_parts else None
    
    # ハッシュ生成
    content_hash = generate_content_hash(
        title=result.project_name,
        organization_name=organization_name,
        published_at=result.cft_issue_date,
        deadline_at=result.period_end_time,
        url=result.external_document_uri,
        source_item_id=result.key,
    )
    
    body_hash = generate_body_hash(result.project_description)
    
    return Item(
        source=source,
        source_item_id=result.key,
        url=result.external_document_uri,
        title=result.project_name,
        organization_name=organization_name,
        published_at=published_at,
        deadline_at=deadline_at,
        category=result.category,
        region=region,
        body=result.project_description,
        body_hash=body_hash,
        content_hash=content_hash,
    )


def normalize_kkj_results(
    results: list[KKJSearchResult],
    source: str = "kkj",
) -> tuple[list[Item], list[tuple[KKJSearchResult, Exception]]]:
    """
    複数のKKJ検索結果を正規化
    
    Returns:
        (normalized_items, errors): 正規化成功したItemリストとエラーリスト
    """
    items = []
    errors = []
    
    for result in results:
        try:
            item = normalize_kkj_result(result, source)
            items.append(item)
        except Exception as e:
            logger.warning(f"正規化エラー: key={result.key}, error={e}")
            errors.append((result, e))
    
    return items, errors
