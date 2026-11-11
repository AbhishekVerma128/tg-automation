import asyncio
import json
import os
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pyrogram import Client
from pyrogram.types import Message

# ================= CONFIGURATION =================
API_ID = 30029090
API_HASH = "814108c4c350f0fbf4925e3928d3fdb0"

BOT_USERNAME = "@Notescarrier_url_upload_bot"
JSON_FILE = "parmar4.0.json"
COMPLETED_FILE = "completed.json"
# =================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Feeder service is alive!")

    def log_message(self, format, *args):
        pass

def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

def normalize_name(name: str):
    """Names ko match karne ke liye clean aur lowercase karta hai."""
    if not name:
        return ""
    # Extension (.mp4, .pdf etc) hatao
    name = re.sub(r'\.(mp4|pdf|mkv|webm)$', '', name, flags=re.IGNORECASE)
    # Special characters hatao
    name = re.sub(r'[^a-zA-Z0-9]', '', name)
    return name.lower().strip()

def extract_direct_url(raw_url: str):
    if not raw_url:
        return None
    if "youtube.com" in raw_url or "youtu.be" in raw_url or len(raw_url) == 11:
        return None
    
    # 1. Videos ke liye ?watch= aur PDFs ke liye ?dl= dono ko extract karein
    match = re.search(r"[?&](?:watch|dl)=([a-f0-9]+)", raw_url)
    if match:
        file_id = match.group(1)
        return f"https://fs1bold-frost-42033611-da83ade26f8d.herokuapp.com/dl/{file_id}"
    
    # 2. Agar pehle se direct Heroku link ho
    if "herokuapp.com/dl/" in raw_url:
        return raw_url

    # 3. Agar 24-character hex ID url path me ho
    match_hex = re.search(r"/([a-f0-9]{24})(?:[/?#]|$)", raw_url)
    if match_hex:
        file_id = match_hex.group(1)
        return f"https://fs1bold-frost-42033611-da83ade26f8d.herokuapp.com/dl/{file_id}"
    
    if raw_url.startswith("http"):
        return raw_url
    return None


def load_completed_local():
    if os.path.exists(COMPLETED_FILE):
        try:
            with open(COMPLETED_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_completed_local(completed_set):
    try:
        with open(COMPLETED_FILE, "w", encoding="utf-8") as f:
            json.dump(list(completed_set), f, indent=2, ensure_ascii=False)
    except Exception:
        pass

async def scan_existing_uploads_from_bot(app: Client, bot_id: int):
    """Bot ke chat history se pehle se uploaded saari files detect karta hai."""
    found_names = set()
    print("🔍 Bot ke chat se purani uploaded files scan ho rahi hain...")
    try:
        count = 0
        async for msg in app.get_chat_history(bot_id, limit=3000):
            count += 1
            # 1. Bot ne jo document ya video send ki hai
            if msg.document and msg.document.file_name:
                found_names.add(normalize_name(msg.document.file_name))
            elif msg.video and msg.video.file_name:
                found_names.add(normalize_name(msg.video.file_name))
            
            # 2. Jo 'URL | Title' message aapne bot ko bheja tha
            if msg.from_user and msg.from_user.is_self and msg.text and "|" in msg.text:
                parts = msg.text.split("|", 1)
                if len(parts) == 2:
                    found_names.add(normalize_name(parts[1].strip()))

        print(f"✅ Bot chat scan complete ({count} messages checked). Total {len(found_names)} purani files identify hui!")
    except Exception as e:
        print(f"⚠️ Bot chat scan error: {e}")
    return found_names

async def sync_completed_from_saved_messages(app: Client):
    cloud_completed = set()
    try:
        async for msg in app.get_chat_history("me", limit=1000):
            text = msg.text or ""
            if text.startswith("#FEEDER_DONE:"):
                key = text.replace("#FEEDER_DONE:", "", 1).strip()
                if key:
                    cloud_completed.add(normalize_name(key))
    except Exception:
        pass
    return cloud_completed

def get_all_tasks(data: dict):
    tasks = []

    # 1. Format: parmar4.0.json (lectures + notes)
    if "lectures" in data or "notes" in data:
        for subject in data.get("lectures", []):
            subj_name = subject.get("n", "General")
            for item in subject.get("i", []):
                tasks.append({
                    "topic": subj_name,
                    "title": item[0],
                    "url": item[1],
                    "type": "video",
                    "link_type": item[2]
                })

        for subject in data.get("notes", []):
            subj_name = subject.get("n", "General")
            for item in subject.get("i", []):
                title = item[0]
                clean_t = re.sub(r'\.mp4$', '', title, flags=re.IGNORECASE).strip()
                if not clean_t.lower().endswith(".pdf"):
                    clean_t += ".pdf"
                tasks.append({
                    "topic": subj_name,
                    "title": clean_t,
                    "url": item[1],
                    "type": "pdf",
                    "link_type": item[2] if len(item) > 2 else "d"
                })

    # 2. Format: parmar_maths_organized.json
    elif "chapters" in data:
        for ch in data.get("chapters", []):
            subj_name = ch.get("topic", "General")
            for v in ch.get("videos", []):
                tasks.append({
                    "topic": subj_name,
                    "title": v.get("title", ""),
                    "url": v.get("url", ""),
                    "type": "video",
                    "link_type": "d"
                })
            for p in ch.get("pdfs", []):
                p_title = p.get("title", "")
                clean_t = re.sub(r'\.mp4$', '', p_title, flags=re.IGNORECASE).strip()
                if not clean_t.lower().endswith(".pdf"):
                    clean_t += ".pdf"
                tasks.append({
                    "topic": subj_name,
                    "title": clean_t,
                    "url": p.get("url", ""),
                    "type": "pdf",
                    "link_type": "d"
                })

    return tasks

async def main():
    app = Client(
        "feeder_session",
        api_id=API_ID,
        api_hash=API_HASH
    )

    if not os.path.exists(JSON_FILE):
        print(f"❌ Error: {JSON_FILE} nahi mila! Usi folder me rakhein.")
        return

    with open(JSON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    tasks = get_all_tasks(data)
    print(f"📋 Total items (Videos + PDFs) JSON me: {len(tasks)}")

    async with app:
        bot = await app.get_users(BOT_USERNAME)
        print(f"🤖 Connected to Bot: @{bot.username} ({bot.first_name}) [ID: {bot.id}]")

        # 1. Bot ke chat history se purani uploaded files load karo
        bot_uploaded = await scan_existing_uploads_from_bot(app, bot.id)
        
        # 2. Saved Messages aur local cache load karo
        saved_msg_done = await sync_completed_from_saved_messages(app)
        local_done = {normalize_name(x) for x in load_completed_local()}

        # Sabko combine karke ek master completed set banao
        master_completed = bot_uploaded | saved_msg_done | local_done
        print(f"📦 Total pehle se uploaded files jo skip hongi: {len(master_completed)}")

        for task in tasks:
            subj_name = task["topic"]
            title = task["title"]
            item_type = task["type"]
            item_key = f"{subj_name} - {title}"

            # Smart match: title ya full key match ho toh skip
            norm_key = normalize_name(item_key)
            norm_title = normalize_name(title)
            if norm_key in master_completed or norm_title in master_completed:
                continue

            if task["link_type"] == "y":
                print(f"⏩ Skipping YouTube: {item_key}")
                continue

            direct_url = extract_direct_url(task["url"])
            if not direct_url:
                print(f"⚠️ Invalid URL: {item_key}, skipping...")
                continue

            print("\n" + "=" * 50)
            tag = "📄 [PDF]" if item_type == "pdf" else "🎬 [VIDEO]"
            print(f"🚀 Processing {tag}: {item_key}")
            print(f"🔗 Direct URL: {direct_url}")

            clean_subj = re.sub(r'[\\/*?:"<>|]', "", subj_name)
            clean_name = re.sub(r'[\\/*?:"<>|]', "", title)
            clean_title = f"{clean_subj} - {clean_name}"
            msg_text = f"{direct_url} | {clean_title}"

            sent_msg = await app.send_message(chat_id=bot.id, text=msg_text)
            print(f"✅ Message sent to bot! (Message ID: {sent_msg.id})")
            print("⏳ Waiting for bot to download, convert and upload...")

            finished = False
            wait_seconds = 0
            max_wait = 1800

            while not finished and wait_seconds < max_wait:
                await asyncio.sleep(5)
                wait_seconds += 5

                async for reply in app.get_chat_history(chat_id=bot.id, limit=5):
                    if reply.id > sent_msg.id:
                        if reply.video or reply.document:
                            print(f"🎉 Upload successful! [Msg ID: {reply.id}]")
                            master_completed.add(norm_key)
                            master_completed.add(norm_title)
                            
                            # Local and Telegram backup
                            save_completed_local(master_completed)
                            try:
                                await app.send_message("me", f"#FEEDER_DONE: {clean_title}")
                            except Exception:
                                pass
                                
                            finished = True
                            break
                        
                        text_lower = (reply.text or reply.caption or "").lower()
                        if "error" in text_lower or "failed" in text_lower:
                            print(f"❌ Bot reported error: {reply.text or reply.caption}")
                            finished = True
                            break

                if wait_seconds % 30 == 0 and not finished:
                    print(f"⏱️ Waiting... ({wait_seconds // 60}m elapsed)")

            if not finished:
                print(f"⚠️ Timeout: {item_key} 30 min me complete nahi hua.")

            await asyncio.sleep(3)

        print("\n🎊 Sabhi Videos aur PDFs process ho chuke hain!")

if __name__ == "__main__":
    threading.Thread(target=start_dummy_server, daemon=True).start()
    asyncio.run(main())
