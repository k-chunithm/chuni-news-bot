import os
import asyncio
import json
import discord
import httpx
from bs4 import BeautifulSoup
from discord.ext import tasks
from discord import app_commands
from dotenv import load_dotenv
import datetime
import calendar

# タイムゾーンの設定 (JST)
JST = datetime.timezone(datetime.timedelta(hours=9), 'JST')

# 環境変数の読み込み
load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# CHUNITHM 公式ニュースサイトのURL
NEWS_SITE_URL = 'https://info-chunithm.sega.jp/'
LAST_NEWS_URL_FILE = 'last_news_url.txt'

# Discordクライアントの設定
intents = discord.Intents.default()
intents.message_content = True
discord_client = discord.Client(intents=intents)
tree = app_commands.CommandTree(discord_client)

# エラー状態を管理するフラグ
is_in_error_state = False

CHANNELS_FILE = 'channels.json'

def get_registered_channels():
    """登録されているチャンネルIDのリストを取得する"""
    if os.path.exists(CHANNELS_FILE):
        try:
            with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def save_registered_channels(channels):
    """登録されているチャンネルIDのリストを保存する"""
    with open(CHANNELS_FILE, 'w', encoding='utf-8') as f:
        json.dump(channels, f, indent=4)

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
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=10.0) as client:
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
async def on_guild_join(guild):
    print(f'Discord: {guild.name} に参加しました！')
    
    greeting = (
        "やっほ～！　プレイヤーさん！\n"
        "CHUNITHM公式ニュースBotの追加、ありがとう！\n"
        "私がいれば、最新のニュースをすぐにこのサーバーにお届けしちゃうよ～！！\n\n"
        "さ、プレイヤーさん！準備いい？\n"
        "ニュースを流したいチャンネルで `/news_register` って入力してね！\n"
        "そこから私とサーバーをリンク接続しちゃうから！よろしくね～！"
    )
    
    if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
        await guild.system_channel.send(greeting)
        return
        
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            await channel.send(greeting)
            return

@discord_client.event
async def on_ready():
    print(f'Discord: {discord_client.user} としてログインしました！')

    try:
        synced = await tree.sync()
        print(f"Discord: {len(synced)} 個のコマンドを同期しました。")
    except Exception as e:
        print(f"Discord: コマンドの同期に失敗しました: {e}")

    channels = get_registered_channels()
    print(f'Discord: 現在登録されているチャンネル数 -> {len(channels)}')

    print("Botの準備が完了しました。10分に1回の監視タスクを開始します...")
    # 初回起動時に現在の最新を取得しておく（未保存の場合のみ）
    if not get_saved_news_url():
        latest = await fetch_latest_news()
        if latest:
            save_news_url(latest['url'])
            print(f"初期設定: 最新ニュースを保存しました ({latest['url']})")

    check_new_news.start()
    end_of_month_reminder.start()

@tree.command(name="news_register", description="このチャンネルにチュウニズムの最新ニュースを通知します。")
async def news_register(interaction: discord.Interaction):
    channels = get_registered_channels()
    if interaction.channel_id in channels:
        await interaction.response.send_message("えへへ、このチャンネルはもう私とリンク接続済みだよ～！", ephemeral=True)
        return
        
    channels.append(interaction.channel_id)
    save_registered_channels(channels)
    await interaction.response.send_message("✅ リンク接続完了！これからここに最新ニュースをバンバンお届けしちゃうよ～！")

@tree.command(name="news_unregister", description="このチャンネルでのチュウニズムニュース通知を解除します。")
async def news_unregister(interaction: discord.Interaction):
    channels = get_registered_channels()
    if interaction.channel_id not in channels:
        await interaction.response.send_message("あれれ？このチャンネルはまだ私とリンク接続してないみたい！", ephemeral=True)
        return
        
    channels.remove(interaction.channel_id)
    save_registered_channels(channels)
    await interaction.response.send_message("❌ リンク接続を解除したよ！今までありがとう、プレイヤーさん！またいつでも呼んでね～！")

@tasks.loop(minutes=10)
async def check_new_news():
    """10分に1回実行されるニュース監視タスク"""
    global is_in_error_state
    print("公式サイト: 最新ニュースのチェックを開始します...")
    try:
        latest = await fetch_latest_news()
        
        # 正常に取得できた場合、エラー状態をリセット
        if is_in_error_state:
            print("公式サイト: エラー状態から復旧しました。")
            is_in_error_state = False

        if not latest:
            print("公式サイト: ニュースが取得できませんでした。")
            return

        saved_url = get_saved_news_url()

        if saved_url == latest['url']:
            print(f"公式サイト: 新しいニュースはありません (最新URL: {latest['url']})")
            return

        # 新規ニュース発見
        channels = get_registered_channels()
        if not channels:
            print(f"公式サイト: 新規ニュース({latest['title']})を発見しましたが、通知先のチャンネルが登録されていません。")
            save_news_url(latest['url'])
            return

        print(f"公式サイト: 新規ニュースを検出！ ({latest['title']})")

        # ニュースタイトルから不要な文字列(NEW!!など)を除去して整形
        clean_title = latest['title'].replace('NEW!!', '').strip()
        
        # 投稿メッセージ (例: 2026.04.01 (水) 「タイトル」)
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
            title="CHUNITHM公式サイトに新しいニュースが掲載されたよ～！",
            description=f"{formatted_title}\n{latest['url']}",
            color=0x00A2E8 # チュウニズムっぽい色
        )
        
        if latest.get('image_url'):
            embed.set_image(url=latest['image_url'])

        # 登録されている全チャンネルに送信
        valid_channels = []
        for channel_id in channels:
            channel = discord_client.get_channel(channel_id)
            if channel is None:
                print(f"エラー: チャンネルが見つかりませんでした。リストから除外します。ID: {channel_id}")
                continue
            
            try:
                await channel.send(embed=embed)
                valid_channels.append(channel_id)
            except discord.errors.Forbidden:
                print(f"エラー: チャンネルへの送信権限がありません。リストから除外します。ID: {channel_id}")
            except Exception as e:
                print(f"チャンネル {channel_id} への送信中にエラーが発生しました: {e}")
                # 一時的なエラーの可能性もあるため、リストからは除外しない
                valid_channels.append(channel_id)

        # 権限エラー等で無効になったチャンネルがあれば更新
        if len(valid_channels) != len(channels):
            save_registered_channels(valid_channels)
            
        save_news_url(latest['url'])
        print("Discord: 全チャンネルへの送信処理が完了しました。")

    except Exception as e:
        error_msg = f"ニュースチェック中にエラーが発生しました: {e}"
        print(error_msg)
        
        # エラー状態でない場合のみDiscordに通知
        if not is_in_error_state:
            channels = get_registered_channels()
            if channels:
                for channel_id in channels:
                    try:
                        channel = discord_client.get_channel(channel_id)
                        if channel:
                            await channel.send(f"⚠️ **エラー通知** ⚠️\nうぇ～ん、公式サイトの監視中にエラーが起きちゃったみたい……。\n```\n{e}\n```")
                    except Exception as inner_e:
                        print(f"チャンネル {channel_id} へのエラー通知の送信失敗: {inner_e}")
                
                # 通知後にエラー状態をオンにする
                is_in_error_state = True
        else:
            print("※現在エラー状態が継続中のため、Discordへの再通知をスキップしました。")

@tasks.loop(time=datetime.time(hour=12, minute=0, tzinfo=JST))
async def end_of_month_reminder():
    """月末から3日前の昼12時に実行されるリマインドタスク"""
    now = datetime.datetime.now(JST)
    last_day = calendar.monthrange(now.year, now.month)[1]
    
    # 月末から3日前かどうかを判定 (例: 31日の場合は28日)
    if now.day == last_day - 3:
        print("月末リマインド: 条件を満たしたため、通知を送信します。")
        channels = get_registered_channels()
        if not channels:
            return
            
        embed = discord.Embed(
            title="🔔 月末のリマインドだよ～！",
            description=(
                "やっほ～！　プレイヤーさん！\n"
                "月末が近づいてるので、CHUNITHM-NETのアイテム交換所でチケットやスタチュウのpt交換予定がある方はお忘れなく～！\n\n"
                "交換忘れちゃったらもったいないからね！"
            ),
            color=0xFFB6C1 # ユニちゃんをイメージしたピンク色
        )
        embed.set_image(url="attachment://shop_entrance.png")
        
        valid_channels = []
        for channel_id in channels:
            channel = discord_client.get_channel(channel_id)
            if channel is None:
                continue
            
            try:
                file = discord.File("figs/shop_entrance.png", filename="shop_entrance.png")
                await channel.send(file=file, embed=embed)
                valid_channels.append(channel_id)
            except discord.errors.Forbidden:
                print(f"月末リマインド: チャンネルへの送信権限がありません (ID: {channel_id})")
            except Exception as e:
                print(f"月末リマインド: チャンネル {channel_id} への送信中にエラーが発生しました: {e}")
                valid_channels.append(channel_id)
                
        # 権限エラー等で無効になったチャンネルがあれば更新
        if len(valid_channels) != len(channels):
            save_registered_channels(valid_channels)

if __name__ == '__main__':
    if not DISCORD_TOKEN:
        print("エラー: .env に DISCORD_TOKEN が設定されていません。")
    else:
        discord_client.run(DISCORD_TOKEN)
