"""
調達ポータル（p-portal.go.jp）クライアント

政府電子調達システム（GEPS）の調達情報を取得する。
HTMLスクレイピングによるデータ取得を行う。

使用方法:
    # 単体テスト
    python -m bid_aggregator.ingest.pportal_client
    
    # または直接実行
    python src/bid_aggregator/ingest/pportal_client.py
"""

import logging
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Generator
from urllib.parse import urljoin, urlencode

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class PPortalSearchResult:
    """調達ポータル検索結果"""
    case_number: str  # 調達案件番号
    title: str  # 案件名称
    organization: str  # 調達機関
    category: str  # 調達種別（入札公告、落札公示等）
    classification: str  # 分類（物品・役務、簡易な公共事業）
    publish_start: str | None  # 公開開始日
    publish_end: str | None  # 公開終了日
    detail_url: str | None  # 詳細URL
    
    def to_dict(self) -> dict:
        """辞書形式に変換"""
        return asdict(self)


class PPortalAPIError(Exception):
    """調達ポータルAPIエラー"""
    pass


class PPortalClient:
    """
    調達ポータルクライアント
    
    HTMLスクレイピングで調達情報を取得する。
    
    注意:
    - レート制限を守ること（デフォルト2秒間隔）
    - サイトの利用規約を確認すること
    """
    
    BASE_URL = "https://www.p-portal.go.jp/pps-web-biz"
    SEARCH_PAGE_URL = f"{BASE_URL}/UAA01/OAA0101"
    # 検索実行URL（フォームのaction先）
    SEARCH_EXEC_URL = f"{BASE_URL}/UAA01/OAA0100"
    
    # 調達種別コード（チェックボックスの値）
    PROCUREMENT_TYPES = {
        # 入札公告・公示予定
        "annual_plan": "01",  # 入札公告(公示)予定の公示(年間調達予定)
        # 資料提供招請
        "rfi": "02",  # 資料提供招請に関する公表
        # 意見招請
        "opinion": "03",  # 意見招請に関する公示
        # 調達実施案件公示
        "bid_wto": "05",  # 一般競争入札の入札公告（WTO対象）
        "bid_designated_wto": "04",  # 指名競争入札の入札公示（WTO対象）
        "negotiated": "07",  # 随意契約に関する公示
        "bid_non_wto": "10",  # 一般競争入札の入札公告（WTO対象外）
        "bid_designated_non_wto": "09",  # 指名競争入札の入札公示（WTO対象外）
        "proposal": "14",  # 公募型プロポーザル情報
        "open_counter": "12",  # オープンカウンタへの参加募集情報
        "open_counter_small": "15",  # オープンカウンタ（少額）への参加募集情報
        # 落札公示
        "award_wto": "06",  # 落札者等の公示（WTO対象）
        "award_non_wto": "11",  # 落札者等の公示（WTO対象外）
        "award_negotiated": "08",  # 落札者等の公示（随意契約）
    }
    
    # 調達機関コード（主要省庁）
    ORGANIZATIONS = {
        "shugiin": "001",  # 衆議院
        "sangiin": "002",  # 参議院
        "courts": "003",  # 最高裁判所
        "audit": "004",  # 会計検査院
        "cabinet": "005",  # 内閣官房
        "npa": "006",  # 人事院
        "cao": "010",  # 内閣府
        "iha": "025",  # 宮内庁
        "npa_police": "008",  # 国家公安委員会（警察庁）
        "mod": "007",  # 防衛省
        "fsa": "026",  # 金融庁
        "mic": "009",  # 総務省
        "moj": "012",  # 法務省
        "mofa": "013",  # 外務省
        "mof": "014",  # 財務省
        "mext": "015",  # 文部科学省
        "mhlw": "016",  # 厚生労働省
        "maff": "017",  # 農林水産省
        "meti": "019",  # 経済産業省
        "mlit": "020",  # 国土交通省
        "env": "021",  # 環境省
        "caa": "022",  # 消費者庁
        "reconstruction": "024",  # 復興庁
        "jftc": "011",  # 公正取引委員会
        "ppc": "023",  # 個人情報保護委員会
        "casino": "028",  # カジノ管理委員会
        "digital": "027",  # デジタル庁
        "cfa": "029",  # こども家庭庁
    }
    
    def __init__(
        self,
        request_interval: float = 2.0,
        timeout: float = 30.0,
    ):
        """
        Args:
            request_interval: リクエスト間隔（秒）
            timeout: タイムアウト（秒）
        """
        self.request_interval = request_interval
        self.timeout = timeout
        self._last_request_time = 0.0
        self._client: httpx.Client | None = None
        self._session_initialized = False
        self._csrf_token = ""
    
    def __enter__(self) -> "PPortalClient":
        self._client = httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
            },
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client:
            self._client.close()
            self._client = None
    
    def _wait_for_rate_limit(self) -> None:
        """レート制限のための待機"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.request_interval:
            time.sleep(self.request_interval - elapsed)
        self._last_request_time = time.time()
    
    def _init_session(self) -> None:
        """セッションを初期化（Cookie・CSRFトークン取得）"""
        if self._session_initialized:
            return
        
        self._wait_for_rate_limit()
        logger.info("調達ポータルセッション初期化中...")
        
        response = self._client.get(self.SEARCH_PAGE_URL)
        
        if response.status_code != 200:
            raise PPortalAPIError(f"セッション初期化失敗: {response.status_code}")
        
        # CSRFトークンを抽出
        soup = BeautifulSoup(response.text, "html.parser")
        csrf_input = soup.select_one("input[name=_csrf]")
        if csrf_input:
            self._csrf_token = csrf_input.get("value", "")
            logger.info(f"CSRFトークン取得: {self._csrf_token[:20]}...")
        else:
            self._csrf_token = ""
            logger.warning("CSRFトークンが見つかりません")
        
        self._session_initialized = True
        logger.info("調達ポータルセッション初期化完了")
    
    def search(
        self,
        keyword: str = "",
        procurement_types: list[str] | None = None,
        organization_codes: list[str] | None = None,
        publish_start_from: str | None = None,
        publish_start_to: str | None = None,
        classification: str = "",  # "1"=物品・役務, "2"=簡易な公共事業, ""=全て
    ) -> tuple[list[PPortalSearchResult], int]:
        """
        調達情報を検索
        
        Args:
            keyword: 検索キーワード（案件名称）
            procurement_types: 調達種別コードのリスト（PROCUREMENT_TYPESの値）
            organization_codes: 調達機関コードのリスト（ORGANIZATIONSの値）
            publish_start_from: 公開開始日（開始）YYYY-MM-DD
            publish_start_to: 公開開始日（終了）YYYY-MM-DD
            classification: 分類
        
        Returns:
            (検索結果リスト, 総件数)
        """
        self._init_session()
        
        # フォームデータを構築
        form_data = self._build_form_data(
            keyword=keyword,
            procurement_types=procurement_types,
            organization_codes=organization_codes,
            publish_start_from=publish_start_from,
            publish_start_to=publish_start_to,
            classification=classification,
        )
        
        self._wait_for_rate_limit()
        
        logger.info(f"調達ポータル検索: keyword='{keyword}'")
        
        # 検索実行（リストをURLエンコード）
        encoded_data = urlencode(form_data)
        
        response = self._client.post(
            self.SEARCH_EXEC_URL,
            content=encoded_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": self.SEARCH_PAGE_URL,
                "Origin": "https://www.p-portal.go.jp",
            },
        )
        
        if response.status_code != 200:
            raise PPortalAPIError(f"検索エラー: {response.status_code}")
        
        # HTMLをパース
        results, total = self._parse_search_results(response.text)
        
        logger.info(f"調達ポータル検索完了: {total}件中 {len(results)}件取得")
        
        return results, total
    
    def _build_form_data(
        self,
        keyword: str,
        procurement_types: list[str] | None,
        organization_codes: list[str] | None,
        publish_start_from: str | None,
        publish_start_to: str | None,
        classification: str,
    ) -> list[tuple[str, str]]:
        """フォームデータを構築（実際のHTMLフォームに合わせた形式）"""
        data = []
        
        # CSRFトークン
        if self._csrf_token:
            data.append(("_csrf", self._csrf_token))
        
        # 案件分類（1=公開中の調達案件）
        data.append(("searchConditionBean.ankenBunrui", "1"))
        
        # 分類
        data.append(("searchConditionBean.bunrui", classification))
        
        # 案件名称
        data.append(("searchConditionBean.ankenMeisho", keyword))
        
        # 検索方法（1=類義語含まない）
        data.append(("searchConditionBean.ankenMeishoKensakuHoho", "1"))
        
        # 案件番号
        data.append(("searchConditionBean.ankenBango", ""))
        
        # 隠しフィールド
        data.append(("searchConditionBean.procurementCla", ""))
        data.append(("searchConditionBean.procurementOrganNm", ""))
        data.append(("searchConditionBean.receiptAddress", ""))
        data.append(("searchConditionBean.procurementItemCla", ""))
        
        # 調達種別
        if procurement_types:
            for pt in procurement_types:
                if pt in ["01", "02"]:
                    data.append(("searchConditionBean.procurementClaBean.procurementClaBidNotice", pt))
                elif pt == "03":
                    data.append(("searchConditionBean.procurementClaBean.requestSubmissionMaterials", pt))
                elif pt == "04":
                    data.append(("searchConditionBean.procurementClaBean.requestComment", pt))
                elif pt in ["05", "06", "07", "10", "12", "13", "14", "99"]:
                    data.append(("searchConditionBean.procurementClaBean.procurementImplementNotice", pt))
                elif pt in ["08", "15", "16"]:
                    data.append(("searchConditionBean.procurementClaBean.successfulBidNotice", pt))
        else:
            data.append(("searchConditionBean.procurementClaBean.procurementImplementNotice", "05"))
            data.append(("searchConditionBean.procurementClaBean.procurementImplementNotice", "10"))
            data.append(("searchConditionBean.procurementClaBean.procurementImplementNotice", "13"))
        
        # 隠しフィールド（チェックボックス用）
        data.append(("_searchConditionBean.procurementClaBean.procurementClaBidNotice", "on"))
        data.append(("_searchConditionBean.procurementClaBean.requestSubmissionMaterials", "on"))
        data.append(("_searchConditionBean.procurementClaBean.requestComment", "on"))
        data.append(("_searchConditionBean.procurementClaBean.procurementImplementNotice", "on"))
        data.append(("_searchConditionBean.procurementClaBean.successfulBidNotice", "on"))
        
        # 調達機関
        if organization_codes:
            for org in organization_codes:
                data.append(("searchConditionBean.govementProcurementOraganBean.procurementOrgNm", org))
        data.append(("_searchConditionBean.govementProcurementOraganBean.procurementOrgNm", "on"))
        
        # 公開開始日
        if publish_start_from:
            data.append(("searchConditionBean.kokaiKaishiYmdFrom", publish_start_from.replace("-", "/")))
        if publish_start_to:
            data.append(("searchConditionBean.kokaiKaishiYmdTo", publish_start_to.replace("-", "/")))
        
        return data
    
    def _parse_search_results(self, html: str) -> tuple[list[PPortalSearchResult], int]:
        """検索結果HTMLをパース"""
        soup = BeautifulSoup(html, "html.parser")
        results = []
        total = 0
        
        # デバッグ: HTMLの一部を出力
        logger.debug(f"HTML length: {len(html)}")
        
        # 総件数を取得（複数のパターンを試す）
        # パターン1: "○○件中"
        count_patterns = [
            r"(\d+)\s*件",
            r"件数[：:]\s*(\d+)",
            r"(\d+)\s*件中",
        ]
        for pattern in count_patterns:
            match = re.search(pattern, html)
            if match:
                total = int(match.group(1))
                logger.debug(f"総件数を検出: {total}")
                break
        
        # 検索結果テーブルをパース（複数のセレクタを試す）
        table_selectors = [
            "table.search-result tbody tr",
            "table.result-table tbody tr",
            "#searchResult tbody tr",
            ".searchResultList tbody tr",
            "table tbody tr",
        ]
        
        rows = []
        for selector in table_selectors:
            rows = soup.select(selector)
            if rows:
                logger.debug(f"セレクタ '{selector}' で {len(rows)} 行を検出")
                break
        
        if not rows:
            # テーブルが見つからない場合、HTMLの構造を調査
            logger.warning("検索結果テーブルが見つかりません")
            # 可能性のあるテーブルを探す
            tables = soup.find_all("table")
            logger.debug(f"ページ内のテーブル数: {len(tables)}")
            for i, table in enumerate(tables):
                rows_in_table = table.find_all("tr")
                logger.debug(f"テーブル{i}: {len(rows_in_table)} 行")
            return results, total
        
        for row in rows:
            try:
                result = self._parse_row(row)
                if result:
                    results.append(result)
            except Exception as e:
                logger.warning(f"行パースエラー: {e}")
                continue
        
        return results, total
    
    def _parse_row(self, row) -> PPortalSearchResult | None:
        """テーブル行をパース"""
        cells = row.find_all("td")
        if len(cells) < 3:
            return None
        
        # 案件番号・リンク
        case_number = ""
        detail_url = ""
        link = row.find("a")
        if link:
            case_number = link.get_text(strip=True)
            href = link.get("href", "")
            if href:
                detail_url = urljoin(self.BASE_URL, href)
        
        # 案件名称（通常2列目）
        title = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        
        # 調達機関（通常3列目）
        organization = cells[2].get_text(strip=True) if len(cells) > 2 else ""
        
        # 調達種別（通常4列目）
        category = cells[3].get_text(strip=True) if len(cells) > 3 else ""
        
        # 公開期間（通常5列目）
        publish_start = None
        publish_end = None
        if len(cells) > 4:
            date_text = cells[4].get_text(strip=True)
            # "2025/01/15 ～ 2025/02/15" のようなフォーマット
            date_match = re.search(r"(\d{4}/\d{2}/\d{2})\s*[～~-]\s*(\d{4}/\d{2}/\d{2})", date_text)
            if date_match:
                publish_start = date_match.group(1).replace("/", "-")
                publish_end = date_match.group(2).replace("/", "-")
        
        if not title:
            return None
        
        return PPortalSearchResult(
            case_number=case_number,
            title=title,
            organization=organization,
            category=category,
            classification="",
            publish_start=publish_start,
            publish_end=publish_end,
            detail_url=detail_url,
        )
    
    def search_all(
        self,
        keyword: str = "",
        procurement_types: list[str] | None = None,
        organization_codes: list[str] | None = None,
        publish_start_from: str | None = None,
        publish_start_to: str | None = None,
        max_pages: int = 10,
    ) -> Generator[PPortalSearchResult, None, None]:
        """
        全ページを取得するジェネレータ
        
        Note: 現時点ではページネーションは未実装（1ページ目のみ）
        """
        results, total = self.search(
            keyword=keyword,
            procurement_types=procurement_types,
            organization_codes=organization_codes,
            publish_start_from=publish_start_from,
            publish_start_to=publish_start_to,
        )
        
        for result in results:
            yield result
        
        logger.info(f"調達ポータル取得完了: {len(results)}件")
    
    def get_raw_html(self, keyword: str = "") -> str:
        """
        デバッグ用: 生のHTMLを取得
        """
        self._init_session()
        
        form_data = self._build_form_data(
            keyword=keyword,
            procurement_types=None,
            organization_codes=None,
            publish_start_from=None,
            publish_start_to=None,
            classification="",
        )
        
        self._wait_for_rate_limit()
        
        # リストをURLエンコード
        encoded_data = urlencode(form_data)
        
        response = self._client.post(
            self.SEARCH_EXEC_URL,
            content=encoded_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": self.SEARCH_PAGE_URL,
                "Origin": "https://www.p-portal.go.jp",
            },
        )
        
        logger.info(f"デバッグ: status={response.status_code}")
        
        return response.text


# =============================================================================
# 直接アクセス用の簡易関数
# =============================================================================


def fetch_pportal_bid_notices(
    keyword: str = "",
    organization: str | None = None,
    days_back: int = 30,
) -> list[PPortalSearchResult]:
    """
    入札公告を取得する簡易関数
    
    Args:
        keyword: 検索キーワード
        organization: 機関コード（例: "meti", "mod"）
        days_back: 過去何日分を取得するか
    
    Returns:
        検索結果リスト
    """
    # 日付範囲
    today = datetime.now()
    start_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")
    
    # 機関コード
    org_codes = None
    if organization and organization in PPortalClient.ORGANIZATIONS:
        org_codes = [PPortalClient.ORGANIZATIONS[organization]]
    
    # 調達種別（入札公告のみ）
    proc_types = [
        PPortalClient.PROCUREMENT_TYPES["bid_wto"],
        PPortalClient.PROCUREMENT_TYPES["bid_non_wto"],
        PPortalClient.PROCUREMENT_TYPES["proposal"],
    ]
    
    with PPortalClient() as client:
        results = list(client.search_all(
            keyword=keyword,
            procurement_types=proc_types,
            organization_codes=org_codes,
            publish_start_from=start_date,
            publish_start_to=end_date,
        ))
    
    return results


def debug_html_structure(keyword: str = "") -> None:
    """
    デバッグ用: HTMLの構造を調査
    """
    print("=" * 60)
    print("調達ポータル HTML構造調査")
    print("=" * 60)
    
    with PPortalClient() as client:
        html = client.get_raw_html(keyword)
    
    print(f"\nHTML長さ: {len(html)} 文字")
    
    # HTMLをファイルに保存
    output_file = "pportal_debug.html"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTMLを {output_file} に保存しました")
    
    # BeautifulSoupで解析
    soup = BeautifulSoup(html, "html.parser")
    
    # テーブルを探す
    tables = soup.find_all("table")
    print(f"\nテーブル数: {len(tables)}")
    
    for i, table in enumerate(tables):
        classes = table.get("class", [])
        table_id = table.get("id", "")
        rows = table.find_all("tr")
        print(f"  テーブル{i}: class={classes}, id={table_id}, 行数={len(rows)}")
        
        # 最初の行の内容を表示
        if rows:
            first_row = rows[0]
            cells = first_row.find_all(["th", "td"])
            cell_texts = [c.get_text(strip=True)[:20] for c in cells[:5]]
            print(f"    最初の行: {cell_texts}")
    
    # フォームを探す
    forms = soup.find_all("form")
    print(f"\nフォーム数: {len(forms)}")
    for i, form in enumerate(forms):
        action = form.get("action", "")
        method = form.get("method", "")
        print(f"  フォーム{i}: action={action}, method={method}")
    
    # 件数表示を探す
    count_patterns = [
        (r"(\d+)\s*件", "件"),
        (r"検索結果", "検索結果"),
    ]
    for pattern, name in count_patterns:
        matches = re.findall(pattern, html)
        if matches:
            print(f"\n'{name}' パターン: {matches[:5]}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="調達ポータルクライアント")
    parser.add_argument("--debug", action="store_true", help="HTML構造を調査")
    parser.add_argument("--keyword", "-k", default="", help="検索キーワード")
    parser.add_argument("--days", "-d", type=int, default=7, help="過去何日分")
    parser.add_argument("--org", "-o", help="機関コード (例: meti, mod)")
    parser.add_argument("--verbose", "-v", action="store_true", help="詳細ログ")
    
    args = parser.parse_args()
    
    # ログ設定
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    
    if args.debug:
        # デバッグモード
        debug_html_structure(args.keyword)
    else:
        # 通常の検索テスト
        print("=" * 60)
        print("調達ポータル検索テスト")
        print("=" * 60)
        print(f"キーワード: '{args.keyword}'")
        print(f"期間: 過去{args.days}日")
        if args.org:
            print(f"機関: {args.org}")
        print()
        
        try:
            results = fetch_pportal_bid_notices(
                keyword=args.keyword,
                organization=args.org,
                days_back=args.days,
            )
            
            print(f"検索結果: {len(results)}件\n")
            
            for i, r in enumerate(results[:10], 1):
                print(f"{i}. {r.title}")
                print(f"   案件番号: {r.case_number}")
                print(f"   機関: {r.organization}")
                print(f"   種別: {r.category}")
                print(f"   公開: {r.publish_start} ～ {r.publish_end}")
                print(f"   URL: {r.detail_url}")
                print()
            
            if len(results) > 10:
                print(f"... 他 {len(results) - 10} 件")
        
        except PPortalAPIError as e:
            print(f"APIエラー: {e}")
        except Exception as e:
            print(f"エラー: {e}")
            import traceback
            traceback.print_exc()
