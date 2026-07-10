import httpx
from bs4 import BeautifulSoup
import asyncio
import os
import traceback
import datetime
import traceback

# スクレイピング対象のURLと出力先ファイル名のマッピング
TARGETS = {
    "https://reiwa.f5.si/chunirec_all.json": "prompt_cache/chunithm_const_data.txt",
    # "https://wikiwiki.jp/chunithmwiki/": "prompt_cache/chunithm_wiki_data.txt",
    # "https://info-chunithm.sega.jp/12052/": "prompt_cache/yuni_character_data.txt",
    # "https://wiki.yjsnpi.nu/wiki/%E6%B7%AB%E5%A4%A2%E8%AA%9E%E9%8C%B2": "prompt_cache/yjsp_wiki_data.txt"
}

async def fetch_and_save(url, filename):
    print(f"[{filename}] 取得を開始します: {url}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper()
        
        response = scraper.get(url, timeout=30)
        
        if response.status_code == 200:
            if "chunirec_all.json" in url:
                # JSONデータを読み込み、曲名と難易度・定数だけを抽出して圧縮
                import json
                # BOM（Byte Order Mark）が付いている場合に対処するため手動でデコード
                text_data = response.content.decode('utf-8-sig')
                data = json.loads(text_data)
                lines = []
                for song in data:
                    title = song.get("meta", {}).get("title", "")
                    diffs = song.get("data", {})
                    diff_texts = []
                    for diff_name, diff_data in diffs.items():
                        lvl = diff_data.get("level")
                        const = diff_data.get("const")
                        if lvl and const:
                            diff_texts.append(f"{diff_name}:{lvl}({const})")
                    if title and diff_texts:
                        lines.append(f"【{title}】 " + " / ".join(diff_texts))
                
                cleaned_text = "\n".join(lines)
            else:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # スクリプトやスタイルシートを除去して純粋なテキストを抽出
                for script in soup(["script", "style", "noscript", "meta", "header", "footer", "nav"]):
                    script.extract()
                
                text = soup.get_text(separator='\n')
                
                # 空行や余分な空白を削除して整理
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                cleaned_text = '\n'.join(chunk for chunk in chunks if chunk)
                
                if "chunithm_wiki_data.txt" in filename:
                    start_idx = cleaned_text.find("今月の日替わりボーナス")
                    end_idx = cleaned_text.find("不具合情報")
                    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                        cleaned_text = cleaned_text[start_idx:end_idx].strip()
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(cleaned_text)
                
            print(f"[{filename}] 保存完了 ({len(cleaned_text)} 文字)")
        else:
            print(f"[{filename}] エラー: HTTP {response.status_code}")
            
    except Exception as e:
        print(f"[{filename}] 取得中に例外が発生しました:")
        traceback.print_exc()

async def run_scraping():
    print("スクレイピング処理を開始します...")
    for url, filename in TARGETS.items():
        await fetch_and_save(url, filename)
        await asyncio.sleep(3) # サーバー負荷軽減のため待機
    print("すべてのスクレイピング処理が完了しました。")

async def main():
    JST = datetime.timezone(datetime.timedelta(hours=9), 'JST')
    
    # 起動時にまず1回実行
    print(f"[{datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')}] 起動時のスクレイピングを実行します...")
    await run_scraping()
    
    while True:
        # 現在のJST時刻を取得
        now = datetime.datetime.now(JST)
        
        # 次の深夜0時（翌日の00:00:00 JST）を計算
        tomorrow = now + datetime.timedelta(days=1)
        next_run = datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0, tzinfo=JST)
        
        # 待機する秒数を計算
        sleep_seconds = (next_run - now).total_seconds()
        
        print(f"次のスクレイピングは {next_run.strftime('%Y-%m-%d %H:%M:%S')} に実行されます。")
        print(f"約 {int(sleep_seconds / 3600)}時間 {int((sleep_seconds % 3600) / 60)}分 待機します...")
        
        # 指定秒数待機
        await asyncio.sleep(sleep_seconds)
        
        # 深夜0時になったので実行
        print(f"[{datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')}] 定期スクレイピングを開始します...")
        await run_scraping()

if __name__ == "__main__":
    asyncio.run(main())
