# 入札・調達情報アグリゲータ（Bid Aggregator）

官公需情報ポータルサイト（KKJ）のAPIを中心に、入札・調達情報を収集して
SQLiteに蓄積し、検索・通知・エクスポートを行うCLIツールです。
調達ポータル（p-portal.go.jp）のスクレイピング取得も実験的にサポートします。

## 概要

- KKJ APIから定期取得し共通スキーマに正規化
- SQLiteに保存し、キーワード・期間・機関で検索
- 保存検索・Slack/メール通知
- CSV/JSONエクスポート
- 日付分割による全件取得（1000件超対策）
- 調達ポータル取得（実験的、HTML構造変更に弱い）

## 出典

- 官公需情報ポータルサイト（KKJ）API
- 調達ポータル（p-portal.go.jp）※スクレイピング

## 必要環境

- Python 3.11+
- SQLite 3
- （任意）調達ポータル取得を使う場合は `beautifulsoup4` が必要

## インストール

```bash
# リポジトリをクローン
git clone <repository-url>
cd bid-aggregator

# 仮想環境を作成
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 依存パッケージをインストール
pip install -e ".[dev]"

# 調達ポータル機能を使う場合のみ
pip install beautifulsoup4
```

## クイックスタート（KKJ）

### 1. 設定ファイルを作成

```bash
cp config/queries.example.yml config/queries.yml
# 必要に応じて編集
```

### 2. データベースを初期化

```bash
bid-cli db init
```

### 3. 入札情報を取得

```bash
bid-cli ingest --source kkj --queries config/queries.yml
```

### 4. 検索

```bash
bid-cli search --keyword "AI OR 機械学習" --limit 20
```

### 5. エクスポート

```bash
bid-cli export --format csv --output results.csv
```

## 調達ポータル取得（実験的）

`bid-cli` とは別の簡易CLIを利用します。HTML構造変更で壊れる可能性があります。

```bash
# ドライラン（DB保存なし）
python -m bid_aggregator.cli.pportal_ingest --dry-run

# キーワード検索
python -m bid_aggregator.cli.pportal_ingest -k "AI" --max-pages 5

# Slack通知付き
python -m bid_aggregator.cli.pportal_ingest -k "AI" --slack-webhook "$SLACK_WEBHOOK_URL"

# メール通知付き
python -m bid_aggregator.cli.pportal_ingest -k "AI" --email "user@example.com"
```

## CLI コマンド（bid-cli）

```bash
# 収集
bid-cli ingest --source kkj --queries config/queries.yml [--dry-run]

# 全件取得（1000件超対策）
bid-cli full-ingest --keyword "AI" --from 2025-01-01 --to 2025-01-31 \
                   [--days 7] [--org ORG] [--region CODE] [--dry-run]

# 検索
bid-cli search --keyword TEXT [--from DATE] [--to DATE] [--org TEXT] \
               [--source kkj|all] [--order-by newest|deadline] \
               [--limit N] [--offset N]

# エクスポート
bid-cli export --format csv|json [--output FILE]

# 保存検索
bid-cli saved-search add --name NAME --keyword TEXT [--from DATE] [--to DATE] \
                        [--org TEXT] [--source TEXT] [--order-by newest|deadline] \
                        [--schedule daily|hourly] [--only-new/--all]
bid-cli saved-search run --name NAME [--notify] [--channel slack|email] [--recipient DEST]
bid-cli saved-search list [--enabled-only]
bid-cli saved-search delete --name NAME

# 通知テスト
bid-cli notify test --channel slack|email --recipient DEST

# データベース
bid-cli db init
bid-cli db stats
```

## 設定

### queries.yml

`queries.yml` は `bid-cli ingest` 用です。保存検索はCLIで作成します。

```yaml
version: 1

queries:
  - name: ai_related
    source: kkj
    params:
      Query: "AI OR 機械学習 OR 画像検査"
    limit: 1000
    enabled: true
```

### 環境変数

```bash
# .env ファイルに記載
DATABASE_URL=sqlite:///data/bid_aggregator.db
LOG_LEVEL=INFO
NOTIFY_MAX_ITEMS=100

# Slack通知（調達ポータルCLIや定期実行で使用）
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx/yyy/zzz

# メール通知
NOTIFY_EMAIL=user@example.com
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=user@example.com
SMTP_PASSWORD=password
SMTP_FROM=noreply@example.com
```

## 定期実行

macOS の launchd での自動実行は `scripts/README.md` を参照してください。

## ディレクトリ構成

```
bid-aggregator/
├── README.md
├── .env.example
├── pyproject.toml
├── config/
│   └── queries.example.yml
├── data/                    # SQLiteデータベース（gitignore）
├── scripts/
│   ├── daily_run.sh
│   ├── test_pportal.sh
│   └── com.user.bid-aggregator.plist
└── src/
    └── bid_aggregator/
        ├── cli/
        │   ├── main.py
        │   └── pportal_ingest.py
        ├── core/
        ├── ingest/
        └── notify/
```

## ライセンス

MIT License

## 関連リンク

- [官公需情報ポータルサイト](https://www.kkj.go.jp/s/)
- [KKJ API ガイド](https://www.kkj.go.jp/doc/ja/api_guide.pdf)
