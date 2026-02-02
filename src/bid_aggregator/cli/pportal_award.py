#!/usr/bin/env python3
"""
調達ポータル落札実績CLI

使用例:
    # 最新の差分を取得
    python -m bid_aggregator.cli.pportal_award --days 7
    
    # 特定日の差分を取得
    python -m bid_aggregator.cli.pportal_award --date 20260131
    
    # 年度全件を取得
    python -m bid_aggregator.cli.pportal_award --year 2024
    
    # 利用可能なファイル一覧
    python -m bid_aggregator.cli.pportal_award --list
"""

import argparse
import csv
import logging
import sys
from datetime import datetime, timedelta

from bid_aggregator.ingest.pportal_award import PPortalAwardClient, AwardRecord


def main():
    parser = argparse.ArgumentParser(description="調達ポータル落札実績を取得")
    
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--days", type=int, help="過去N日分の差分を取得")
    group.add_argument("--date", help="特定日の差分を取得 (YYYYMMDD)")
    group.add_argument("--year", type=int, help="年度全件を取得 (西暦)")
    group.add_argument("--list", action="store_true", help="利用可能なファイル一覧")
    
    parser.add_argument("-o", "--output", help="CSV出力ファイル")
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログ")
    parser.add_argument("--limit", type=int, default=20, help="表示件数（デフォルト20）")
    
    args = parser.parse_args()
    
    # ログ設定
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    
    with PPortalAwardClient() as client:
        # 一覧表示
        if args.list:
            files = client.list_available_files()
            
            print("=== 全件ファイル ===")
            for f in files["yearly"]:
                print(f"  {f}")
            
            print(f"\n=== 差分ファイル（最新{min(10, len(files['diff']))}件）===")
            for f in files["diff"][:10]:
                print(f"  {f}")
            
            print(f"\n全件: {len(files['yearly'])}件, 差分: {len(files['diff'])}件")
            return 0
        
        records = []
        
        # 日付指定
        if args.date:
            records = client.download_diff(args.date)
        
        # 年度指定
        elif args.year:
            records = client.download_yearly(args.year)
        
        # 日数指定（デフォルト）
        else:
            days = args.days or 7
            files = client.list_available_files()
            
            print(f"過去{days}日分の差分を取得中...\n")
            
            for filename in files["diff"][:days]:
                import re
                match = re.search(r"diff_(\d{8})\.zip", filename)
                if match:
                    date = match.group(1)
                    day_records = client.download_diff(date)
                    records.extend(day_records)
                    print(f"  {date}: {len(day_records)}件")
        
        # 結果表示
        print(f"\n=== 取得結果: {len(records)}件 ===\n")
        
        for i, r in enumerate(records[:args.limit], 1):
            print(f"{i}. {r.title[:50]}")
            print(f"   案件番号: {r.case_number}")
            print(f"   落札日: {r.award_date}")
            print(f"   落札金額: {r.award_amount:,.0f}円")
            print(f"   落札者: {r.winner_name}")
            if r.corporate_number:
                print(f"   法人番号: {r.corporate_number}")
            print()
        
        if len(records) > args.limit:
            print(f"... 他 {len(records) - args.limit} 件")
        
        # CSV出力
        if args.output and records:
            with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "case_number", "title", "award_date", "award_amount",
                    "procurement_type", "org_code", "winner_name", "corporate_number"
                ])
                writer.writeheader()
                for r in records:
                    writer.writerow(r.to_dict())
            
            print(f"\nCSV出力: {args.output}")
        
        return 0


if __name__ == "__main__":
    sys.exit(main())
