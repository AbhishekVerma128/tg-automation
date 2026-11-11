import asyncio
import json
import os
import re
from pyrogram import Client
from pyrogram.types import Message

# ================= CONFIGURATION =================
API_ID = 30029090
API_HASH = "814108c4c350f0fbf4925e3928d3fdb0"

# Apne URL Uploader bot ka username yahan dalein (bina @ ke ya @ ke sath)
BOT_USERNAME = "@Notescarrier_url_upload_bot"  # e.g. "my_url_uploader_bot"
JSON_FILE = "parmar4.0.json"
COMPLETED_FILE = "completed.json"
# =================================================

def extract_direct_url(raw_url: str):
    """
    Blogspot watch URL se Heroku ka direct media URL extract karta hai.
    YouTube links ko skip karne ke liye None return karta hai.
    """
    if "youtube.com" in raw_url or "youtu.be" in raw_url or len(raw_url) == 11:
        return None
    
    match = re.search(r"[?&]watch=([a-f0-9]+)", raw_url)
    if match:
        file_id = match.group(1)
        return f"https://fs1bold-frost-42033611-da83ade26f8d.herokuapp.com/dl/{file_id}"
    
    if raw_url.startswith("http"):
        return raw_url
    return None

def load_completed():
    if os.path.exists(COMPLETED_FILE):
        try:
            with open(COMPLETED_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_completed(completed_set):
    with open(COMPLETED_FILE, "w", encoding="utf-8") as f:
        json.dump(list(completed_set), f, indent=2, ensure_ascii=False)

async def main():
    # Local session file 'feeder_session' banegi, Render ke session se clash nahi hogi
    app = Client(
        "feeder_session",
        api_id=API_ID,
        api_hash=API_HASH
    )

    completed = load_completed()
    print(f"📦 Total pehle se completed: {len(completed)}")

    if not os.path.exists(JSON_FILE):
        print(f"❌ Error: {JSON_FILE} nahi mila! Usi folder me rakhein jahan ye script hai.")
        return

    with open(JSON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    async with app:
        bot = await app.get_users(BOT_USERNAME)
        print(f"🤖 Connected to Bot: @{bot.username} ({bot.first_name}) [ID: {bot.id}]")

        for subject in data.get("lectures", []):
            subj_name = subject.get("n", "General")
            items = subject.get("i", [])

            for item in items:
                title, raw_link, link_type = item[0], item[1], item[2]
                item_key = f"{subj_name} - {title}"

                if item_key in completed:
                    continue

                if link_type == "y":
                    print(f"⏩ Skipping YouTube: {item_key}")
                    continue

                direct_url = extract_direct_url(raw_link)
                if not direct_url:
                    print(f"⚠️ Invalid URL: {item_key}, skipping...")
                    continue

                print("\n" + "=" * 50)
                print(f"🚀 Processing: {item_key}")
                print(f"🔗 Direct URL: {direct_url}")

                clean_title = re.sub(r'[\\/*?:"<>|]', "", f"{subj_name} - {title}")
                msg_text = f"{direct_url} | {clean_title}"

                # 1. Bot ko URL | Title bhejte hain
                sent_msg = await app.send_message(chat_id=bot.id, text=msg_text)
                print(f"✅ Message sent to bot! (Message ID: {sent_msg.id})")
                print("⏳ Waiting for bot to download, convert and upload...")

                # 2. Wait karein jab tak bot video/document bhej na de
                finished = False
                wait_seconds = 0
                max_wait = 1800  # 30 minute timeout

                while not finished and wait_seconds < max_wait:
                    await asyncio.sleep(5)
                    wait_seconds += 5

                    async for reply in app.get_chat_history(chat_id=bot.id, limit=5):
                        if reply.id > sent_msg.id:
                            # Bot ne document ya video bheja
                            if reply.video or reply.document:
                                print(f"🎉 Upload successful! [Msg ID: {reply.id}]")
                                completed.add(item_key)
                                save_completed(completed)
                                finished = True
                                break
                            
                            # Bot ne error report kiya
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

        print("\n🎊 Sabhi lectures process ho chuke hain!")

if __name__ == "__main__":
    asyncio.run(main())
