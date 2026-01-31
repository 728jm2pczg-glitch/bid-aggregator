"""
データモデル定義

入札情報の共通スキーマとYAML設定のモデルを定義する。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# =============================================================================
# 入札情報モデル
# =============================================================================


class RawFetch(BaseModel):
    """生データ保存モデル"""

    id: int | None = None
    source: str
    fetched_at: datetime
    request_fingerprint: str
    http_status: int
    content_type: str
    raw_hash: str
    raw_payload: bytes


class Item(BaseModel):
    """正規化された入札案件モデル"""

    id: int | None = None
    source: str
    source_item_id: str | None = None
    url: str | None = None
    title: str
    organization_name: str
    published_at: datetime | None = None
    deadline_at: datetime | None = None
    category: str | None = None
    region: str | None = None
    body: str | None = None
    body_hash: str | None = None
    content_hash: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SearchResult(BaseModel):
    """検索結果モデル"""

    items: list[Item]
    total_count: int
    offset: int
    limit: int


# =============================================================================
# queries.yml 設定モデル
# =============================================================================


class QueryParams(BaseModel):
    """KKJ APIパラメータ"""

    Query: str = ""
    Project_Name: str = ""
    Organization_Name: str = ""
    LG_Code: str = ""
    Count: int = Field(default=1000, le=1000)
    Category: int | None = None
    Procedure_Type: int | None = None
    Certification: str | None = None
    CFT_Issue_Date: str | None = None
    Tender_Submission_Deadline: str | None = None
    Opening_Tenders_Event: str | None = None
    Period_End_Time: str | None = None


class DateRange(BaseModel):
    """日付範囲"""

    from_: str | None = Field(default=None, alias="from")
    to: str | None = None


class QueryConfig(BaseModel):
    """取得クエリ定義"""

    name: str
    source: Literal["kkj"] = "kkj"
    params: QueryParams = Field(default_factory=QueryParams)
    date_range: DateRange | None = None
    limit: int = Field(default=1000, le=1000)
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)


class SearchFilters(BaseModel):
    """検索フィルタ"""

    keyword: str = ""
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    org: str = ""
    source: str = ""
    limit: int = 100
    offset: int = 0


class SavedSearchConfig(BaseModel):
    """保存検索定義"""

    name: str
    query_ref: str
    filters: SearchFilters = Field(default_factory=SearchFilters)
    order_by: Literal["newest", "deadline"] = "newest"
    schedule: Literal["daily", "hourly"] | None = None
    only_new: bool = True
    enabled: bool = True


class NotifyConfig(BaseModel):
    """通知設定"""

    channel: Literal["slack", "email"]
    recipients: list[str]
    template: str = "default"
    max_items: int = 100
    enabled: bool = True


class QueriesConfig(BaseModel):
    """queries.yml全体の設定"""

    version: int = 1
    queries: list[QueryConfig] = Field(default_factory=list)
    saved_searches: list[SavedSearchConfig] = Field(default_factory=list)
    notify: NotifyConfig | None = None


# =============================================================================
# KKJ APIレスポンスモデル
# =============================================================================


class KKJAttachment(BaseModel):
    """KKJ添付ファイル"""

    name: str | None = None
    uri: str | None = None


class KKJSearchResult(BaseModel):
    """KKJ検索結果1件"""

    result_id: int
    key: str
    external_document_uri: str | None = None
    project_name: str
    date: str | None = None
    file_type: str | None = None
    file_size: int | None = None
    lg_code: str | None = None
    prefecture_name: str | None = None
    city_code: str | None = None
    city_name: str | None = None
    organization_name: str | None = None
    certification: str | None = None
    cft_issue_date: str | None = None
    period_end_time: str | None = None
    category: str | None = None
    procedure_type: str | None = None
    location: str | None = None
    tender_submission_deadline: str | None = None
    opening_tenders_event: str | None = None
    item_code: str | None = None
    project_description: str | None = None
    attachments: list[KKJAttachment] = Field(default_factory=list)


class KKJAPIResponse(BaseModel):
    """KKJ APIレスポンス"""

    version: str
    search_hits: int
    results: list[KKJSearchResult] = Field(default_factory=list)
    error: str | None = None
