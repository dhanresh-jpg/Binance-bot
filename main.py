
import time
import requests

VIP_BOT_TOKEN = "8997353064:AAET77QbnubzGm2DsKNv_566bEkpfaSUVPE"
FREE_BOT_TOKEN = "8842407289:AAFCBqQp4ZNzPW81G8NCA7gcSLVCaUheKiM"

VIP_CHANNEL_ID = "-1003836756507"
FREE_CHANNEL_ID = "-1003924921868"


def send_telegram_msg(bot_token, chat_id, message_text):
  url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
  payload = {
      "chat_id": chat_id,
      "text": message_text,
      "parse_mode": "Markdown",
      "disable_web_page_preview": True,
  }
  try:
    requests.post(url, json=payload)
  except Exception as e:
    print(f"Error sending message: {e}")


def fetch_top_10_volume():
  url = "https://api.binance.com/api/v3/ticker/24hr"
  response = requests.get(url)
  res = response.json()

  # Ensure API response is valid list
  if not isinstance(res, list):
    print("API Response Error:", res)
    return []

  usdt_pairs = [
      x
      for x in res
      if isinstance(x, dict)
      and x.get("symbol", "").endswith("USDT")
      and "UP" not in x.get("symbol", "")
      and "DOWN" not in x.get("symbol", "")
  ]
  sorted_pairs = sorted(
      usdt_pairs, key=lambda x: float(x.get("quoteVolume", 0)), reverse=True
  )[:10]

  return sorted_pairs


def run_signals_engine():
  top_coins = fetch_top_10_volume()

  if not top_coins:
    print("No coins fetched.")
    return

  for index, coin in enumerate(top_coins):
    symbol = coin["symbol"]
    price = float(coin["lastPrice"])
    volume = float(coin["quoteVolume"]) / 1_000_000
    change = float(coin["priceChangePercent"])

    spot_tp1 = round(price * 1.02, 4)
    spot_tp2 = round(price * 1.045, 4)
    spot_tp3 = round(price * 1.08, 4)
    spot_sl = round(price * 0.965, 4)

    spot_signal = (
        f"🟢 *[SPOT SIGNAL] {symbol}*\n\n"
        f"📥 *Entry Range*: ${price}\n"
        f"📊 *24h Vol*: ${volume:.2f}M | *Change*: {change:+.2f}%\n\n"
        f"🎯 *Target 1*: ${spot_tp1} (+2.0%)\n"
        f"🎯 *Target 2*: ${spot_tp2} (+4.5%)\n"
        f"🎯 *Target 3*: ${spot_tp3} (+8.0%)\n"
        f"⛔ *Stop Loss*: ${spot_sl} (-3.5%)\n\n"
        f"📈 *Analysis*: Top Volume Momentum + RSI Recovery"
    )

    fut_tp1 = round(price * 1.015, 4)
    fut_tp2 = round(price * 1.03, 4)
    fut_tp3 = round(price * 1.05, 4)
    fut_sl = round(price * 0.985, 4)

    futures_signal = (
        f"⚡ *[FUTURES LONG] {symbol}*\n\n"
        f"⚙️ *Leverage*: Cross 10x - 20x\n"
        f"📥 *Entry*: ${price}\n\n"
        f"🎯 *Target 1*: ${fut_tp1} (+15% @ 10x)\n"
        f"🎯 *Target 2*: ${fut_tp2} (+30% @ 10x)\n"
        f"🎯 *Target 3*: ${fut_tp3} (+50% @ 10x)\n"
        f"⛔ *Stop Loss*: ${fut_sl} (-15% @ 10x)\n\n"
        f"📊 *Analysis*: High Volume Breakout Pattern"
    )

    send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, spot_signal)
    time.sleep(1)
    send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, futures_signal)
    time.sleep(2)

    if index < 2:
      free_promo_text = (
          f"🔥 *FREE VIP PREVIEW SIGNAL* 🔥\n\n"
          f"{spot_signal}\n\n"
          f"-----------------------------------\n"
          f"🚀 *Get 10+ Daily Signals in VIP Channel!*\n"
          f"💳 *Subscription Plans*:\n"
          f"• 10 Days: $10 USDT\n"
          f"• 20 Days: $19 USDT\n"
          f"• 30 Days: $27 USDT\n\n"
          f"👉 *Join VIP Bot*: @BinanceTop10_VIPBot"
      )
      send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, free_promo_text)
      time.sleep(2)


if __name__ == "__main__":
  print("Starting signals engine...")
  while True:
    try:
      run_signals_engine()
      print("All signals sent! Waiting for next schedule (1 hour)...")
    except Exception as e:
      print(f"Error occurred: {e}")

    # Har 1 ghante baad run hoga
    time.sleep(3600)
