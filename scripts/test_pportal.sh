#!/bin/bash
# 調達ポータルスクレイピングテスト
#
# 使用方法:
#   ./scripts/test_pportal.sh              # 通常テスト
#   ./scripts/test_pportal.sh --debug      # HTML構造調査
#   ./scripts/test_pportal.sh -k "AI"      # キーワード検索

set -e

cd "$(dirname "$0")/.."

# 仮想環境を有効化（存在する場合）
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "調達ポータルクライアント テスト"
echo "================================"
echo ""

# 引数がない場合はデバッグモードで実行
if [ $# -eq 0 ]; then
    echo "使用方法:"
    echo "  ./scripts/test_pportal.sh --debug         # HTML構造を調査"
    echo "  ./scripts/test_pportal.sh -k 'AI'         # キーワード検索"
    echo "  ./scripts/test_pportal.sh -k 'AI' -v      # 詳細ログ付き"
    echo "  ./scripts/test_pportal.sh --org meti      # 経済産業省のみ"
    echo ""
    echo "利用可能な機関コード:"
    echo "  mod      - 防衛省"
    echo "  meti     - 経済産業省"
    echo "  digital  - デジタル庁"
    echo "  mext     - 文部科学省"
    echo "  mhlw     - 厚生労働省"
    echo "  maff     - 農林水産省"
    echo "  mlit     - 国土交通省"
    echo "  env      - 環境省"
    echo "  mof      - 財務省"
    echo "  mofa     - 外務省"
    echo "  moj      - 法務省"
    echo "  cao      - 内閣府"
    echo ""
    echo "まずデバッグモードでHTML構造を確認することを推奨します:"
    echo "  ./scripts/test_pportal.sh --debug"
    exit 0
fi

# テスト実行
python -m bid_aggregator.ingest.pportal_client "$@"
