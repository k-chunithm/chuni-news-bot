import os
import asyncio
import discord
import httpx
from bs4 import BeautifulSoup
from discord.ext import tasks
from dotenv import load_dotenv

# 環境変数の読み込み
load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
TARGET_CHANNEL_ID = os.getenv('TARGET_CHANNEL_ID')

# CHUNITHM 公式ニュースサイトのURL
NEWS_SITE_URL = 'https://info-chunithm.sega.jp/'
LAST_NEWS_URL_FILE = 'last_news_url.txt'

# Discordクライアントの設定
intents = discord.Intents.default()
intents.message_content = True
discord_client = discord.Client(intents=intents)

def get_saved_news_url():
    """前回投稿したニュースのURLをファイルから読み込む"""
    if os.path.exists(LAST_NEWS_URL_FILE):
        with open(LAST_NEWS_URL_FILE, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return None

def save_news_url(url):
    """投稿したニュースのURLをファイルに保存する"""
    with open(LAST_NEWS_URL_FILE, 'w', encoding='utf-8') as f:
        f.write(str(url))

async def fetch_latest_news():
    """公式サイトから最新のニュースを取得する"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        response = await client.get(NEWS_SITE_URL)
        if response.status_code != 200:
            raise Exception(f"サイトへのアクセスに失敗しました (Status: {response.status_code})")

        soup = BeautifulSoup(response.text, 'html.parser')

        # ニュース項目を取得
        # セレクタはサイトの構造に合わせて調整 (通常は article や .news_list a)
        news_links = soup.find_all('a', href=True)

        for link in news_links:
            href = link['href']
            # https://info-chunithm.sega.jp/数字/ 形式のリンクを探す
            if NEWS_SITE_URL in href and href.rstrip('/').split('/')[-1].isdigit():
                title = link.get_text(separator=" ", strip=True)
                # タイトルが空の場合は中の要素から探す
                # 画像の抽出
                image_url = None
                img_tag = link.find('img')
                if img_tag and img_tag.get('src'):
                    image_url = img_tag['src']
                    # 相対パスの場合は絶対パスに変換
                    if not image_url.startswith('http'):
                        from urllib.parse import urljoin
                        image_url = urljoin(NEWS_SITE_URL, image_url)
                
                return {"url": href, "title": title, "image_url": image_url}

    return None

@discord_client.event
async def on_ready():
    print(f'Discord: {discord_client.user} としてログインしました！')

    if not TARGET_CHANNEL_ID:
        print("エラー: .env に TARGET_CHANNEL_ID が設定されていません。")
        return

    print(f'Discord: 対象チャンネルID -> {TARGET_CHANNEL_ID}')
    print("Botの準備が完了しました。10分に1回の監視タスクを開始します...")
    # 初回起動時に現在の最新を取得しておく（未保存の場合のみ）
    if not get_saved_news_url():
        latest = await fetch_latest_news()
        if latest:
            save_news_url(latest['url'])
            print(f"初期設定: 最新ニュースを保存しました ({latest['url']})")

    check_new_news.start()

@tasks.loop(minutes=10)
async def check_new_news():
    """10分に1回実行されるニュース監視タスク"""
    print("公式サイト: 最新ニュースのチェックを開始します...")
    try:
        latest = await fetch_latest_news()

        if not latest:
            print("公式サイト: ニュースが取得できませんでした。")
            return

        saved_url = get_saved_news_url()

        if saved_url == latest['url']:
            print(f"公式サイト: 新しいニュースはありません (最新URL: {latest['url']})")
            return

        # 新規ニュース発見
        print(f"公式サイト: 新規ニュースを検出！ ({latest['title']})")

        channel = discord_client.get_channel(int(TARGET_CHANNEL_ID))
        if channel is None:
            print(f"エラー: チャンネルが見つかりませんでした。ID: {TARGET_CHANNEL_ID}")
            return

        # ニュースタイトルから不要な文字列(NEW!!など)を除去して整形
        clean_title = latest['title'].replace('NEW!!', '').strip()
        
        # 投稿メッセージ (例: 2026.04.01 (水) 「タイトル」)
        # 日付とタイトルの間にスペースがあることを前提に、最初の一致（日付部分）を分離
        import re
        date_pattern = r'^\d{4}\.\d{2}\.\d{2} \(.+?\)'
        date_match = re.search(date_pattern, clean_title)
        
        if date_match:
            date_part = date_match.group()
            title_part = clean_title.replace(date_part, '').strip()
            formatted_title = f"{date_part} 「{title_part}」"
        else:
            formatted_title = f"「{clean_title}」"

        # 投稿メッセージ (Embed形式)
        embed = discord.Embed(
            title="CHUNITHM公式サイトに新しいニュースが掲載されました！",
            description=f"{formatted_title}\n{latest['url']}",
            color=0x00A2E8 # チュウニズムっぽい色
        )
        
        if latest.get('image_url'):
            embed.set_image(url=latest['image_url'])
            
        await channel.send(embed=embed)

        save_news_url(latest['url'])
        print("Discord: 送信完了しました。")

    except Exception as e:
        error_msg = f"ニュースチェック中にエラーが発生しました: {e}"
        print(error_msg)
        try:
            channel = discord_client.get_channel(int(TARGET_CHANNEL_ID))
            if channel:
                await channel.send(f"⚠️ **Botエラー通知** ⚠️\n公式サイトの監視中にエラーが発生しました。\n```\n{e}\n```")
        except Exception as inner_e:
            print(f"エラー通知の送信失敗: {inner_e}")

if __name__ == '__main__':
    if not DISCORD_TOKEN:
        print("エラー: .env に DISCORD_TOKEN が設定されていません。")
    else:
        discord_client.run(DISCORD_TOKEN)
