"""
調達ポータル落札実績CSV取り込み

オープンデータとして公開されている落札実績CSVを取り込む。
https://www.p-portal.go.jp/pps-web-biz/UAB02/OAB0201
"""

import csv
import io
import logging
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Generator

import httpx

logger = logging.getLogger(__name__)


# CSVカラム定義（ヘッダーなし）
CSV_COLUMNS = [
    "case_number",      # 0: 調達案件番号
    "title",            # 1: 案件名称
    "award_date",       # 2: 落札日 (YYYY-MM-DD)
    "award_amount",     # 3: 落札金額
    "procurement_type", # 4: 調達種別コード
    "org_code",         # 5: 機関コード
    "winner_name",      # 6: 落札者名
    "corporate_number", # 7: 法人番号
]


@dataclass
class AwardRecord:
    """落札実績レコード"""
    case_number: str          # 調達案件番号
    title: str                # 案件名称
    award_date: str           # 落札日 (YYYY-MM-DD)
    award_amount: float       # 落札金額
    procurement_type: str     # 調達種別コード
    org_code: str             # 機関コード
    winner_name: str          # 落札者名
    corporate_number: str     # 法人番号
    
    def to_dict(self) -> dict:
        return {
            "case_number": self.case_number,
            "title": self.title,
            "award_date": self.award_date,
            "award_amount": self.award_amount,
            "procurement_type": self.procurement_type,
            "org_code": self.org_code,
            "winner_name": self.winner_name,
            "corporate_number": self.corporate_number,
        }


class PPortalAwardClient:
    """調達ポータル落札実績クライアント"""
    
    BASE_URL = "https://api.p-portal.go.jp/pps-web-biz/UAB03/OAB0301"
    LIST_URL = "https://www.p-portal.go.jp/pps-web-biz/UAB02/OAB0201"
    
    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self._client: httpx.Client | None = None
    
    def __enter__(self) -> "PPortalAwardClient":
        self._client = httpx.Client(timeout=self.timeout, follow_redirects=True)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client:
            self._client.close()
            self._client = None
    
    def _get_download_url(self, filename: str) -> str:
        """ダウンロードURLを生成"""
        return f"{self.BASE_URL}?fileversion=v001&filename={filename}"
    
    def download_diff(self, date: str) -> list[AwardRecord]:
        """
        差分ファイルをダウンロード
        
        Args:
            date: 日付 (YYYYMMDD形式)
        
        Returns:
            落札実績レコードのリスト
        """
        filename = f"successful_bid_record_info_diff_{date}.zip"
        return self._download_and_parse(filename)
    
    def download_yearly(self, year: int) -> list[AwardRecord]:
        """
        年度別全件ファイルをダウンロード
        
        Args:
            year: 西暦年度 (例: 2024)
        
        Returns:
            落札実績レコードのリスト
        """
        filename = f"successful_bid_record_info_all_{year}.zip"
        return self._download_and_parse(filename)
    
    def _download_and_parse(self, filename: str) -> list[AwardRecord]:
        """ZIPをダウンロードしてCSVをパース"""
        url = self._get_download_url(filename)
        logger.info(f"落札実績ダウンロード: {filename}")
        
        response = self._client.get(url)
        
        if response.status_code != 200:
            logger.error(f"ダウンロードエラー: {response.status_code}")
            return []
        
        return self._parse_zip(response.content)
    
    def _parse_zip(self, content: bytes) -> list[AwardRecord]:
        """ZIPファイルを解凍してCSVをパース"""
        records = []
        
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                csv_files = [n for n in zf.namelist() if n.endswith('.csv')]
                
                for csv_name in csv_files:
                    with zf.open(csv_name) as f:
                        csv_content = f.read().decode('utf-8-sig')
                        records.extend(self._parse_csv(csv_content))
        
        except zipfile.BadZipFile as e:
            logger.error(f"ZIPファイル解凍エラー: {e}")
        
        return records
    
    def _parse_csv(self, content: str) -> list[AwardRecord]:
        """CSVをパース"""
        records = []
        reader = csv.reader(io.StringIO(content))
        
        for row in reader:
            if len(row) < 8:
                continue
            
            try:
                record = AwardRecord(
                    case_number=row[0],
                    title=row[1],
                    award_date=row[2],
                    award_amount=float(row[3]) if row[3] else 0.0,
                    procurement_type=row[4],
                    org_code=row[5],
                    winner_name=row[6],
                    corporate_number=row[7] if len(row) > 7 else "",
                )
                records.append(record)
            except (ValueError, IndexError) as e:
                logger.warning(f"行パースエラー: {row}, {e}")
        
        logger.info(f"落札実績パース完了: {len(records)}件")
        return records
    
    def list_available_files(self) -> dict:
        """
        利用可能なファイル一覧を取得
        
        Returns:
            {"yearly": [...], "diff": [...]}
        """
        from bs4 import BeautifulSoup
        
        response = self._client.get(self.LIST_URL)
        if response.status_code != 200:
            return {"yearly": [], "diff": []}
        
        soup = BeautifulSoup(response.text, "html.parser")
        tables = soup.select("table")
        
        result = {"yearly": [], "diff": []}
        
        # 全件データ（テーブル0）
        if len(tables) > 0:
            for row in tables[0].select("tr")[1:]:
                cells = row.select("td")
                if len(cells) >= 2:
                    link = cells[1].select_one("a")
                    if link:
                        onclick = link.get("onclick", "")
                        # doDownload('filename.zip') からファイル名を抽出
                        import re
                        match = re.search(r"doDownload\('([^']+)'\)", onclick)
                        if match:
                            result["yearly"].append(match.group(1))
        
        # 差分データ（テーブル1）
        if len(tables) > 1:
            for row in tables[1].select("tr")[1:]:
                cells = row.select("td")
                if len(cells) >= 2:
                    link = cells[1].select_one("a")
                    if link:
                        onclick = link.get("onclick", "")
                        import re
                        match = re.search(r"doDownload\('([^']+)'\)", onclick)
                        if match:
                            result["diff"].append(match.group(1))
        
        return result


def fetch_recent_awards(days: int = 7) -> Generator[AwardRecord, None, None]:
    """
    最近の落札実績を取得
    
    Args:
        days: 過去何日分
    
    Yields:
        AwardRecord
    """
    from datetime import timedelta
    
    with PPortalAwardClient() as client:
        # 利用可能なファイルを取得
        files = client.list_available_files()
        
        # 最新のdays日分を取得
        for filename in files["diff"][:days]:
            # ファイル名から日付を抽出
            # successful_bid_record_info_diff_20260131.zip
            import re
            match = re.search(r"diff_(\d{8})\.zip", filename)
            if match:
                date = match.group(1)
                records = client.download_diff(date)
                for record in records:
                    yield record


if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    
    print("=== 落札実績オープンデータ取得テスト ===\n")
    
    with PPortalAwardClient() as client:
        # 利用可能なファイル一覧
        files = client.list_available_files()
        print(f"全件ファイル: {len(files['yearly'])}件")
        for f in files['yearly'][:3]:
            print(f"  {f}")
        
        print(f"\n差分ファイル: {len(files['diff'])}件")
        for f in files['diff'][:5]:
            print(f"  {f}")
        
        # 最新の差分をダウンロード
        if files['diff']:
            print(f"\n=== 最新差分ファイルの内容 ===")
            # ファイル名から日付を抽出
            import re
            match = re.search(r"diff_(\d{8})\.zip", files['diff'][0])
            if match:
                date = match.group(1)
                records = client.download_diff(date)
                
                print(f"レコード数: {len(records)}")
                for r in records[:5]:
                    print(f"\n案件番号: {r.case_number}")
                    print(f"  案件名: {r.title[:50]}...")
                    print(f"  落札日: {r.award_date}")
                    print(f"  落札金額: {r.award_amount:,.0f}円")
                    print(f"  落札者: {r.winner_name}")
