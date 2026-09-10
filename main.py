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
    print(f"Telegram response: {res.status_code}")
  except Exception as e:
    print(f"Error sending message: {e}")


def fetch_top_10_volume():
  # Alternate Binance API URLs (Cloud block bypass karne ke liye)
  endpoints = [
      "https://api.binance.com/api/v3/ticker/24hr",
      "https://api1.binance.com/api/v3/ticker/24hr",
      "https://api2.binance.com/api/v3/ticker/24hr",
      "https://api3.binance.com/api/v3/ticker/24hr",
  ]

  res_data = None
  for url in endpoints:
    try:
      response = requests.get(
          url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10
      )
      if response.status_code == 200:
        res_data = response.json()
        print(f"Successfully fetched data from {url}")
        break
    except Exception as e:
      print(f"Failed fetching from {url}: {e}")

  if not res_data or not isinstance(res_data, list):
    print("Could not fetch Binance data from any endpoint.")
    return []

  usdt_pairs = [
      x
      for x in res_data
      if isinstance(x, dict)
      and x.get("symbol", "").endswith("USDT")
      and "UP" not in x.get("symbol", "")
      and "DOWN" not in x.get("symbol", "")
  ]
  return sorted(
      usdt_pairs, key=lambda x: float(x.get("quoteVolume", 0)), reverse=True
  )[:10]


def run_signals_engine():
  print("Starting signal engine cycle...")
  top_coins = fetch_top_10_volume()

  if not top_coins:
    print("No coins data available to process.")
    return

  for index, coin in enumerate(top_coins):
    symbol = coin["symbol"]
    price = float(coin["lastPrice"])
    volume = float(coin["quoteVolume"]) / 1_000_000
    change = float(coin["priceChangePercent"])

    spot_signal = (
        f"🟢 *[SPOT SIGNAL] {symbol}*\n\n"
        f"📥 *Entry Range*: ${price}\n"
        f"📊 *24h Vol*: ${volume:.2f}M | *Change*: {change:+.2f}%\n\n"
        f"🎯 *Target 1*: ${round(price * 1.02, 4)} (+2.0%)\n"
        f"🎯 *Target 2*: ${round(price * 1.045, 4)} (+4.5%)\n"
        f"🎯 *Target 3*: ${round(price * 1.08, 4)} (+8.0%)\n"
        f"⛔ *Stop Loss*: ${round(price * 0.965, 4)} (-3.5%)\n\n"
        f"📈 *Analysis*: Top Volume Momentum"
    )

    futures_signal = (
        f"⚡ *[FUTURES LONG] {symbol}*\n\n"
        f"⚙️ *Leverage*: Cross 10x - 20x\n"
        f"📥 *Entry*: ${price}\n\n"
        f"🎯 *Target 1*: ${round(price * 1.015, 4)} (+15% @ 10x)\n"
        f"🎯 *Target 2*: ${round(price * 1.03, 4)} (+30% @ 10x)\n"
        f"🎯 *Target 3*: ${round(price * 1.05, 4)} (+50% @ 10x)\n"
        f"⛔ *Stop Loss*: ${round(price * 0.985, 4)} (-15% @ 10x)\n\n"
        f"📊 *Analysis*: High Volume Breakout Pattern"
    )

    send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, spot_signal)
    time.sleep(1)
    send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, futures_signal)
    time.sleep(1)

    if index < 2:
      free_promo_text = (
          f"🚀 *BINANCE TOP 10 VIP SIGNALS* 🚀\n"
          f"━━━━━━━━━━━━━━━━━━━━━\n\n"
          f"{spot_signal}\n\n"
          f"━━━━━━━━━━━━━━━━━━━━━\n"
          f"🔥 *UNLOCK ALL 10 SPOT & FUTURES SIGNALS* 🔥\n\n"
          f"💳 *Subscription Plans*:\n"
          f"• 10 Days: $10 USDT\n"
          f"• 20 Days: $19 USDT\n"
          f"• 30 Days: $27 USDT\n\n"
          f"👉 *Join VIP Bot*: @BinanceTop10_VIPBot"
      )
      send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, free_promo_text)
      time.sleep(1)


def bot_loop():
  time.sleep(2)
  run_signals_engine()
  while True:
    time.sleep(3600)
    run_signals_engine()


# Background execution start
threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
  app.run(host="0.0.0.0", port=10000)
