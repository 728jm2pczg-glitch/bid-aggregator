"""
データベース管理モジュール

SQLiteデータベースの初期化、マイグレーション、CRUD操作を提供する。
"""

import hashlib
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from bid_aggregator.core.config import settings
from bid_aggregator.core.models import Item, RawFetch


# =============================================================================
# DDL（テーブル定義）
# =============================================================================

DDL_STATEMENTS = """
-- raw_fetch: 生データ保存
CREATE TABLE IF NOT EXISTS raw_fetch (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    http_status INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    raw_hash TEXT NOT NULL,
    raw_payload BLOB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_fetch_source ON raw_fetch(source);
CREATE INDEX IF NOT EXISTS idx_raw_fetch_fetched_at ON raw_fetch(fetched_at);
CREATE INDEX IF NOT EXISTS idx_raw_fetch_raw_hash ON raw_fetch(raw_hash);

-- items: 正規化案件データ
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_item_id TEXT,
    url TEXT,
    title TEXT NOT NULL,
    organization_name TEXT NOT NULL,
    published_at TEXT,
    deadline_at TEXT,
    category TEXT,
    region TEXT,
    body TEXT,
    body_hash TEXT,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_items_source_item 
    ON items(source, source_item_id) WHERE source_item_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_items_url 
    ON items(url) WHERE url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_items_content_hash ON items(content_hash);
CREATE INDEX IF NOT EXISTS idx_items_published_at ON items(published_at);
CREATE INDEX IF NOT EXISTS idx_items_deadline_at ON items(deadline_at);
CREATE INDEX IF NOT EXISTS idx_items_organization_name ON items(organization_name);

-- saved_searches: 保存検索
CREATE TABLE IF NOT EXISTS saved_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    filters_json TEXT NOT NULL,
    query_ref TEXT,
    order_by TEXT DEFAULT 'newest',
    schedule TEXT,
    only_new INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run_at TEXT,
    last_hit_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- saved_search_runs: 保存検索実行履歴
CREATE TABLE IF NOT EXISTS saved_search_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    saved_search_id INTEGER NOT NULL,
    query_ref TEXT,
    filters_snapshot TEXT,
    run_at TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error_message TEXT,
    notified_channels TEXT,
    notify_status TEXT,
    notify_error TEXT,
    FOREIGN KEY (saved_search_id) REFERENCES saved_searches(id)
);

CREATE INDEX IF NOT EXISTS idx_ssr_saved_search_id ON saved_search_runs(saved_search_id);
CREATE INDEX IF NOT EXISTS idx_ssr_run_at ON saved_search_runs(run_at);

-- saved_search_hits: 保存検索ヒット結果
CREATE TABLE IF NOT EXISTS saved_search_hits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    saved_search_run_id INTEGER NOT NULL,
    item_id INTEGER,
    content_hash TEXT,
    matched_at TEXT NOT NULL,
    notified_at TEXT,
    FOREIGN KEY (saved_search_run_id) REFERENCES saved_search_runs(id),
    FOREIGN KEY (item_id) REFERENCES items(id)
);

CREATE INDEX IF NOT EXISTS idx_ssh_run_id ON saved_search_hits(saved_search_run_id);
CREATE INDEX IF NOT EXISTS idx_ssh_item_id ON saved_search_hits(item_id);
CREATE INDEX IF NOT EXISTS idx_ssh_notified_at ON saved_search_hits(notified_at);

-- saved_search_notifications: 通知送信履歴
CREATE TABLE IF NOT EXISTS saved_search_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    saved_search_run_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    recipient TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT NOT NULL,
    error_message TEXT,
    dedupe_key TEXT NOT NULL UNIQUE,
    FOREIGN KEY (saved_search_run_id) REFERENCES saved_search_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_ssn_run_id ON saved_search_notifications(saved_search_run_id);
CREATE INDEX IF NOT EXISTS idx_ssn_channel ON saved_search_notifications(channel);
CREATE INDEX IF NOT EXISTS idx_ssn_status ON saved_search_notifications(status);
"""


# =============================================================================
# データベース接続
# =============================================================================


def get_db_path() -> Path:
    """データベースファイルのパスを取得"""
    url = settings.database_url
    if url.startswith("sqlite:///"):
        path = Path(url.replace("sqlite:///", ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    raise ValueError(f"Unsupported database URL: {url}")


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """データベース接続を取得（コンテキストマネージャ）"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """データベースを初期化（テーブル作成）"""
    with get_connection() as conn:
        conn.executescript(DDL_STATEMENTS)
        conn.commit()


def get_db_stats() -> dict:
    """データベースの統計情報を取得"""
    with get_connection() as conn:
        stats = {}
        for table in ["raw_fetch", "items", "saved_searches", "saved_search_runs"]:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            stats[table] = cursor.fetchone()[0]
        return stats


# =============================================================================
# ハッシュ生成
# =============================================================================


def normalize_string(s: str | None) -> str:
    """文字列を正規化（NFKC、空白正規化、トリム）"""
    if s is None:
        return ""
    # NFKC正規化
    s = unicodedata.normalize("NFKC", s)
    # 連続する空白・改行を1つに
    s = " ".join(s.split())
    # 前後トリム
    return s.strip()


def escape_pipe(s: str) -> str:
    """パイプ文字をエスケープ"""
    return s.replace("\\", "\\\\").replace("|", "\\|")


def generate_content_hash(
    title: str,
    organization_name: str,
    published_at: str | None,
    deadline_at: str | None,
    url: str | None,
    source_item_id: str | None = None,
) -> str:
    """content_hashを生成"""
    parts = []
    if source_item_id:
        parts.append(escape_pipe(normalize_string(source_item_id)))
    parts.extend([
        escape_pipe(normalize_string(title)),
        escape_pipe(normalize_string(organization_name)),
        escape_pipe(normalize_string(published_at)),
        escape_pipe(normalize_string(deadline_at)),
        escape_pipe(normalize_string(url)),
    ])
    content = "|".join(parts)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def generate_body_hash(body: str | None) -> str | None:
    """body_hashを生成"""
    if not body:
        return None
    normalized = normalize_string(body)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def generate_raw_hash(payload: bytes) -> str:
    """raw_hashを生成"""
    return hashlib.sha256(payload).hexdigest()


def generate_request_fingerprint(source: str, params: dict) -> str:
    """request_fingerprintを生成"""
    # パラメータをキー昇順でソート、空値除外
    sorted_params = sorted(
        ((k, v) for k, v in params.items() if v),
        key=lambda x: x[0],
    )
    param_str = "&".join(f"{k}={v}" for k, v in sorted_params)
    content = f"{source}:{param_str}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# =============================================================================
# CRUD操作: raw_fetch
# =============================================================================


def save_raw_fetch(raw: RawFetch) -> int:
    """生データを保存"""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO raw_fetch 
            (source, fetched_at, request_fingerprint, http_status, content_type, raw_hash, raw_payload)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                raw.source,
                raw.fetched_at.isoformat(),
                raw.request_fingerprint,
                raw.http_status,
                raw.content_type,
                raw.raw_hash,
                raw.raw_payload,
            ),
        )
        conn.commit()
        return cursor.lastrowid or 0


# =============================================================================
# CRUD操作: items
# =============================================================================


def _now_utc() -> str:
    """現在時刻をUTC ISO8601形式で取得"""
    return datetime.now(timezone.utc).isoformat()


def upsert_item(item: Item) -> tuple[int, bool]:
    """
    案件をupsert（挿入または更新）
    
    Returns:
        (item_id, is_new): IDと新規挿入かどうか
    """
    with get_connection() as conn:
        now = _now_utc()
        
        # 既存レコードを検索（優先順: source_item_id → url → content_hash）
        existing_id = None
        
        if item.source_item_id:
            cursor = conn.execute(
                "SELECT id FROM items WHERE source = ? AND source_item_id = ?",
                (item.source, item.source_item_id),
            )
            row = cursor.fetchone()
            if row:
                existing_id = row["id"]
        
        if existing_id is None and item.url:
            cursor = conn.execute(
                "SELECT id FROM items WHERE url = ?",
                (item.url,),
            )
            row = cursor.fetchone()
            if row:
                existing_id = row["id"]
        
        if existing_id is None:
            cursor = conn.execute(
                "SELECT id FROM items WHERE content_hash = ?",
                (item.content_hash,),
            )
            row = cursor.fetchone()
            if row:
                existing_id = row["id"]
        
        if existing_id:
            # 更新
            conn.execute(
                """
                UPDATE items SET
                    source_item_id = ?,
                    url = ?,
                    title = ?,
                    organization_name = ?,
                    published_at = ?,
                    deadline_at = ?,
                    category = ?,
                    region = ?,
                    body = ?,
                    body_hash = ?,
                    content_hash = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    item.source_item_id,
                    item.url,
                    item.title,
                    item.organization_name,
                    item.published_at.isoformat() if item.published_at else None,
                    item.deadline_at.isoformat() if item.deadline_at else None,
                    item.category,
                    item.region,
                    item.body,
                    item.body_hash,
                    item.content_hash,
                    now,
                    existing_id,
                ),
            )
            conn.commit()
            return existing_id, False
        else:
            # 新規挿入
            cursor = conn.execute(
                """
                INSERT INTO items 
                (source, source_item_id, url, title, organization_name, 
                 published_at, deadline_at, category, region, body, body_hash, 
                 content_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.source,
                    item.source_item_id,
                    item.url,
                    item.title,
                    item.organization_name,
                    item.published_at.isoformat() if item.published_at else None,
                    item.deadline_at.isoformat() if item.deadline_at else None,
                    item.category,
                    item.region,
                    item.body,
                    item.body_hash,
                    item.content_hash,
                    now,
                    now,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0, True


def search_items(
    keyword: str = "",
    from_date: str | None = None,
    to_date: str | None = None,
    org: str = "",
    source: str = "",
    order_by: str = "newest",
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Item], int]:
    """
    案件を検索
    
    Returns:
        (items, total_count): 検索結果とヒット総数
    """
    with get_connection() as conn:
        # WHERE句の構築
        conditions = []
        params: list = []
        
        if keyword:
            conditions.append("(title LIKE ? OR body LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        
        if from_date:
            conditions.append("published_at >= ?")
            params.append(from_date)
        
        if to_date:
            conditions.append("published_at <= ?")
            params.append(to_date)
        
        if org:
            conditions.append("organization_name LIKE ?")
            params.append(f"%{org}%")
        
        if source and source != "all":
            conditions.append("source = ?")
            params.append(source)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        # ORDER BY句
        if order_by == "deadline":
            order_clause = "CASE WHEN deadline_at IS NULL THEN 1 ELSE 0 END, deadline_at ASC"
        else:  # newest
            order_clause = "COALESCE(published_at, created_at) DESC"
        
        # 総件数を取得
        count_sql = f"SELECT COUNT(*) FROM items WHERE {where_clause}"  # noqa: S608
        cursor = conn.execute(count_sql, params)
        total_count = cursor.fetchone()[0]
        
        # 結果を取得
        query_sql = f"""
            SELECT * FROM items 
            WHERE {where_clause} 
            ORDER BY {order_clause}
            LIMIT ? OFFSET ?
        """  # noqa: S608
        cursor = conn.execute(query_sql, params + [limit, offset])
        rows = cursor.fetchall()
        
        items = []
        for row in rows:
            items.append(Item(
                id=row["id"],
                source=row["source"],
                source_item_id=row["source_item_id"],
                url=row["url"],
                title=row["title"],
                organization_name=row["organization_name"],
                published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
                deadline_at=datetime.fromisoformat(row["deadline_at"]) if row["deadline_at"] else None,
                category=row["category"],
                region=row["region"],
                body=row["body"],
                body_hash=row["body_hash"],
                content_hash=row["content_hash"],
                created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
                updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            ))
        
        return items, total_count
