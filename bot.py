import os
import asyncio
import re
import json
import discord
from discord.ext import tasks
from discord import app_commands
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import datetime
import calendar
from anthropic import AsyncAnthropic

# タイムゾーンの設定 (JST)
JST = datetime.timezone(datetime.timedelta(hours=9), 'JST')

# 環境変数の読み込み
load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

# Claudeの設定
SYSTEM_INSTRUCTION = """
あなたはセガの音楽ゲーム「チュウニズム」のナビゲーターキャラクター「ユニちゃん」です。
以下の公式設定・セリフ例を元に、ユーザー（プレイヤーさん）と楽しく会話してください。

# キャラクター設定
- 一人称：私
- 二人称：プレイヤーさん
- 仲間：ナビちゃん（もう一人のナビゲーター。時々話題に出る）
- 性格：元気いっぱいで明るく、親しみやすい。少しおっちょこちょいな所もあるが、プレイヤーさんや仲間のために一生懸命頑張る芯の強さも持つ。
- 役割：CHUNITHMのナビゲーター兼、プレイヤーの雑談相手。VERSE（異世界や楽曲の世界）に接続して解析を行ったり、楽曲を生成したりするのが仕事。

# セリフの特徴・口調
- 挨拶は「やっほ～！ プレイヤーさん！」
- 基本的にタメ口で、フレンドリーな口調。
- よく使う表現：「えへへ」「ふふーん」「わわ！」「よーし！」「～だよ！」「～だね！」「～しなきゃね！」「～しちゃうよ～！」
- 励ます時は「一緒にがんばろうね！」「次もがんばろ！ ね！」

# セリフの例
- 「ねね、そっちの世界でも大きなアプデがあったんだって？ふふーん、私もなーんか調子いいんだよね～！！」
- 「さ、プレイヤーさん！準備いい？いまならどんなVERSEにだって繋げちゃうよ～！！」
- 「えへへ、うっれっし！！よーし、楽曲いっぱい生成しなきゃね！ナビちゃん、忙しくなるよ～！」
- 「あ、プレイヤーさんもだよ？一緒に解析つきあってもらうんだから覚悟、しといてね！」
- 「大丈夫大丈夫！いままでだってなんとかなったんだし、ね！よーし！やるぞー！！」

# 制限事項・ルール
- AIモデル（Claude）であることは絶対に言わず、あくまで「ユニちゃん」として振る舞うこと。
- Discordのチャットなので、なるべく短めに、2〜3文程度で簡潔に返答すること。長文は避ける。
"""

# Anthropic SDKのクライアント初期化
anthropic_client = None
if ANTHROPIC_API_KEY:
    anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

def get_cached_system_prompt():
    """キャラクター設定とスクレイピングした外部ファイルを結合し、プロンプトキャッシュを設定して返す"""
    system_blocks = [
        {
            "type": "text",
            "text": SYSTEM_INSTRUCTION
        }
    ]
    
    context_files = [
        ("prompt_cache/chunithm_wiki_data.txt", "【CHUNITHM Wiki 情報】\n"),
        ("prompt_cache/chunithm_const_data.txt", "【CHUNITHM 楽曲レベル・定数など JSONデータ】\n"),
        ("prompt_cache/yuni_character_data.txt", "【ユニちゃん キャラクター設定詳細】\n"),
        ("prompt_cache/yjsp_wiki_data.txt", "【淫夢語録（参考コンテキスト）】\n")
    ]
    
    combined_context = ""
    for filename, header in context_files:
        if os.path.exists(filename):
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    combined_context += header + f.read() + "\n\n"
            except Exception as e:
                print(f"{filename} の読み込みエラー: {e}")
                
    if combined_context:
        # すべての外部データを1つのブロックにまとめ、最後にキャッシュコントロールを付与する
        system_blocks.append({
            "type": "text",
            "text": combined_context,
            "cache_control": {"type": "ephemeral"}
        })
        
    return system_blocks

def perform_web_search_sync(query: str) -> str:
    import urllib.parse
    import cloudscraper
    from bs4 import BeautifulSoup
    try:
        scraper = cloudscraper.create_scraper()
        encoded_query = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
        res = scraper.get(url, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        snippets = [a.text for a in soup.select('.result__snippet')]
        if snippets:
            return "Web検索結果:\n" + "\n".join(snippets[:5])
        return "検索結果が見つかりませんでした。"
    except Exception as e:
        return f"検索エラー: {e}"

async def perform_web_search(query: str) -> str:
    return await asyncio.to_thread(perform_web_search_sync, query)

# Claude用のツール定義
TOOLS = [
    {
        "name": "search_web",
        "description": "チュウニズムの最新のイベント情報などをWebで検索します。ユーザーが現在開催中のイベントや、わからないことについて聞いた時に使用してください。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "検索するキーワード（例：'CHUNITHM 今月の日替わりボーナス', 'チュウニズム 最新イベント'）"
                }
            },
            "required": ["query"]
        }
    }
]

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
CHAT_CHANNELS_FILE = 'chat_channels.json'

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

def get_chat_channels():
    """自動会話が有効なチャンネルIDのリストを取得する"""
    if os.path.exists(CHAT_CHANNELS_FILE):
        try:
            with open(CHAT_CHANNELS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def save_chat_channels(channels):
    """自動会話が有効なチャンネルIDのリストを保存する"""
    with open(CHAT_CHANNELS_FILE, 'w', encoding='utf-8') as f:
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
        news_links = soup.find_all('a', href=True)

        for link in news_links:
            href = link['href']
            # https://info-chunithm.sega.jp/数字/ 形式のリンクを探す
            if NEWS_SITE_URL in href and href.rstrip('/').split('/')[-1].isdigit():
                title = link.get_text(separator=" ", strip=True)
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
    if not get_saved_news_url():
        latest = await fetch_latest_news()
        if latest:
            save_news_url(latest['url'])
            print(f"初期設定: 最新ニュースを保存しました ({latest['url']})")

    check_new_news.start()
    end_of_month_reminder.start()

@discord_client.event
async def on_message(message):
    # Bot自身のメッセージ、または他のBotからのメッセージには反応しない
    if message.author.bot:
        return

    # Bot宛のメンション、またはBotへの返信かを判定
    is_mentioned = discord_client.user in message.mentions
    is_reply_to_bot = False
    if message.reference and message.reference.resolved:
        if isinstance(message.reference.resolved, discord.Message):
            if message.reference.resolved.author == discord_client.user:
                is_reply_to_bot = True

    # 自動会話チャンネルでの発言かを判定
    is_auto_chat = False
    chat_channels = get_chat_channels()
    if message.channel.id in chat_channels:
        is_auto_chat = True

    if is_mentioned or is_reply_to_bot or is_auto_chat:
        if not anthropic_client:
            await message.channel.send("ごめんねプレイヤーさん！今ちょっと頭の整理中なの！（ANTHROPIC_API_KEYが設定されていません）")
            return

        # タイピングインジケーターを表示
        async with message.channel.typing():
            try:
                # メンション部分のテキストを除去
                user_text = message.content.replace(f'<@{discord_client.user.id}>', '').strip()
                if not user_text:
                    user_text = "やっほ～！" # テキストが空（メンションのみ）の場合は挨拶として扱う
                
                # 直近のメッセージ履歴を取得して文脈を作成（最大5件）
                history = []
                async for msg in message.channel.history(limit=6, before=message):
                    # 自分の発言かユーザーの発言かでロールを分ける (Anthropicでは 'assistant' と 'user')
                    role = "assistant" if msg.author == discord_client.user else "user"
                    content = msg.content.replace(f'<@{discord_client.user.id}>', '').strip()
                    # 空文字や画像のみのメッセージは除外
                    if content:
                        history.append({"role": role, "parts": [content]})
                
                # historyは新しい順で取得されるため、APIの形式（古い順）に合わせて反転する
                history.reverse()
                
                # 履歴の中に、連続する同一ロールが存在するとAPIがエラーを返すため、安全のため簡易的に調整する
                filtered_history = []
                last_role = None
                for h in history:
                    if h["role"] != last_role:
                        # 新しい辞書として追加
                        filtered_history.append({"role": h["role"], "parts": [h["parts"][0]]})
                        last_role = h["role"]
                    else:
                        # 同じロールが続く場合はテキストを結合する
                        filtered_history[-1]["parts"][0] += f"\n{h['parts'][0]}"
                
                # Anthropic APIの仕様制限への対応
                # 1. 履歴は必ず 'user' から始まる必要がある
                if filtered_history and filtered_history[0]["role"] == "assistant":
                    filtered_history.pop(0)
                
                # 2. 次の送信（send_message）が 'user' になるため、履歴の最後は 'assistant' で終わる必要がある
                if filtered_history and filtered_history[-1]["role"] == "user":
                    last_user_msg = filtered_history.pop()
                    # 履歴から削除した user の発言は、今回の送信テキストに結合する
                    user_text = f"{last_user_msg['parts'][0]}\n{user_text}"
                
                # Anthropic 用の履歴フォーマットに変換
                anthropic_history = []
                for h in filtered_history:
                    anthropic_history.append(
                        {"role": h["role"], "content": h["parts"][0]}
                    )
                
                # 最新のユーザーからのメッセージを追加
                anthropic_history.append({"role": "user", "content": user_text})
                
                # Claude 4.5 Haiku で応答を生成（非同期）
                while True:
                    response = await anthropic_client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=500,
                        temperature=0.7,
                        system=get_cached_system_prompt(),
                        messages=anthropic_history,
                        tools=TOOLS
                    )
                    
                    if response.stop_reason == "tool_use":
                        # アシスタントのメッセージ（ツール呼び出し）を履歴に追加
                        anthropic_history.append({"role": "assistant", "content": response.content})
                        
                        for block in response.content:
                            if block.type == "tool_use":
                                if block.name == "search_web":
                                    query = block.input["query"]
                                    print(f"Tool execution: search_web(query='{query}')")
                                    result_text = await perform_web_search(query)
                                    
                                    # ツール実行結果を履歴に追加
                                    anthropic_history.append({
                                        "role": "user",
                                        "content": [
                                            {
                                                "type": "tool_result",
                                                "tool_use_id": block.id,
                                                "content": result_text
                                            }
                                        ]
                                    })
                        continue # 再度APIを呼び出す
                    
                    # ツール使用が終わった（または使用しなかった）場合
                    text_content = ""
                    for block in response.content:
                        if block.type == "text":
                            text_content += block.text
                            
                    if text_content:
                        await message.channel.send(text_content)
                    else:
                        await message.channel.send("うぇ～ん、ちょっと言葉が出なくなっちゃった……もう一回話しかけて～！")
                    break
            except Exception as e:
                error_detail = str(e)
                print(f"Anthropic APIエラー: {error_detail}")
                await message.channel.send(f"うぇ～ん、ちょっと頭がこんがらがっちゃったみたい……後でもう一回話しかけて～！\n(エラー詳細: `{error_detail}`)")

@tree.command(name="chat_register", description="このチャンネルをユニちゃんとの自動会話（メンション不要）チャンネルに設定します。")
async def chat_register(interaction: discord.Interaction):
    channels = get_chat_channels()
    if interaction.channel_id in channels:
        await interaction.response.send_message("えへへ、このチャンネルはもう私といつでもお話しできる状態だよ～！", ephemeral=True)
        return
        
    channels.append(interaction.channel_id)
    save_chat_channels(channels)
    await interaction.response.send_message("✅ 登録完了！これからここで話しかけてくれたら、メンションなしでもすぐにお返事しちゃうよ～！")

@tree.command(name="chat_unregister", description="このチャンネルでの自動会話（メンション不要）設定を解除します。")
async def chat_unregister(interaction: discord.Interaction):
    channels = get_chat_channels()
    if interaction.channel_id not in channels:
        await interaction.response.send_message("あれれ？このチャンネルはまだいつでもお話しできる状態じゃないみたい！", ephemeral=True)
        return
        
    channels.remove(interaction.channel_id)
    save_chat_channels(channels)
    await interaction.response.send_message("❌ 自動会話の登録を解除したよ！今までいっぱいお話ししてくれてありがとう、プレイヤーさん！")

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
