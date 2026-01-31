# 入札・調達情報アグリゲータ（Bid Aggregator）

官公需情報ポータルサイト（KKJ）等の公的データソースから入札・調達情報を収集し、検索・通知・エクスポートを提供するツール。

## 概要

- 公式APIから入札情報を定期取得
- 共通スキーマに正規化して蓄積
- キーワード・期間・機関での検索
- 条件にマッチした案件の通知（メール/Slack）
- CSV/JSONエクスポート

## 出典

本ツールは[官公需情報ポータルサイト](https://www.kkj.go.jp/s/)のAPIを使用しています。

## 必要環境

- Python 3.11+
- SQLite 3

## インストール

```bash
# リポジトリをクローン
git clone <repository-url>
cd bid-aggregator

# 仮想環境を作成
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 依存パッケージをインストール
pip install -e ".[dev]"
```

## クイックスタート

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

## CLI コマンド

```bash
# 収集
bid-cli ingest --source kkj --queries config/queries.yml [--dry-run]

# 検索
bid-cli search --keyword TEXT [--from DATE] [--to DATE] [--org TEXT] \
               [--source kkj|all] [--order-by newest|deadline] \
               [--limit N] [--offset N]

# エクスポート
bid-cli export --format csv|json [--output FILE]

# 保存検索
bid-cli saved-search add --name NAME --query-ref REF
bid-cli saved-search run --name NAME [--notify]
bid-cli saved-search list
bid-cli saved-search delete --name NAME

# 通知テスト
bid-cli notify test --channel slack --recipient <WEBHOOK_URL>

# データベース
bid-cli db init
bid-cli db migrate
bid-cli db stats
```

## 設定

### queries.yml

```yaml
version: 1

queries:
  - name: ai_related
    source: kkj
    params:
      Query: "AI OR 機械学習 OR 画像検査"
    limit: 1000
    enabled: true

saved_searches:
  - name: ai_daily
    query_ref: ai_related
    schedule: daily
    only_new: true
    enabled: true

notify:
  channel: slack
  recipients:
    - "https://hooks.slack.com/services/xxx/yyy/zzz"
  enabled: true
```

### 環境変数

```bash
# .env ファイルに記載
DATABASE_URL=sqlite:///data/bid_aggregator.db
LOG_LEVEL=INFO
NOTIFY_MAX_ITEMS=100

# Slack通知
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx/yyy/zzz

# メール通知
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=user@example.com
SMTP_PASSWORD=password
SMTP_FROM=noreply@example.com
```

## ディレクトリ構成

```
bid-aggregator/
├── README.md
├── pyproject.toml
├── config/
│   ├── queries.example.yml
│   └── queries.yml          # ユーザー設定（gitignore）
├── data/
│   └── bid_aggregator.db    # SQLiteデータベース（gitignore）
├── src/
│   └── bid_aggregator/
│       ├── __init__.py
│       ├── cli/             # CLIコマンド
│       ├── core/            # コアロジック
│       ├── ingest/          # データ収集
│       ├── normalize/       # 正規化
│       ├── search/          # 検索
│       ├── notify/          # 通知
│       └── export/          # エクスポート
└── tests/
    ├── unit/
    └── integration/
```

## ライセンス

MIT License

## 関連リンク

- [官公需情報ポータルサイト](https://www.kkj.go.jp/s/)
- [KKJ API ガイド](https://www.kkj.go.jp/doc/ja/api_guide.pdf)
