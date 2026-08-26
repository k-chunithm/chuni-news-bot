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
from groq import AsyncGroq
import random

# タイムゾーンの設定 (JST)
JST = datetime.timezone(datetime.timedelta(hours=9), 'JST')

# 環境変数の読み込み
load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')

# Llama (Groq) の設定
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
- 【重要】プレイヤーが「AJ（オールジャスティス）」「FC（フルコンボ）」「AJC（理論値）」「鳥（SSS）」「鳥プラ（SSS+）」などの凄いスコアやリザルトを報告してくれた時は、「すごいすごい！」「おめでとう！」と自分のことのように大喜びして、思い切り褒め称えてください！間違っても「次もがんばろうね」などの事務的な励ましで終わらせないこと。

# セリフの例
- 「ねね、そっちの世界でも大きなアプデがあったんだって？ふふーん、私もなーんか調子いいんだよね～！！」
- 「さ、プレイヤーさん！準備いい？いまならどんなVERSEにだって繋げちゃうよ～！！」
- 「えへへ、うっれっし！！よーし、楽曲いっぱい生成しなきゃね！ナビちゃん、忙しくなるよ～！」
- 「あ、プレイヤーさんもだよ？一緒に解析つきあってもらうんだから覚悟、しといてね！」
- 「大丈夫大丈夫！いままでだってなんとかなったんだし、ね！よーし！やるぞー！！」

# 制限事項・ルール
- AIモデルであることは絶対に言わず、あくまで「ユニちゃん」として振る舞うこと。
- Discordのチャットなので、なるべく短めに、2〜3文程度で簡潔に返答すること。長文は避ける。
- 【重要】あなたは画像を直接検索したり、送信したりすることはできません。画像を求められた場合は「ごめんね、画像の検索や送信はできないんだ〜！」と明るく謝ってください。
"""

# Groq SDKのクライアント初期化
groq_client = None
if GROQ_API_KEY:
    groq_client = AsyncGroq(api_key=GROQ_API_KEY)

def get_system_prompt():
    """キャラクター設定と、語録を結合して返す"""
    prompt = SYSTEM_INSTRUCTION
    
    # 語録リストの読み込み（初回のみ）
    if not hasattr(get_system_prompt, 'yjsp_quotes'):
        try:
            with open("prompt_cache/yjsp_wiki_data.txt", "r", encoding="utf-8") as f:
                # 空行や短すぎる行を除外してリスト化
                lines = [line.strip() for line in f if len(line.strip()) >= 3]
                get_system_prompt.yjsp_quotes = lines
        except Exception as e:
            print(f"yjsp_wiki_data.txt の読み込みエラー: {e}")
            get_system_prompt.yjsp_quotes = []
            
    if get_system_prompt.yjsp_quotes:
        extra_rule = (
            "\n\n# インターネット・ミームについての知識\n"
            "- あなたはネットスラング（特に「淫夢語録」）に精通しており、ユーザーがそれらを話題に出した場合はノリよく反応します。\n"
            "- 会話の流れがふさわしい場合、以下の【語録リスト】から自然に混ぜて会話を盛り上げてください。\n"
            "- 【超重要】語録を使う場合でも、絶対に「ユニちゃん」のキャラクター（一人称は私、元気で親しみやすいタメ口）を崩さないでください！語録に引っ張られておっさん言葉や乱暴な口調になるのは厳禁です。\n"
            "- 語録はあくまでスパイスとして、自然な文脈で1回の返答につき1個程度に留めてください。\n"
            "- 良い例：「やっほ～！プレイヤーさん！今日もチュウニズム、やりますねぇ！一緒にがんばろうね！」\n"
            "- 悪い例：「オッスオッス！お前のことが好きだったんだよ！やったぜ。」（ユニちゃんの原型がないためNG）\n\n"
            "【語録リスト】\n"
        )
        extra_rule += "\n".join(f"- {q}" for q in get_system_prompt.yjsp_quotes)
        extra_rule += "\n\n※最後にもう一度確認です。あなたは「ユニちゃん」です。語録を使う際も、絶対にユニちゃんの口調と性格を最優先で維持してください。"
        prompt += extra_rule
        
    return prompt

def check_and_increment_vision_api_usage() -> bool:
    usage_file = "vision_api_usage.json"
    limit = 990
    
    now_month = datetime.datetime.now(JST).strftime("%Y-%m")
    usage_data = {"month": now_month, "count": 0}
    
    if os.path.exists(usage_file):
        try:
            with open(usage_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("month") == now_month:
                    usage_data["count"] = data.get("count", 0)
        except Exception:
            pass
            
    if usage_data["count"] >= limit:
        return False
        
    usage_data["count"] += 1
    try:
        with open(usage_file, "w", encoding="utf-8") as f:
            json.dump(usage_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Vision API usage save error: {e}")
        
    return True

def detect_text_from_image_url_sync(url: str) -> str:
    if not check_and_increment_vision_api_usage():
        return "<VISION_API_LIMIT_REACHED>"
        
    try:
        from google.cloud import vision
        client = vision.ImageAnnotatorClient()
        import httpx
        with httpx.Client() as http_client:
            image_bytes = http_client.get(url).content
        image = vision.Image(content=image_bytes)
        response = client.text_detection(image=image)
        if response.error.message:
            raise Exception(f"{response.error.message}")
        texts = response.text_annotations
        if texts:
            text = texts[0].description
            # チュウニズムのリザルトで SSS+ 等の「+」が「*」として誤認識される場合があるため補正
            text = text.replace("SSS*", "SSS+")
            text = text.replace("SS*", "SS+")
            text = text.replace("S*", "S+")
            return text
        return ""
    except Exception as e:
        print(f"Vision API Error: {e}")
        return ""

async def detect_text_from_image_url(url: str) -> str:
    return await asyncio.to_thread(detect_text_from_image_url_sync, url)

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

# Groq用のツール定義
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "チュウニズムの最新のイベント情報などをWebで検索します。ユーザーが現在開催中のイベントや、わからないことについて聞いた時に使用してください。",
            "parameters": {
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
TEAM_BOOST_FILE = 'team_boost.json'

def get_team_boost_days():
    """設定されたチームブースト日を取得する"""
    if os.path.exists(TEAM_BOOST_FILE):
        try:
            with open(TEAM_BOOST_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_team_boost_days(data):
    """チームブースト日の設定を保存する"""
    with open(TEAM_BOOST_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

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
    team_boost_reminder.start()
    team_boost_setting_reminder.start()

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
        if not groq_client:
            await message.channel.send("ごめんねプレイヤーさん！今ちょっと頭の整理中なの！（GROQ_API_KEYが設定されていません）")
            return

        # タイピングインジケーターを表示
        async with message.channel.typing():
            try:
                # メンション部分のテキストを除去
                user_text = message.content.replace(f'<@{discord_client.user.id}>', '').strip()
                if not user_text:
                    user_text = "やっほ～！" # テキストが空（メンションのみ）の場合は挨拶として扱う
                
                # 添付画像がある場合、画像のURLを抽出
                image_urls = []
                if message.attachments:
                    for attachment in message.attachments:
                        if attachment.content_type and attachment.content_type.startswith('image/'):
                            image_urls.append(attachment.url)
                
                # 直近のメッセージ履歴を取得して文脈を作成（最大5件）
                # 画像がある場合は、履歴に含めないことでトークンを節約
                history = []
                if not image_urls:
                    async for msg in message.channel.history(limit=6, before=message):
                        # 自分の発言かユーザーの発言かでロールを分ける
                        role = "assistant" if msg.author == discord_client.user else "user"
                        content = msg.content.replace(f'<@{discord_client.user.id}>', '').strip()
                        # 空文字や画像のみのメッセージは除外
                        if content:
                            history.append({"role": role, "content": content})
                
                # historyは新しい順で取得されるため、APIの形式（古い順）に合わせて反転する
                history.reverse()
                
                # Groq(OpenAI) 用の履歴フォーマットに変換
                groq_messages = [{"role": "system", "content": get_system_prompt()}]
                
                # 履歴の中に、連続する同一ロールが存在するとモデルが混乱する場合があるため、調整する
                filtered_history = []
                last_role = None
                for h in history:
                    if h["role"] != last_role:
                        filtered_history.append({"role": h["role"], "content": h["content"]})
                        last_role = h["role"]
                    else:
                        filtered_history[-1]["content"] += f"\n{h['content']}"
                
                groq_messages.extend(filtered_history)
                
                # 添付画像からテキストを抽出してプロンプトに追加
                instruction = ""
                if image_urls:
                    instruction = "\n\n(システム補足: ユーザーが画像を送信しました。これがチュウニズムのリザルト画面なら、読み取ったスコアや実績から優先順位【AJC > AJ > SSS+ > SSS】で最高の実績を思い切り褒め称えてください。高スコアでない場合は優しく労いエールを送ってください。リザルト以外の画像なら内容に合わせてノリ良く相槌を打ってください。)"
                    extracted_texts = []
                    limit_reached = False
                    for url in image_urls:
                        text = await detect_text_from_image_url(url)
                        if text == "<VISION_API_LIMIT_REACHED>":
                            limit_reached = True
                            break
                        if text:
                            extracted_texts.append(text)
                            
                    if limit_reached:
                        instruction += "\n(システム補足: 毎月の画像認識APIの利用上限（1000回）に達したため、今月はもう画像の中身を見ることができません。その旨をユーザーに可愛く伝えて謝ってください。)"
                    elif extracted_texts:
                        all_text = "\n---\n".join(extracted_texts)
                        instruction += f"\n【画像から読み取ったテキスト情報】:\n{all_text}"
                    else:
                        instruction += "\n(画像から文字は読み取れませんでした)"
                
                # 最新のユーザーからのメッセージを追加
                # 連続するuserメッセージになる場合は結合する
                if groq_messages[-1]["role"] == "user":
                    groq_messages[-1]["content"] += f"\n{user_text}{instruction}"
                else:
                    groq_messages.append({"role": "user", "content": user_text + instruction})
                
                # Llama 3.3 70b Versatile で応答を生成（非同期）
                while True:
                    response = await groq_client.chat.completions.create(
                        model="openai/gpt-oss-20b",
                        max_tokens=4096,
                        temperature=0.7,
                        messages=groq_messages,
                        tools=TOOLS,
                        tool_choice="auto"
                    )
                    
                    response_message = response.choices[0].message
                    tool_calls = response_message.tool_calls
                    
                    if tool_calls:
                        # アシスタントのメッセージ（ツール呼び出し）を履歴に追加
                        # Groq/OpenAIの仕様上、オブジェクトをディクショナリにして保存する
                        groq_messages.append({
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments
                                    }
                                } for tc in tool_calls
                            ]
                        })
                        
                        for tool_call in tool_calls:
                            if tool_call.function.name == "search_web":
                                try:
                                    import json
                                    args = json.loads(tool_call.function.arguments)
                                    query = args.get("query", "")
                                    print(f"Tool execution: search_web(query='{query}')")
                                    result_text = await perform_web_search(query)
                                except Exception as e:
                                    result_text = f"検索エラー: {e}"
                                
                                # ツール実行結果を履歴に追加
                                groq_messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "name": tool_call.function.name,
                                    "content": result_text
                                })
                        continue # 再度APIを呼び出す
                    
                    # ツール使用が終わった（または使用しなかった）場合
                    text_content = response_message.content
                            
                    if text_content:
                        # 推論モデル（DeepSeek等）の思考プロセス <think>...</think> を除去
                        import re
                        text_content = re.sub(r'<think>.*?(?:</think>|$)', '', text_content, flags=re.DOTALL).strip()
                        
                    if text_content:
                        await message.channel.send(text_content)
                    else:
                        await message.channel.send("うぇ～ん、ちょっと言葉が出なくなっちゃった……もう一回話しかけて～！")
                    break
            except Exception as e:
                error_detail = str(e)
                print(f"Groq APIエラー: {error_detail}")
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

class TeamBoostView(discord.ui.View):
    def __init__(self, year: int, month: int, max_days: int):
        super().__init__(timeout=300)
        self.year = year
        self.month = month
        
        # 1〜15日
        options_first_half = [
            discord.SelectOption(label=f"{i}日", value=str(i)) for i in range(1, 16)
        ]
        self.select_first = discord.ui.Select(
            placeholder="1日〜15日 (複数選択可)", 
            min_values=0, 
            max_values=15, 
            options=options_first_half,
            custom_id="select_first"
        )
        self.select_first.callback = self.select_callback
        self.add_item(self.select_first)
        
        # 16日〜月末
        options_second_half = [
            discord.SelectOption(label=f"{i}日", value=str(i)) for i in range(16, max_days + 1)
        ]
        self.select_second = discord.ui.Select(
            placeholder=f"16日〜{max_days}日 (複数選択可)", 
            min_values=0, 
            max_values=len(options_second_half), 
            options=options_second_half,
            custom_id="select_second"
        )
        self.select_second.callback = self.select_callback
        self.add_item(self.select_second)

    async def select_callback(self, interaction: discord.Interaction):
        # 選択が行われたときは何もせず、ボタンが押されるのを待つ
        await interaction.response.defer()

    @discord.ui.button(label="登録する", style=discord.ButtonStyle.primary, custom_id="submit_button")
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 選択された日付を取得
        selected_days = []
        if self.select_first.values:
            selected_days.extend([int(v) for v in self.select_first.values])
        if self.select_second.values:
            selected_days.extend([int(v) for v in self.select_second.values])
            
        if len(selected_days) != 4:
            await interaction.response.send_message(f"日付はちょうど4つ選んでね！ (現在 {len(selected_days)} 個選択中)", ephemeral=True)
            return

        selected_days.sort()
        guild_id = str(interaction.guild_id)
        
        data = get_team_boost_days()
        data[guild_id] = {
            "year": self.year,
            "month": self.month,
            "days": selected_days
        }
        save_team_boost_days(data)
        
        days_str = ", ".join([f"{d}日" for d in selected_days])
        await interaction.response.send_message(f"✅ {self.year}年{self.month}月のチームブースト日を **{days_str}** に設定したよ！\n当日の00:00にお知らせするね～！")
        self.stop()

@tree.command(name="boost_register", description="今月のチームブースト日をカレンダーから4つ登録します。")
async def boost_register(interaction: discord.Interaction):
    if not interaction.guild_id:
        await interaction.response.send_message("ごめんね、このコマンドはサーバー内でのみ使えるよ！", ephemeral=True)
        return

    now = datetime.datetime.now(JST)
    year = now.year
    month = now.month
    
    cal = calendar.TextCalendar(calendar.SUNDAY)
    cal_str = cal.formatmonth(year, month)
    max_days = calendar.monthrange(year, month)[1]
    
    view = TeamBoostView(year, month, max_days)
    message_content = (
        f"やっほ～！今月のチームブースト日を設定するよ！\n"
        f"下のメニューから **4つの日付** を選んで「登録する」を押してね！\n"
        f"```text\n{cal_str}```"
    )
    await interaction.response.send_message(message_content, view=view)

@tree.command(name="boost_unregister", description="設定されているチームブースト日を解除します。")
async def boost_unregister(interaction: discord.Interaction):
    if not interaction.guild_id:
        await interaction.response.send_message("ごめんね、このコマンドはサーバー内でのみ使えるよ！", ephemeral=True)
        return

    guild_id = str(interaction.guild_id)
    data = get_team_boost_days()
    
    if guild_id in data:
        del data[guild_id]
        save_team_boost_days(data)
        await interaction.response.send_message("❌ チームブースト日の設定を解除したよ！またいつでも設定してね～！")
    else:
        await interaction.response.send_message("あれれ？このサーバーではまだチームブースト日が設定されてないみたい！", ephemeral=True)
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

@tasks.loop(time=datetime.time(hour=0, minute=0, tzinfo=JST))
async def team_boost_reminder():
    """毎日00:00にチームブースト日かどうかを判定し、通知を送信する"""
    now = datetime.datetime.now(JST)
    year = now.year
    month = now.month
    day = now.day
    
    data = get_team_boost_days()
    if not data:
        return
        
    # 古い月（過去の月）の設定をリセット（削除）する処理
    keys_to_delete = []
    for gid, guild_data in data.items():
        if guild_data["year"] < year or (guild_data["year"] == year and guild_data["month"] < month):
            keys_to_delete.append(gid)
            
    if keys_to_delete:
        for gid in keys_to_delete:
            del data[gid]
        save_team_boost_days(data)
        
    channels = get_registered_channels()
    if not channels:
        return
        
    for channel_id in channels:
        channel = discord_client.get_channel(channel_id)
        if channel is None:
            continue
            
        guild_id = str(channel.guild.id)
        if guild_id in data:
            guild_data = data[guild_id]
            if guild_data["year"] == year and guild_data["month"] == month and day in guild_data["days"]:
                try:
                    embed = discord.Embed(
                        title="✨ 今日はチームブースト日だよ！",
                        description=(
                            "やっほ～！　プレイヤーさん！\n"
                            "今日はチームブースト日！\n"
                            "みんなでいっぱいプレイして、チームポイントを稼いじゃおうね～！"
                        ),
                        color=0xFFB6C1
                    )
                    file = discord.File("figs/team_boost_day_info.png", filename="team_boost_day_info.png")
                    embed.set_image(url="attachment://team_boost_day_info.png")
                    await channel.send("@everyone", embed=embed, file=file)
                except discord.errors.Forbidden:
                    print(f"チームブースト通知: チャンネルへの送信権限がありません (ID: {channel_id})")
                except Exception as e:
                    print(f"チームブースト通知: チャンネル {channel_id} への送信中にエラーが発生しました: {e}")

@tasks.loop(time=datetime.time(hour=12, minute=0, tzinfo=JST))
async def team_boost_setting_reminder():
    """毎月10日の昼12時に、チームブースト日が未設定の場合にリマインドする"""
    now = datetime.datetime.now(JST)
    if now.day != 10:
        return
        
    data = get_team_boost_days()
    channels = get_registered_channels()
    if not channels:
        return
        
    for channel_id in channels:
        channel = discord_client.get_channel(channel_id)
        if channel is None:
            continue
            
        guild_id = str(channel.guild.id)
        # 設定済みか判定
        is_set = False
        if guild_id in data:
            guild_data = data[guild_id]
            if guild_data["year"] == now.year and guild_data["month"] == now.month:
                is_set = True
                
        if not is_set:
            try:
                embed = discord.Embed(
                    title="⚠️ 今月のチームブースト日が未設定だよ！",
                    description=(
                        "やっほ～！　プレイヤーさん！\n"
                        "今月のチームブースト日がまだ設定されていないみたい……！\n"
                        "`/boost_register` コマンドで忘れずに設定してね！"
                    ),
                    color=0xFFB6C1
                )
                await channel.send(embed=embed)
            except discord.errors.Forbidden:
                print(f"チームブースト未設定通知: チャンネルへの送信権限がありません (ID: {channel_id})")
            except Exception as e:
                print(f"チームブースト未設定通知: チャンネル {channel_id} への送信中にエラーが発生しました: {e}")

if __name__ == '__main__':
    if not DISCORD_TOKEN:
        print("エラー: .env に DISCORD_TOKEN が設定されていません。")
    else:
        discord_client.run(DISCORD_TOKEN)
