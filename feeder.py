import asyncio
import json
import os
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pyrogram import Client
from pyrogram.types import Message

# ================= DUMMY HEALTH SERVER (Render ke liye zaroori) =================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Feeder is running!")

    def log_message(self, format, *args):
        return

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

# ================= CONFIGURATION =================
API_ID = int(os.environ.get("API_ID", 30029090))
API_HASH = os.environ.get("API_HASH", "814108c4c350f0fbf4925e3928d3fdb0")
SESSION_STRING = os.environ.get("SESSION_STRING", "")

BOT_USERNAME = os.environ.get("BOT_USERNAME", "@Notescarrier_url_upload_bot")
JSON_FILE = "nirman2026.json"
TAG_PREFIX = "[NIRMAN_DONE]"

def clean_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', '', name)
    return " ".join(name.split()).strip()

def load_tasks_from_json(filepath: str) -> list:
    if not os.path.exists(filepath):
        print(f"❌ File not found: {filepath}")
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    batch_title = data.get("title", "Nirman Batch 2026")
    tasks = []

    for subject in data.get("subjects", []):
        topic = subject.get("name", "General")
        for lec in subject.get("lectures", []):
            lec_no = lec.get("lectureNo", "")
            lec_title = lec.get("title", "Lecture")
            
            # Video Task
            v_url = lec.get("videoUrl")
            if v_url and v_url.strip():
                v_title = f"{topic} - Lec {lec_no}: {lec_title}" if lec_no else f"{topic} - {lec_title}"
                v_title = clean_filename(v_title)
                tasks.append({
                    "type": "video",
                    "url": v_url.strip(),
                    "title": v_title,
                    "topic": topic,
                    "batch": batch_title,
                    "filename": f"{v_title}.mp4"
                })
                
            # PDF Task
            p_url = lec.get("pdfUrl")
            if p_url and p_url.strip():
                p_title = lec.get("pdfTitle") or f"{lec_title} Notes"
                full_p_title = clean_filename(f"{topic} - {p_title}")
                tasks.append({
                    "type": "pdf",
                    "url": p_url.strip(),
                    "title": full_p_title,
                    "topic": topic,
                    "batch": batch_title,
                    "filename": f"{full_p_title}.pdf"
                })

    return tasks

async def get_completed_urls(client: Client) -> set:
    """Telegram Saved Messages ('me') se completed URLs read karta hai."""
    completed = set()
    print("🔄 Telegram Saved Messages se progress fetch kar rahe hain...")
    try:
        async for msg in client.get_chat_history("me", limit=2000):
            if msg.text and msg.text.startswith(TAG_PREFIX):
                url = msg.text.replace(TAG_PREFIX, "").strip()
                if url:
                    completed.add(url)
    except Exception as e:
        print(f"⚠️ Saved Messages read error: {e}")
    print(f"📊 Pehle se completed items: {len(completed)}")
    return completed

async def mark_url_completed(client: Client, url: str):
    """URL complete hone par Saved Messages me marker store karta hai."""
    try:
        await client.send_message("me", f"{TAG_PREFIX} {url}")
    except Exception as e:
        print(f"⚠️ Saved Messages write error: {e}")

async def wait_for_bot_response(client: Client, bot_username: str, trigger_msg_id: int, timeout: int = 1800) -> bool:
    """Uploader bot ke confirmation reply ka wait karta hai."""
    elapsed = 0
    poll_interval = 5

    while elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        try:
            async for msg in client.get_chat_history(bot_username, limit=5):
                if msg.id <= trigger_msg_id:
                    continue

                if msg.video or msg.document or msg.media:
                    return True

                text = (msg.text or msg.caption or "").lower()
                if any(w in text for w in ["uploaded successfully", "upload complete", "sent to channel", "done"]):
                    return True

                if any(w in text for w in ["error", "failed", "cannot download", "timed out", "file too large"]):
                    print(f"   ⚠️ Bot error: {text[:100]}")
                    return False
        except Exception as e:
            print(f"   ⚠️ Poll error: {e}")

    print("   ⏳ Timeout: Bot ne 30 min me response nahi diya.")
    return False

async def main():
    if not SESSION_STRING:
        print("❌ Error: SESSION_STRING environment variable set nahi hai!")
        return

    # Start health server thread for Render
    threading.Thread(target=run_health_server, daemon=True).start()
    print(f"🌐 Health server started on port {os.environ.get('PORT', 8080)}")

    tasks = load_tasks_from_json(JSON_FILE)
    print(f"📊 Total items in JSON: {len(tasks)}")
    if not tasks:
        print("❌ Koi task nahi mila, check karein json file path.")
        return

    app = Client("feeder_user", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

    async with app:
        me = await app.get_me()
        print(f"👤 Logged in as: {me.first_name} (@{me.username or me.id})")

        completed_urls = await get_completed_urls(app)
        pending_tasks = [t for t in tasks if t["url"] not in completed_urls]
        print(f"🚀 Pending items to upload: {len(pending_tasks)}")

        for idx, task in enumerate(pending_tasks, 1):
            print(f"\n[{idx}/{len(pending_tasks)}] 📤 Sending: {task['filename']}")
            print(f"    Topic: {task['topic']} | Type: {task['type']}")

            payload = f"{task['url']} | {task['filename']} | {task['topic']} | {task['batch']}"

            try:
                sent_msg = await app.send_message(BOT_USERNAME, payload)
            except Exception as e:
                print(f"❌ Send message failed: {e}")
                await asyncio.sleep(10)
                continue

            print("    ⏳ Waiting for uploader bot to download & upload...")
            success = await wait_for_bot_response(app, BOT_USERNAME, sent_msg.id)

            if success:
                print("    ✅ Upload confirmed!")
                await mark_url_completed(app, task["url"])
                completed_urls.add(task["url"])
            else:
                print("    ❌ Failed or timeout on this item. Skipping to next...")

            await asyncio.sleep(5)

        print("\n🎉 All pending tasks processed!")

if __name__ == "__main__":
    asyncio.run(main())
