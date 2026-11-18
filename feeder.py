import asyncio
import json
import os
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pyrogram import Client
from pyrogram.types import Message


# ================= DUMMY HEALTH SERVER (Render / Cloud hosting) =================
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

BOT_USERNAME = os.environ.get("BOT_USERNAME", "@notescarrier_video_extractor_bot")
JSON_FILE = "onlyStationMaster.json"
TAG_PREFIX = "[STATION_MASTER_DONE]"


def clean_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', '', name)
    return " ".join(name.split()).strip()


def load_tasks_from_json(filepath: str) -> list:
    if not os.path.exists(filepath):
        print(f"❌ File not found: {filepath}")
        return []

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Top-level key fetch (e.g., "local-9")
    batch_data = next(iter(data.values())) if isinstance(data, dict) else {}

    batch_info = batch_data.get("info", {})
    batch_title = batch_info.get("title", "Station Master Batch 2026")

    # Topic groups list
    topic_groups = batch_data.get("classes", {}).get("classes", [])
    tasks = []

    for topic_group in topic_groups:
        topic_name = topic_group.get("topicName", "General")
        class_items = topic_group.get("classes", [])

        for cls in class_items:
            cls_title = cls.get("title", "Lecture")
            recordings = cls.get("mp4Recordings", [])

            for rec in recordings:
                v_url = rec.get("url", "").strip()
                if not v_url:
                    continue

                v_title = clean_filename(f"{topic_name} - {cls_title}")
                tasks.append({
                    "type": "video",
                    "url": v_url,
                    "title": v_title,
                    "topic": topic_name,
                    "batch": batch_title,
                    "filename": f"{v_title}.mp4"
                })

    return tasks


async def get_completed_items(client: Client, bot_username: str) -> tuple[set, set]:
    """
    1. Saved Messages ('me') se URL & Filename read karta hai.
    2. Bot Chat History se pehle upload ho chuki files detect karke duplicate prevent karta hai.
    """
    completed_urls = set()
    completed_filenames = set()

    print("🔄 Progress sync kar rahe hain (Saved Messages + Bot Chat)...")

    # 1. Saved Messages check
    try:
        async for msg in client.get_chat_history("me", limit=2000):
            if msg.text and msg.text.startswith(TAG_PREFIX):
                content = msg.text.replace(TAG_PREFIX, "").strip()
                if "|" in content:
                    parts = [p.strip() for p in content.split("|", 1)]
                    if parts[0]:
                        completed_urls.add(parts[0])
                    if len(parts) > 1 and parts[1]:
                        completed_filenames.add(parts[1])
                elif content:
                    completed_urls.add(content)
    except Exception as e:
        print(f"⚠️ Saved Messages read error: {e}")

    # 2. Bot Chat History check (Pehle se upload ho chuki files)
    try:
        async for msg in client.get_chat_history(bot_username, limit=500):
            text = msg.text or msg.caption or ""
            match = re.search(r"uploaded to channel!\s*\(`([^`]+)`\)", text, re.I)
            if match:
                f_name = match.group(1).strip()
                completed_filenames.add(f_name)
    except Exception as e:
        print(f"⚠️ Bot chat history scan error: {e}")

    print(f"📊 Pehle se completed videos: {len(completed_urls.union(completed_filenames))}")
    return completed_urls, completed_filenames


async def mark_item_completed(client: Client, url: str, filename: str):
    """URL aur Filename dono ko Saved Messages me store karta hai."""
    try:
        await client.send_message("me", f"{TAG_PREFIX} {url} | {filename}")
    except Exception as e:
        print(f"⚠️ Saved Messages write error: {e}")


async def wait_for_bot_response(client: Client, bot_username: str, trigger_msg_id: int, timeout: int = 1800) -> bool:
    """Uploader bot ke confirmation reply ka wait karta hai."""
    elapsed = 0
    poll_interval = 4

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

                # Exact keywords matching uploader bot's reply
                if any(w in text for w in [
                    "✅",
                    "successfully uploaded",
                    "uploaded to channel",
                    "uploaded successfully",
                    "upload complete",
                    "sent to channel",
                    "done",
                ]):
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

    threading.Thread(target=run_health_server, daemon=True).start()
    print(f"🌐 Health server started on port {os.environ.get('PORT', 8080)}")

    tasks = load_tasks_from_json(JSON_FILE)
    print(f"📊 Total video tasks in JSON: {len(tasks)}")
    if not tasks:
        print("❌ Koi task nahi mila, JSON structure ya path check karein.")
        return

    app = Client("feeder_user", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

    async with app:
        me = await app.get_me()
        print(f"👤 Logged in as: {me.first_name} (@{me.username or me.id})")

        completed_urls, completed_filenames = await get_completed_items(app, BOT_USERNAME)

        # Agar URL ya Filename pehle se completed hai toh skip hoga
        pending_tasks = [
            t for t in tasks
            if t["url"] not in completed_urls and t["filename"] not in completed_filenames
        ]
        print(f"🚀 Pending videos to upload: {len(pending_tasks)}")

        for idx, task in enumerate(pending_tasks, 1):
            print(f"\n[{idx}/{len(pending_tasks)}] 📤 Sending: {task['filename']}")
            print(f"    Topic: {task['topic']} | Type: {task['type']}")

            payload = f"{task['url']} | {task['filename']} | {task['topic']} | {task['batch']}"

            try:
                sent_msg = await app.send_message(BOT_USERNAME, payload)
            except Exception as e:
                print(f"❌ Send message failed: {e}")
                await asyncio.sleep(5)
                continue

            print("    ⏳ Waiting for uploader bot to download & upload...")
            success = await wait_for_bot_response(app, BOT_USERNAME, sent_msg.id)

            if success:
                print("    ✅ Upload confirmed!")
                await mark_item_completed(app, task["url"], task["filename"])
                completed_urls.add(task["url"])
                completed_filenames.add(task["filename"])
            else:
                print("    ❌ Failed or timeout on this item. Skipping to next...")

            await asyncio.sleep(2)

        print("\n🎉 All pending video tasks processed!")


if __name__ == "__main__":
    asyncio.run(main())
