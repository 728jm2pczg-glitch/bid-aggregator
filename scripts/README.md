# 定期実行のセットアップ

macOS の launchd を使用して、毎日自動で入札情報を取得・通知します。

## クイックセットアップ

```bash
# 1. スクリプトに実行権限を付与
chmod +x scripts/daily_run.sh

# 2. plistファイルを編集
#    - YOUR_USERNAME → 実際のユーザー名
#    - /path/to/bid-aggregator → 実際のプロジェクトパス
#    - SLACK_WEBHOOK_URL → 実際のWebhook URL
vi scripts/com.user.bid-aggregator.plist

# 3. LaunchAgentsにコピー
cp scripts/com.user.bid-aggregator.plist ~/Library/LaunchAgents/

# 4. ジョブを登録
launchctl load ~/Library/LaunchAgents/com.user.bid-aggregator.plist

# 5. 動作確認（手動実行）
launchctl start com.user.bid-aggregator
```

## 詳細手順

### 1. 事前準備

```bash
# ログディレクトリを作成
mkdir -p logs

# スクリプトに実行権限を付与
chmod +x scripts/daily_run.sh

# 手動でテスト実行
./scripts/daily_run.sh

# 通知付きでテスト実行
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/xxx/yyy/zzz" \
./scripts/daily_run.sh --notify
```

### 2. plistファイルの編集

`scripts/com.user.bid-aggregator.plist` を編集し、以下を置き換えます：

| 置換対象 | 例 |
|----------|-----|
| `YOUR_USERNAME` | `nao` |
| `/path/to/bid-aggregator` | `/Users/nao/main/work/project/行政/bid-aggregator` |
| `SLACK_WEBHOOK_URL` | `https://hooks.slack.com/services/T.../B.../xxx` |

### 3. launchdに登録

```bash
# LaunchAgentsディレクトリにコピー
cp scripts/com.user.bid-aggregator.plist ~/Library/LaunchAgents/

# ジョブを登録（有効化）
launchctl load ~/Library/LaunchAgents/com.user.bid-aggregator.plist

# 登録確認
launchctl list | grep bid-aggregator
```

### 4. 動作確認

```bash
# 手動で即時実行
launchctl start com.user.bid-aggregator

# ログを確認
tail -f logs/daily_run_$(date +%Y-%m-%d).log
tail -f logs/launchd_stdout.log
tail -f logs/launchd_stderr.log
```

## 管理コマンド

```bash
# ジョブの状態確認
launchctl list | grep bid-aggregator

# ジョブを停止（無効化）
launchctl unload ~/Library/LaunchAgents/com.user.bid-aggregator.plist

# ジョブを再読み込み（設定変更後）
launchctl unload ~/Library/LaunchAgents/com.user.bid-aggregator.plist
launchctl load ~/Library/LaunchAgents/com.user.bid-aggregator.plist

# 手動で即時実行
launchctl start com.user.bid-aggregator

# ジョブを完全に削除
launchctl unload ~/Library/LaunchAgents/com.user.bid-aggregator.plist
rm ~/Library/LaunchAgents/com.user.bid-aggregator.plist
```

## スケジュールの変更

`com.user.bid-aggregator.plist` の `StartCalendarInterval` を編集します。

### 毎日8:00 AM（デフォルト）

```xml
<key>StartCalendarInterval</key>
<dict>
    <key>Hour</key>
    <integer>8</integer>
    <key>Minute</key>
    <integer>0</integer>
</dict>
```

### 毎日8:00 AMと18:00 PM（1日2回）

```xml
<key>StartCalendarInterval</key>
<array>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <dict>
        <key>Hour</key>
        <integer>18</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
</array>
```

### 平日のみ（月〜金）

```xml
<key>StartCalendarInterval</key>
<array>
    <dict>
        <key>Weekday</key>
        <integer>1</integer>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <!-- 火〜金も同様に追加 -->
</array>
```

### 1時間ごと

```xml
<key>StartInterval</key>
<integer>3600</integer>
```

## トラブルシューティング

### ジョブが実行されない

```bash
# ジョブの状態を確認
launchctl list | grep bid-aggregator
# 結果例: -  0  com.user.bid-aggregator
# 左から: PID(実行中でなければ-), 終了コード, ラベル

# 終了コードが0以外の場合はエラー
# ログを確認
cat logs/launchd_stderr.log
```

### 権限エラー

```bash
# スクリプトの実行権限を確認
ls -la scripts/daily_run.sh

# 権限がない場合
chmod +x scripts/daily_run.sh
```

### パスが見つからない

plistファイルの `PATH` 環境変数に必要なパスを追加：

```xml
<key>PATH</key>
<string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:/Users/nao/.local/bin</string>
```

### 仮想環境が見つからない

plistファイルの `BID_AGGREGATOR_DIR` が正しいか確認：

```bash
# 確認
ls -la /Users/nao/path/to/bid-aggregator/.venv/
```

## ログファイル

| ファイル | 内容 |
|----------|------|
| `logs/daily_run_YYYY-MM-DD.log` | 日次実行ログ |
| `logs/launchd_stdout.log` | launchd標準出力 |
| `logs/launchd_stderr.log` | launchdエラー出力 |

ログは30日経過後に自動削除されます。

## メール通知を使用する場合

Slack の代わりにメール通知を使用する場合：

1. `.env` ファイルにSMTP設定を追加：

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=your-email@gmail.com
```

2. plistファイルの環境変数を変更：

```xml
<key>EnvironmentVariables</key>
<dict>
    <key>NOTIFY_EMAIL</key>
    <string>recipient@example.com</string>
    <!-- SLACK_WEBHOOK_URL を削除または空にする -->
</dict>
```

※ Gmail を使用する場合は「アプリパスワード」が必要です。
