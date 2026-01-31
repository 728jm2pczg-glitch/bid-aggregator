#!/bin/bash
# =============================================================================
# 入札情報アグリゲータ 定期実行スクリプト
# =============================================================================
#
# 使用方法:
#   ./scripts/daily_run.sh [--notify]
#
# オプション:
#   --notify  Slack/メール通知を有効化
#
# 環境変数:
#   BID_AGGREGATOR_DIR  プロジェクトディレクトリ（デフォルト: スクリプトの親ディレクトリ）
#   SLACK_WEBHOOK_URL   Slack通知先（--notify時に使用）
#   NOTIFY_EMAIL        メール通知先（--notify時に使用、Slack優先）
#
# =============================================================================

set -e

# スクリプトのディレクトリを取得
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${BID_AGGREGATOR_DIR:-$(dirname "$SCRIPT_DIR")}"

# ログディレクトリ
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

# ログファイル（日付付き）
DATE=$(date +%Y-%m-%d)
LOG_FILE="$LOG_DIR/daily_run_$DATE.log"

# 関数: ログ出力
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# 関数: エラーハンドリング
error_exit() {
    log "ERROR: $1"
    exit 1
}

# =============================================================================
# メイン処理
# =============================================================================

log "========== 定期実行開始 =========="
log "プロジェクトディレクトリ: $PROJECT_DIR"

# 仮想環境の確認と有効化
VENV_DIR="$PROJECT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    error_exit "仮想環境が見つかりません: $VENV_DIR"
fi

log "仮想環境を有効化: $VENV_DIR"
source "$VENV_DIR/bin/activate"

# bid-cliの確認
if ! command -v bid-cli &> /dev/null; then
    error_exit "bid-cli が見つかりません"
fi

# 設定ファイルの確認
CONFIG_FILE="$PROJECT_DIR/config/queries.yml"
if [ ! -f "$CONFIG_FILE" ]; then
    error_exit "設定ファイルが見つかりません: $CONFIG_FILE"
fi

# =============================================================================
# 1. データ取得
# =============================================================================

log "--- データ取得開始 ---"
cd "$PROJECT_DIR"

if bid-cli ingest --queries "$CONFIG_FILE" >> "$LOG_FILE" 2>&1; then
    log "データ取得完了"
else
    log "WARNING: データ取得でエラーが発生しました（処理は継続）"
fi

# =============================================================================
# 2. 保存検索の実行（--notify オプション時）
# =============================================================================

if [ "$1" = "--notify" ]; then
    log "--- 保存検索・通知開始 ---"
    
    # 通知先の決定
    NOTIFY_CHANNEL=""
    NOTIFY_RECIPIENT=""
    
    if [ -n "$SLACK_WEBHOOK_URL" ]; then
        NOTIFY_CHANNEL="slack"
        NOTIFY_RECIPIENT="$SLACK_WEBHOOK_URL"
        log "通知先: Slack"
    elif [ -n "$NOTIFY_EMAIL" ]; then
        NOTIFY_CHANNEL="email"
        NOTIFY_RECIPIENT="$NOTIFY_EMAIL"
        log "通知先: Email ($NOTIFY_EMAIL)"
    else
        log "WARNING: 通知先が設定されていません（SLACK_WEBHOOK_URL または NOTIFY_EMAIL）"
    fi
    
    # 有効な保存検索を実行
    if [ -n "$NOTIFY_CHANNEL" ]; then
        # 保存検索一覧を取得して実行
        SAVED_SEARCHES=$(bid-cli saved-search list --enabled-only 2>/dev/null | grep -E "^\│" | awk -F'│' '{print $3}' | tr -d ' ' | grep -v "^$" | grep -v "名前")
        
        if [ -n "$SAVED_SEARCHES" ]; then
            for name in $SAVED_SEARCHES; do
                log "保存検索実行: $name"
                if bid-cli saved-search run \
                    --name "$name" \
                    --notify \
                    --channel "$NOTIFY_CHANNEL" \
                    --recipient "$NOTIFY_RECIPIENT" >> "$LOG_FILE" 2>&1; then
                    log "保存検索完了: $name"
                else
                    log "WARNING: 保存検索でエラー: $name"
                fi
            done
        else
            log "有効な保存検索がありません"
        fi
    fi
else
    log "通知はスキップ（--notify オプションなし）"
fi

# =============================================================================
# 3. 統計情報の出力
# =============================================================================

log "--- 統計情報 ---"
bid-cli db stats >> "$LOG_FILE" 2>&1 || true

# =============================================================================
# 4. 古いログの削除（30日以上前）
# =============================================================================

log "--- 古いログの削除 ---"
find "$LOG_DIR" -name "daily_run_*.log" -mtime +30 -delete 2>/dev/null || true
log "30日以上前のログを削除しました"

# =============================================================================
# 完了
# =============================================================================

log "========== 定期実行完了 =========="

# 仮想環境を無効化
deactivate 2>/dev/null || true

exit 0
