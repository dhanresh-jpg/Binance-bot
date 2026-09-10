import threading
import time
from flask import Flask
import requests

VIP_BOT_TOKEN = "8997353064:AAET77QbnubzGm2DsKNv_566bEkpfaSUVPE"
FREE_BOT_TOKEN = "8842407289:AAFCBqQp4ZNzPW81G8NCA7gcSLVCaUheKiM"

VIP_CHANNEL_ID = "-1003836756507"
FREE_CHANNEL_ID = "-1003924921868"

app = Flask(__name__)


@app.route("/")
def home():
  return "Bot is active and running!"


def send_telegram_msg(bot_token, chat_id, message_text):
  url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
  payload = {
      "chat_id": chat_id,
      "text": message_text,
      "parse_mode": "Markdown",
      "disable_web_page_preview": True,
  }
  try:
    res = requests.post(url, json=payload, timeout=10)
    data = res.json()
    return data
  except Exception as e:
    print(f"Error sending message: {e}")
    return {"ok": False, "description": str(e)}


def test_free_channel():
  time.sleep(5)
  # VIP Channel Test
  send_telegram_msg(
      VIP_BOT_TOKEN, VIP_CHANNEL_ID, "✅ *VIP Bot*: Connection Active!"
  )

  # Free Channel Test
  res = send_telegram_msg(
      FREE_BOT_TOKEN, FREE_CHANNEL_ID, "🚀 *FREE Channel*: Test Message!"
  )

  # If Free channel fails, notify VIP channel with exact reason
  if not res or not res.get("ok"):
    error_desc = res.get("description", "Unknown Error") if res else "No response"
    send_telegram_msg(
        VIP_BOT_TOKEN,
        VIP_CHANNEL_ID,
        f"⚠️ *Free Channel Error Alert*:\n`{error_desc}`\n\nCheck Free Bot Admin"
        " permissions or Free Channel ID.",
    )


threading.Thread(target=test_free_channel, daemon=True).start()

if __name__ == "__main__":
  app.run(host="0.0.0.0", port=10000)
