# chuni-news-bot

<p align="left">
    <!-- python icon -->
    <img src="https://img.shields.io/badge/-Python-F9DC3E.svg?logo=python&style=flat" />
    <!-- code size -->
    <img src="https://img.shields.io/github/languages/code-size/k-chunithm/chuni-news-bot" />
</p>

CHUNITHM（チュウニズム）の[公式サイト ニュース一覧](https://info-chunithm.sega.jp/)を10分ごとに監視し、新しいニュースが掲載された場合に指定したDiscordチャンネルへ画像付きで自動転送するBotです。
Twitter(X)の仕様変更に左右されず、安定して動作します。

## 技術スタック
- **言語:** Python 3
- **主要なライブラリ:**
  - `discord.py` (Discordへのメッセージ送信)
  - `beautifulsoup4` (公式サイトの解析)
  - `httpx` (HTTP通信)
  - `python-dotenv` (環境変数の読み込み)

## 動作の仕組み
1. 10分に1回、公式ニュースサイトを確認し、最新の記事URLを取得します。
2. 取得したURLが前回取得したもの（`last_news_url.txt` に保存）と異なる場合、「新しいニュース」と判定します。
3. 記事のタイトル、URL、サムネイル画像を抽出し、Discordへ埋め込みメッセージ（Embed）として送信します。

## 必要な事前準備（ローカル実行）

### 1. パッケージインストール
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 環境変数の設定
`.env` ファイルを作成し、以下の情報を記述します。
```env
DISCORD_TOKEN=あなたのDiscordボットトークン
TARGET_CHANNEL_ID=送信先のチャンネルID
```

---

## クラウド（GCP / e2-micro）でのデプロイ・運用手順

### 1. GCP インスタンスの設定（無料枠の推奨設定）
GCPの「Always Free（無期限無料枠）」内で運用するための推奨設定です。

- **リージョン**: `us-west1` (オレゴン), `us-central1` (アイオワ), `us-east1` (サウスカロライナ) のいずれかを選択。
- **マシンタイプ**: `e2-micro` (2 vCPU, 1 GB メモリ)。
- **ブートディスク**: 
  - タイプ: **標準永続ディスク** (Standard Persistent Disk) を選択（※バランスまたはSSDは有料になる場合があります）。
  - サイズ: 30 GB 以下。
- **OS**: Debian または Ubuntu (LTS) を推奨。
- **ネットワーク**: 「静的外部IPアドレス」を予約してインスタンスに紐付けておくと、再起動してもIPが変わらずSSH接続が楽になります。

### 2. ローカル（Mac）からのSSH接続設定（初回のみ）
GCPのブラウザターミナルを使わず、ローカルのMacターミナルから直接サーバーへ接続できるようにするための手順です。

1. **公開鍵の確認（Mac）**：Macのターミナルで `cat ~/.ssh/id_rsa.pub` を実行し、公開鍵をコピーします。
2. **公開鍵をGCPサーバーに登録**：GCPのブラウザターミナル上で、コピーした公開鍵を登録します。
   ```bash
   echo "ssh-rsa AAAAB3Nza......(あなたのMacの公開鍵の文字列)......" >> ~/.ssh/authorized_keys
   ```

### 3. 初回環境・アプリのセットアップ
1. **サーバー側の必要なパッケージをインストール**
   ```bash
   sudo apt update
   sudo apt install -y python3-pip python3-venv tmux
   ```

2. **Macからファイルを転送**
   手元のMacのターミナルで実行してください。
   ```bash
   scp bot.py .env requirements.txt k_chunithm@8.229.250.63:~/chuni_news_bot/
   ```

3. **サーバーにSSH接続してアプリを構築**
   ```bash
   ssh k_chunithm@8.229.250.63
   cd chuni_news_bot
   
   # 仮想環境の作成
   python3 -m venv venv
   
   # 実行画面（tmux）の作成
   tmux new -s bot
   
   # 実行準備
   source venv/bin/activate
   pip install -r requirements.txt
   
   # Bot起動
   python3 bot.py
   ```

4. **実行状態のまま抜ける（デタッチ）**
   実行中に `Ctrl + B` → `D` を押すと、Botを動かしたままSSHを終了できます。
   （画面を閉じてもBotは動き続けます）

### 4. 2回目以降（エラー時や再起動時）
1. **サーバーに接続**
   ```bash
   ssh k_chunithm@8.229.250.63
   cd chuni_news_bot
   ```
2. **実行画面に戻る（アタッチ）**
   ```bash
   tmux attach -t bot
   ```
3. **停止・再起動**
   `Ctrl + C` で一度止めてから、`python3 bot.py` で再度実行します。
