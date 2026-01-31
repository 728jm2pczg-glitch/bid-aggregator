"""
全件取得パイプライン

日付範囲を分割して1000件以上のデータを取得する。
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Generator

from bid_aggregator.core.database import (
    generate_raw_hash,
    generate_request_fingerprint,
    save_raw_fetch,
    upsert_item,
)
from bid_aggregator.core.models import QueryConfig, QueryParams, RawFetch
from bid_aggregator.ingest.kkj_client import KKJClient
from bid_aggregator.ingest.normalizer import normalize_kkj_results

logger = logging.getLogger(__name__)


def date_range_generator(
    start_date: str,
    end_date: str,
    days_per_chunk: int = 7,
) -> Generator[tuple[str, str], None, None]:
    """
    日付範囲を分割して返すジェネレータ
    
    Args:
        start_date: 開始日 (YYYY-MM-DD)
        end_date: 終了日 (YYYY-MM-DD)
        days_per_chunk: 1チャンクの日数（デフォルト7日）
    
    Yields:
        (chunk_start, chunk_end) のタプル
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=days_per_chunk - 1), end)
        yield current.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")
        current = chunk_end + timedelta(days=1)


class FullIngestResult:
    """全件取得結果"""
    
    def __init__(self):
        self.total_fetched: int = 0
        self.total_new: int = 0
        self.total_updated: int = 0
        self.total_errors: int = 0
        self.total_api_hits: int = 0  # APIが返したヒット総数
        self.chunks_processed: int = 0
        self.chunk_results: list[dict] = []
    
    def add_chunk_result(
        self,
        from_date: str,
        to_date: str,
        api_hits: int,
        fetched: int,
        new: int,
        updated: int,
        errors: int,
    ) -> None:
        self.total_api_hits = max(self.total_api_hits, api_hits)  # 最大値を保持
        self.total_fetched += fetched
        self.total_new += new
        self.total_updated += updated
        self.total_errors += errors
        self.chunks_processed += 1
        self.chunk_results.append({
            "from": from_date,
            "to": to_date,
            "api_hits": api_hits,
            "fetched": fetched,
            "new": new,
            "updated": updated,
            "errors": errors,
        })
    
    def summary(self) -> str:
        return (
            f"チャンク: {self.chunks_processed}個, "
            f"取得: {self.total_fetched}件, "
            f"新規: {self.total_new}件, "
            f"更新: {self.total_updated}件, "
            f"エラー: {self.total_errors}件"
        )


def run_full_ingest(
    query: QueryConfig,
    start_date: str,
    end_date: str,
    days_per_chunk: int = 7,
    dry_run: bool = False,
) -> FullIngestResult:
    """
    日付範囲を分割して全件取得
    
    Args:
        query: クエリ設定
        start_date: 開始日 (YYYY-MM-DD)
        end_date: 終了日 (YYYY-MM-DD)
        days_per_chunk: 1チャンクの日数（デフォルト7日）
        dry_run: Trueの場合、DBへの保存をスキップ
    
    Returns:
        FullIngestResult: 取得結果
    """
    result = FullIngestResult()
    
    logger.info(f"全件取得開始: {query.name}")
    logger.info(f"期間: {start_date} 〜 {end_date} ({days_per_chunk}日ごと)")
    
    with KKJClient() as client:
        for chunk_start, chunk_end in date_range_generator(start_date, end_date, days_per_chunk):
            try:
                chunk_result = _process_chunk(
                    client=client,
                    query=query,
                    from_date=chunk_start,
                    to_date=chunk_end,
                    dry_run=dry_run,
                )
                
                result.add_chunk_result(
                    from_date=chunk_start,
                    to_date=chunk_end,
                    api_hits=chunk_result["api_hits"],
                    fetched=chunk_result["fetched"],
                    new=chunk_result["new"],
                    updated=chunk_result["updated"],
                    errors=chunk_result["errors"],
                )
                
                logger.info(
                    f"  {chunk_start}〜{chunk_end}: "
                    f"取得={chunk_result['fetched']}, "
                    f"新規={chunk_result['new']}, "
                    f"更新={chunk_result['updated']}"
                )
                
                # 1000件に達した場合は警告（さらに分割が必要な可能性）
                if chunk_result["fetched"] >= 1000:
                    logger.warning(
                        f"  ⚠ チャンク {chunk_start}〜{chunk_end} が1000件に達しました。"
                        f"days_per_chunk を小さくすることを検討してください。"
                    )
                
            except Exception as e:
                logger.error(f"チャンク処理エラー: {chunk_start}〜{chunk_end}, {e}")
                result.add_chunk_result(
                    from_date=chunk_start,
                    to_date=chunk_end,
                    api_hits=0,
                    fetched=0,
                    new=0,
                    updated=0,
                    errors=1,
                )
    
    logger.info(f"全件取得完了: {result.summary()}")
    return result


def _process_chunk(
    client: KKJClient,
    query: QueryConfig,
    from_date: str,
    to_date: str,
    dry_run: bool,
) -> dict:
    """
    1つの日付チャンクを処理
    """
    # パラメータをコピーして日付範囲を設定
    params = query.params.model_copy()
    params.Count = 1000  # 最大取得
    params.CFT_Issue_Date = f"{from_date}/{to_date}"
    
    # API呼び出し
    response, raw_body, status_code, content_type = client.search(params)
    
    # raw保存
    if not dry_run:
        raw_fetch = RawFetch(
            source=query.source,
            fetched_at=datetime.now(timezone.utc),
            request_fingerprint=generate_request_fingerprint(
                query.source,
                params.model_dump(exclude_none=True),
            ),
            http_status=status_code,
            content_type=content_type,
            raw_hash=generate_raw_hash(raw_body),
            raw_payload=raw_body,
        )
        save_raw_fetch(raw_fetch)
    
    # 正規化
    items, normalize_errors = normalize_kkj_results(response.results, query.source)
    
    # DB保存
    new_count = 0
    updated_count = 0
    
    if not dry_run:
        for item in items:
            try:
                item_id, is_new = upsert_item(item)
                if is_new:
                    new_count += 1
                else:
                    updated_count += 1
            except Exception as e:
                logger.error(f"DB保存エラー: {e}")
    else:
        new_count = len(items)
    
    return {
        "api_hits": response.search_hits,
        "fetched": len(response.results),
        "new": new_count,
        "updated": updated_count,
        "errors": len(normalize_errors),
    }


def estimate_chunks(
    start_date: str,
    end_date: str,
    days_per_chunk: int = 7,
) -> int:
    """必要なチャンク数を見積もる"""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    total_days = (end - start).days + 1
    return (total_days + days_per_chunk - 1) // days_per_chunk
