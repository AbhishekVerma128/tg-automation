import asyncio
import json
import os
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pyrogram import Client
from pyrogram.types import Message

# ================= CONFIGURATION =================
API_ID = int(os.environ.get("API_ID", 30029090))
API_HASH = os.environ.get("API_HASH", "814108c4c350f0fbf4925e3928d3fdb0")

BOT_USERNAME = os.environ.get("BOT_USERNAME", "@Notescarrier_url_upload_bot")
JSON_FILE = os.environ.get("JSON_FILE", "nirman2026.json")
COMPLETED_FILE = os.environ.get("COMPLETED_FILE", "completed_nirman.json")
# =================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Nirman Feeder service is alive!")

    def log_message(self, format, *args):
        pass

def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

def load_local_completed():
    if os.path.exists(COMPLETED_FILE):
        try:
            with open(COMPLETED_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_local_completed(completed_set):
    with open(COMPLETED_FILE, "w", encoding="utf-8") as f:
        json.dump(list(completed_set), f, indent=2, ensure_ascii=False)

async def sync_completed_from_saved_messages(app: Client, completed_set: set):
    """Server crash ya restart hone par Telegram Saved Messages se progress sync karta hai."""
    print("🔄 Checking Saved Messages for previously completed items...")
    count = 0
    try:
        async for msg in app.get_chat_history("me", limit=1000):
            text = msg.text or ""
            if "#NIRMAN_DONE:" in text:
                match = re.search(r"#NIRMAN_DONE:(\S+)", text)
                if match:
                    completed_set.add(match.group(1))
                    count += 1
        print(f"📥 Recovered {count} completed items from Saved Messages.")
    except Exception as e:
        print(f"⚠️ Saved Messages sync notice: {e}")

async def mark_done_in_saved_messages(app: Client, key: str, title: str):
    """Crash persistence: Saved Messages me save karta hai taaki redeploy par dobara upload na ho."""
    try:
        await app.send_message("me", f"✅ Uploaded:\n{title}\n\n#NIRMAN_DONE:{key}")
    except Exception as e:
        print(f"⚠️ Could not write to Saved Messages: {e}")

async def main():
    app = Client(
        "nirman_feeder_session",
        api_id=API_ID,
        api_hash=API_HASH
    )

    completed = load_local_completed()

    if not os.path.exists(JSON_FILE):
        print(f"❌ Error: {JSON_FILE} nahi mila! Usi folder me rakhein.")
        return

    with open(JSON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    batch_title = f"{data.get('title', 'NIRMAN BATCH 2026')} BY {data.get('instructor', 'NEERAJ SIR')}".upper()

    tasks = []
    for subject in data.get("subjects", []):
        s_name = subject.get("name", "Science").upper()
        for lec in subject.get("lectures", []):
            lec_no = lec.get("lectureNo", 0)
            raw_title = lec.get("title", f"Class {lec_no}")
            clean_title = re.sub(r'[\\/*?:"<>|]', "", raw_title).strip()

            # 1. Video
            if lec.get("videoUrl"):
                v_filename = f"{s_name} CLASS {lec_no:02d} - {clean_title}.mp4"
                tasks.append({
                    "key": f"{subject.get('id')}_lec_{lec_no}_video",
                    "url": lec["videoUrl"],
                    "filename": v_filename,
                    "topic": f"{s_name} VIDEOS",
                    "batch": batch_title,
                    "type": "video"
                })

            # 2. PDF
            if lec.get("pdfUrl"):
                p_filename = f"{s_name} CLASS {lec_no:02d} - {clean_title} NOTES.pdf"
                tasks.append({
                    "key": f"{subject.get('id')}_lec_{lec_no}_pdf",
                    "url": lec["pdfUrl"],
                    "filename": p_filename,
                    "topic": f"{s_name} CLASS NOTES PDF",
                    "batch": batch_title,
                    "type": "pdf"
                })

    print(f"📊 Total items in Nirman JSON: {len(tasks)}")

    async with app:
        await sync_completed_from_saved_messages(app, completed)
        save_local_completed(completed)

        bot = await app.get_users(BOT_USERNAME)
        print(f"🤖 Connected to Bot: @{bot.username} ({bot.first_name}) [ID: {bot.id}]")

        for idx, task in enumerate(tasks, 1):
            key = task["key"]
            if key in completed:
                continue

            print("\n" + "=" * 60)
            print(f"🚀 [{idx}/{len(tasks)}] Uploading {task['type'].upper()}: {task['filename']}")
            print(f"🔗 URL: {task['url']}")

            # Format: URL | Filename | Topic | Batch
            msg_text = f"{task['url']} | {task['filename']} | {task['topic']} | {task['batch']}"

            sent_msg = await app.send_message(chat_id=bot.id, text=msg_text)
            print(f"✅ Sent to bot! (Msg ID: {sent_msg.id})")
            print("⏳ Waiting for bot to download, process thumbnail and upload to channel...")

            finished = False
            wait_seconds = 0
            max_wait = 1800  # 30 mins max per file

            while not finished and wait_seconds < max_wait:
                await asyncio.sleep(5)
                wait_seconds += 5

                async for reply in app.get_chat_history(chat_id=bot.id, limit=5):
                    if reply.id > sent_msg.id:
                        text_lower = (reply.text or reply.caption or "").lower()

                        if reply.video or reply.document or "success" in text_lower or "uploaded" in text_lower:
                            print(f"🎉 Success detected! [Reply ID: {reply.id}]")
                            completed.add(key)
                            save_local_completed(completed)
                            await mark_done_in_saved_messages(app, key, task["filename"])
                            finished = True
                            break

                        if "error" in text_lower or "failed" in text_lower:
                            print(f"❌ Bot error reported: {reply.text or reply.caption}")
                            finished = True
                            break

                if wait_seconds % 30 == 0 and not finished:
                    print(f"⏱️ Waiting... ({wait_seconds // 60}m elapsed)")

            if not finished:
                print(f"⚠️ Timeout: {task['filename']} did not complete within 30 mins.")

            await asyncio.sleep(3)

        print("\n🎊 Sabhi Nirman Batch lectures aur PDFs process ho chuke hain!")

if __name__ == "__main__":
    if os.environ.get("PORT"):
        threading.Thread(target=start_dummy_server, daemon=True).start()
    asyncio.run(main())
