# hotel-watch

ダイワロイネットホテル（[tripla](https://tripla.io/) 予約エンジン）の空室を定期的にチェックし、
「満室 → 空室あり」に変化したタイミングで Slack に通知するツールです。

GitHub Actions で全自動運用しています。ヘッドレスブラウザで毎回トークンを取得し直すので、
`client_session` を手動で更新する必要はありません。

## 仕組み

```
cron-job.org (15分おき)
   │  POST /actions/workflows/watch.yml/dispatches
   ▼
GitHub Actions (watch.yml)
   │  1. Chromium を起動し、予約ページを開いて client-session を取得
   │  2. 対象の日程ごとに空室APIを叩く
   │  3. 前回チェック時の状態(state.json)と比較
   │  4. 満室→空室に変化した日程があれば Slack に通知
   │  5. state.json をコミットして次回実行に引き継ぐ
   ▼
Slack チャンネル
```

GitHub の `schedule:` トリガーもバックアップとして併用しています（cron-job.org や PAT が
止まった場合の保険。ただし GitHub 側は実行間隔が数時間まで間引かれることがあります）。

## ファイル構成

| ファイル | 役割 |
|---|---|
| [hotel_watch.py](hotel_watch.py) | 本体。空室チェックと Slack 通知 |
| [refresh_session.py](refresh_session.py) | ヘッドレスブラウザで `client_session` を取得 |
| [config.json](config.json) | 実際に使う設定（**gitignore対象、秘匿値を含む**） |
| [config.example.json](config.example.json) | ローカル実行用のひな形 |
| [config.ci.json](config.ci.json) | GitHub Actions 用の設定（秘匿値は含まない） |
| [state.json](state.json) | 日程ごとの前回チェック結果（コミットして永続化） |
| [.github/workflows/watch.yml](.github/workflows/watch.yml) | GitHub Actions ワークフロー |
| [requirements.txt](requirements.txt) | 本体の依存（`requests`） |
| [requirements-refresh.txt](requirements-refresh.txt) | セッション取得用の依存（`playwright`） |

## 設定項目（config.json）

```jsonc
{
  "hotel_id": 285,                  // 対象ホテルのID (concierge.tripla.ai/book/hotels/<ID>/rooms)
  "hotel_code": "973ac83f...",      // 予約リンク生成用のホテルコード
  "client_session": "...",          // tripla APIの認証トークン(自動取得されるので通常は触らない)
  "slack_webhook_url": "https://hooks.slack.com/services/...",
  "room_name_filter": "禁煙",        // 部屋名にこの文字列を含む部屋だけを判定・通知対象にする。空文字で全部屋
  "targets": [                      // 監視する日程のリスト
    { "checkin_date": "2026/09/19", "checkout_date": "2026/09/20", "adults": 2 }
  ]
}
```

## ローカルでの手動実行

```bash
pip install -r requirements.txt
cp config.example.json config.json   # 初回のみ。client_session と slack_webhook_url を編集
python hotel_watch.py
```

Windows で `python` が Microsoft Store のスタブになっている場合は `py` を使ってください。

### client_session の手動更新（ローカルのみ）

予約ページを開くだけでログイン不要のセッショントークンが新規発行される仕組みを利用しています。

```bash
pip install -r requirements-refresh.txt
playwright install chromium
python refresh_session.py            # config.json の client_session を最新化
python refresh_session.py --print    # 値を標準出力に出すだけ(CIで使用)
```

## GitHub Actions（全自動）

[watch.yml](.github/workflows/watch.yml) が実行ごとに：

1. `config.ci.json` を `config.json` としてコピー（秘匿値は含まれていない）
2. `refresh_session.py --print` で毎回新しい `client_session` を取得し環境変数で渡す
3. `hotel_watch.py` を実行
4. 失敗したら Slack に `:warning:` 通知
5. `state.json` をコミット＆push

### 必要な Secrets

| Secret | 用途 |
|---|---|
| `SLACK_WEBHOOK_URL` | 通知先の Incoming Webhook URL |

`CLIENT_SESSION` シークレットは不要です（毎回ヘッドレスブラウザで取得するため）。

### 15分間隔での起動（cron-job.org）

GitHub の `schedule:` は実行間隔が大きく間引かれる（実測で数時間おき）ため、
[cron-job.org](https://cron-job.org) から15分おきに GitHub API へ `workflow_dispatch` を
POST して起動しています。

- Fine-grained PAT（対象リポジトリのみ、Repository permissions → Actions: Read and write）を発行
- cron-job.org に以下を登録
  - URL: `https://api.github.com/repos/<owner>/<repo>/actions/workflows/watch.yml/dispatches`
  - Method: `POST`
  - Body: `{"ref":"main"}`
  - Headers: `Accept: application/vnd.github+json` / `Authorization: Bearer <PAT>` / `X-GitHub-Api-Version: 2022-11-28`

PATには有効期限があるため、切れたら作り直して cron-job.org 側のヘッダーを更新してください。

## リポジトリの公開について

このリポジトリは **public** です。ヘッドレスブラウザを使う関係で1実行が1分弱かかり、
15分間隔だと private リポジトリの無料 Actions 分数（2,000分/月）を超えるため、
public にすることで分数無制限の恩恵を受けています。コード・設定ファイルに秘匿値は
含まれておらず（`client_session` は実行ごとに使い捨て、Webhook URL は Secrets で暗号化）、
公開して問題ない構成にしています。

## トラブルシューティング

- **Actions が赤くなる**：ほとんどの場合 `client_session` 取得の失敗。ログの
  `401 Invalid Client-Session` を確認。Slack にも失敗通知が飛ぶはず。
- **cron-job.org のテスト実行が 401**：PAT が失効しています。作り直して
  Authorization ヘッダーを更新してください。
- **想定より通知間隔が空く**：GitHub の `schedule:` 実行だけに頼っている状態。
  cron-job.org 側の設定を確認してください。
