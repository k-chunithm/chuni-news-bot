import os
import asyncio
import discord
from discord.ext import tasks
from twikit import Client
from dotenv import load_dotenv

# 環境変数の読み込み
load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
TARGET_CHANNEL_ID = os.getenv('TARGET_CHANNEL_ID')
TWITTER_USERNAME = os.getenv('TWITTER_USERNAME')
TWITTER_EMAIL = os.getenv('TWITTER_EMAIL')
TWITTER_PASSWORD = os.getenv('TWITTER_PASSWORD')

# Chunithmの公式Xアカウントスクリーンネーム
TARGET_SCREEN_NAME = 'chunithm'
COOKIES_FILE = 'cookies.json'
LAST_TWEET_ID_FILE = 'last_tweet_id.txt'

# Discordクライアントの設定 (Message Content Intentを有効化)
intents = discord.Intents.default()
intents.message_content = True
discord_client = discord.Client(intents=intents)

# Twikitクライアントの設定
twitter_client = Client('ja-JP')

def get_saved_tweet_id():
    """前回取得したツイートIDをファイルから読み込む"""
    if os.path.exists(LAST_TWEET_ID_FILE):
        with open(LAST_TWEET_ID_FILE, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return None

def save_tweet_id(tweet_id):
    """取得したツイートIDをファイルに保存する"""
    with open(LAST_TWEET_ID_FILE, 'w', encoding='utf-8') as f:
        f.write(str(tweet_id))

async def login_to_twitter():
    """Xアカウントへのログイン処理（Cookieがあれば再利用）"""
    if os.path.exists(COOKIES_FILE):
        print("Twitter: 保存されたCookieを読み込みます...")
        twitter_client.load_cookies(COOKIES_FILE)
    else:
        print("Twitter: 新規ログインを試みます...")
        if not all([TWITTER_USERNAME, TWITTER_EMAIL, TWITTER_PASSWORD]):
            print("エラー: .env にXのアカウント情報が設定されていません。")
            return False
            
        await twitter_client.login(
            auth_info_1=TWITTER_USERNAME,
            auth_info_2=TWITTER_EMAIL,
            password=TWITTER_PASSWORD
        )
        twitter_client.save_cookies(COOKIES_FILE)
        print("Twitter: ログイン成功。Cookieを保存しました。")
    return True

@discord_client.event
async def on_ready():
    print(f'Discord: {discord_client.user} としてログインしました！')
    
    # チャンネルIDの設定チェック
    if not TARGET_CHANNEL_ID:
        print("エラー: .env に TARGET_CHANNEL_ID が設定されていません。投稿できません。")
        return
        
    print(f'Discord: 対象チャンネルID -> {TARGET_CHANNEL_ID}')
    
    # Twitterへのログイン
    login_success = await login_to_twitter()
    if login_success:
        print("Botの準備が完了しました。10分に1回の監視タスクを開始します...")
        check_new_tweets.start()
    else:
        print("Botの起動を中断します。Xの設定を確認してください。")

@tasks.loop(minutes=10)
async def check_new_tweets():
    """10分に1回実行されるメインの監視タスク"""
    print("Twitter: 最新ポストのチェックを開始します...")
    try:
        # 指定ユーザーの情報を取得・検証
        user = await twitter_client.get_user_by_screen_name(TARGET_SCREEN_NAME)
        
        # ユーザーの最新ポスト（タイムライン）を取得
        tweets = await twitter_client.get_user_tweets(str(user.id), 'Tweets')
        
        if not tweets:
            print("Twitter: ツイートが取得できませんでした。")
            return

        # 最新のツイート（先頭の要素）を取得
        latest_tweet = tweets[0]
        
        # リツイートかどうかを判定（テキストが 'RT @' で始まっていることが多い、もしくはリツイート元の情報があるか）
        is_retweet = latest_tweet.text.startswith('RT @')
        
        # 前回投稿したツイートかチェック
        saved_id = get_saved_tweet_id()
        
        if saved_id == latest_tweet.id:
            print(f"Twitter: 新しいポストはありません (最新ID: {latest_tweet.id})")
            return
            
        if is_retweet:
            print(f"Twitter: 最新はリツイートだったためスキップしました (ID: {latest_tweet.id})")
            # リツイートでも「最新取得済みID」として保存し、何度もひっかからないようにする
            save_tweet_id(latest_tweet.id)
            return

        # --- 新しい通常ポストが見つかった場合の処理 ---
        print(f"Twitter: 新規ポストを検出！ (ID: {latest_tweet.id})")
        
        # URLを生成 (https://x.com/{screen_name}/status/{id})
        tweet_url = f"https://x.com/{TARGET_SCREEN_NAME}/status/{latest_tweet.id}"
        
        # Discordの指定チャンネルへ送信
        channel = discord_client.get_channel(int(TARGET_CHANNEL_ID))
        if channel is None:
            print(f"エラー: チャンネルID {TARGET_CHANNEL_ID} が見つかりませんでした。Botが招待されているか確認してください。")
            return
            
        await channel.send(f"CHUNITHM公式の新しいポストです！\n{tweet_url}")
        
        # IDを保存して次回重複して送らないようにする
        save_tweet_id(latest_tweet.id)
        print("Discord: 送信完了しました。")

    except Exception as e:
        error_msg = f"Twitterチェック中にエラーが発生しました: {e}"
        print(error_msg)
        try:
            channel = discord_client.get_channel(int(TARGET_CHANNEL_ID))
            if channel:
                await channel.send(f"⚠️ **Botエラー通知** ⚠️\nTwitterの監視中にエラーが発生しました。\nCookieの期限切れやXの仕様変更の可能性があります。\n```\n{e}\n```")
        except Exception as inner_e:
            print(f"エラー通知の送信にも失敗しました: {inner_e}")

if __name__ == '__main__':
    if not DISCORD_TOKEN:
        print("エラー: .env に DISCORD_TOKEN が設定されていません。")
    else:
        discord_client.run(DISCORD_TOKEN)
