# chuni-news-bot

<p align="left">
    <!-- python icon -->
    <img src="https://img.shields.io/badge/-Python-F9DC3E.svg?logo=python&style=flat" />
    <!-- code size -->
    <img src="https://img.shields.io/github/languages/code-size/kei-academic/chuni-news-bot" />
</p>

チュウニズム（CHUNITHM）の公式X（Twitter）アカウント（@chunithm）の最新ポストを10分ごとに監視し、新しい投稿があった場合に指定したDiscordチャンネルへ自動転送するBotです。

## 技術スタック
- **言語:** Python 3
- **主要なライブラリ:**
  - `discord.py` (Discordへのメッセージ送信)
  - `twikit` (Xの非公式APIスクレイピング機能)
  - `python-dotenv` (環境変数の読み込み)

## 動作の仕組み
1. 10分に1回、`twikit` を利用して公式アカウントの最新ポストを取得します。
2. 取得したポストがリツイートではなく、かつ前回取得した `ID`（`last_tweet_id.txt` に一時保存）と異なる場合のみ、「新しい投稿」と判定します。
3. `discord.py` を用いて、`.env` に登録された指定チャンネルにURLを送信し、重複送信を防ぐために最新IDを上書き記録します。

## 必要な事前準備（ローカル実行）

### 1. リポジトリのクローンとパッケージインストール
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 環境変数の設定
プロジェクトのルートディレクトリに `.env` ファイルを作成し、以下の情報を記述します。

```env
DISCORD_TOKEN=あなたのDiscordボットトークン
TARGET_CHANNEL_ID=送信先のチャンネルID
# (以下は新規ログイン用ですが、現在は後述の cookies.json を使用します)
TWITTER_USERNAME=Bot用のXアカウントのユーザーネーム
TWITTER_EMAIL=Bot用のXアカウントのメールアドレス
TWITTER_PASSWORD=Bot用のXアカウントのパスワード
```

### 3. X（Twitter）のCookie取得 【重要】
現在、XのCloudflareボット対策によるアクセス拒否（403 Forbidden）を回避するため、ブラウザで取得したCookieを使用してログイン状態を保持します。

1. 通常のブラウザでX（Twitter）にログインします。
2. 開発者ツール（F12キー）を開き、`Application`（またはストレージ）タブ内の `Cookies` から `https://x.com` を選択します。
3. `auth_token` と `ct0` の値をコピーします。
4. 本プログラムと同じフォルダに `cookies.json` というファイルを作成し、以下の形式で保存します。

```json
{
  "auth_token": "コピーした値",
  "ct0": "コピーした値"
}
```

## 起動方法

```bash
python3 bot.py
```
起動時のログで「Discord: 送信完了しました。」等が出力されれば正常に動作しています。

---

## クラウド（GCP / e2-micro）での24時間365日稼働手順

手元のPCをシャットダウンしてもBotを動かし続けるには、サーバーを利用してバックグラウンドで起動させる必要があります。

1. **ファイルのアップロード**
   必要なファイル（`bot.py`, `cookies.json`, `.env`, `requirements.txt`）をサーバーにアップロードします。

2. **Python環境の構築**
   ```bash
   sudo apt update
   sudo apt install -y python3-pip python3-venv tmux
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **twikit のエラーパッチ適用（※バージョン2.3.3時点の必須手順）**
   Xの仕様変更により `Couldn't get KEY_BYTE indices` エラーが出る場合、以下のパッチを当ててライブラリを修正します。
   ```bash
   TARGET_FILE=$(ls -d venv/lib/python3.*/site-packages/twikit/x_client_transaction/transaction.py)
   wget -qO "$TARGET_FILE" https://raw.githubusercontent.com/ryanstoic/twikit/4a62e2895676398e5c2dcce697597abbddb07a2c/twikit/x_client_transaction/transaction.py
   ```

4. **仮想画面（tmux）での永続起動**
   ```bash
   # tmuxに入る
   tmux new -s bot

   # venvを再度有効化してプログラムを起動
   source venv/bin/activate
   python3 bot.py
   ```

5. **バックグラウンドに回す（デタッチ）**
   プログラムが動いているのを確認したら、**`Ctrl+B` を押して指を離し、`D` を押す**とバックグラウンド稼働状態になります。
   これでSSH画面を閉じてもBotは24時間稼働し続けます。

## トラブルシューティング
* **突然動かなくなった場合**
X（Twitter）の仕様変更によるものか、`cookies.json` に設定している値の有効期限切れ（数ヶ月程度）の可能性が高いです。ブラウザから再度最新のCookieを取得して上書きし、再起動してください。
