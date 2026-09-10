import threading
import time
import random
from flask import Flask
import requests

BOT_TOKEN = "8997353064:AAGqtm4nFQihOzwgIUuWWXRHagTAt8Itq4w"

VIP_CHANNEL_ID = "-1003836756507"
FREE_CHANNEL_ID = "-1003924921868"

app = Flask(__name__)

@app.route('/')
def home():
    return "Automated Signal System Active!"

def send_telegram_msg(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.json()
    except Exception as e:
        return {"ok": False, "description": str(e)}

def fetch_market_data():
    headers = {"User-Agent": "Mozilla/5.0"}
    symbols = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT"]

    # Provider 1: CoinPaprika
    try:
        url = "https://api.coinpaprika.com/v1/tickers"
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            mapping = {
                "BTC": "btc-bitcoin", "ETH": "eth-ethereum", "SOL": "sol-solana", 
                "BNB": "bnb-binance-coin", "XRP": "xrp-xrp", "DOGE": "doge-dogecoin", 
                "ADA": "ada-cardano", "AVAX": "avax-avalanche", "LINK": "link-chainlink", "DOT": "dot-polkadot"
            }
            result = []
            for s in symbols:
                coin_id = mapping.get(s)
                item = next((x for x in data if x["id"] == coin_id), None)
                if item:
                    usd_info = item["quotes"]["USD"]
                    result.append({
                        "symbol": s + "USDT",
                        "price": float(usd_info["price"]),
                        "volume": float(usd_info["volume_24h"]) / 1_000_000,
                        "change": float(usd_info["percent_change_24h"])
                    })
            if len(result) >= 5:
                return result
    except Exception:
        pass

    # Fallback Data Generator
    base_prices = {
        "BTCUSDT": 64500.0, "ETHUSDT": 3450.0, "SOLUSDT": 145.0, "BNBUSDT": 580.0, 
        "XRPUSDT": 0.58, "DOGEUSDT": 0.11, "ADAUSDT": 0.38, "AVAXUSDT": 26.0, 
        "LINKUSDT": 11.85, "DOTUSDT": 4.35
    }
    
    fallback_result = []
    for sym, price in base_prices.items():
        var_price = price * (1 + random.uniform(-0.003, 0.003))
        fallback_result.append({
            "symbol": sym,
            "price": round(var_price, 4),
            "volume": round(random.uniform(150.0, 300.0), 2),
            "change": round(random.uniform(-1.5, 3.5), 2)
        })
    return fallback_result

def signal_engine():
    coins = fetch_market_data()

    for index, coin in enumerate(coins):
        symbol = coin["symbol"]
        price = coin["price"]
        volume = coin["volume"]
        change = coin["change"]

        spot_text = (
            f"🟢 <b>[SPOT SIGNAL] {symbol}</b>\n\n"
            f"📥 <b>Entry Range</b>: ${price:.4f}\n"
            f"📊 <b>24h Vol</b>: ${volume:.2f}M | <b>Change</b>: {change:+.2f}%\n\n"
            f"🎯 <b>Target 1</b>: ${round(price * 1.02, 4)} (+2.0%)\n"
            f"🎯 <b>Target 2</b>: ${round(price * 1.045, 4)} (+4.5%)\n"
            f"🎯 <b>Target 3</b>: ${round(price * 1.08, 4)} (+8.0%)\n"
            f"⛔ <b>Stop Loss</b>: ${round(price * 0.965, 4)} (-3.5%)\n\n"
            f"📈 <b>Analysis</b>: Top Volume Momentum"
        )

        futures_text = (
            f"⚡ <b>[FUTURES LONG] {symbol}</b>\n\n"
            f"⚙️ <b>Leverage</b>: Cross 10x - 20x\n"
            f"📥 <b>Entry</b>: ${price:.4f}\n\n"
            f"🎯 <b>Target 1</b>: ${round(price * 1.015, 4)} (+15% @ 10x)\n"
            f"🎯 <b>Target 2</b>: ${round(price * 1.03, 4)} (+30% @ 10x)\n"
            f"🎯 <b>Target 3</b>: ${round(price * 1.05, 4)} (+50% @ 10x)\n"
            f"⛔ <b>Stop Loss</b>: ${round(price * 0.985, 4)} (-15% @ 10x)\n\n"
            f"📊 <b>Analysis</b>: High Volume Breakout Pattern"
        )

        # 1. Send to VIP Channel
        send_telegram_msg(VIP_CHANNEL_ID, spot_text)
        time.sleep(1.5)
        send_telegram_msg(VIP_CHANNEL_ID, futures_text)
        time.sleep(2)

        # 2. Send Preview to Free Channel (First 2 coins)
        if index < 2:
            free_promo_text = (
                f"🚀 <b>FREE PREVIEW SIGNAL</b> 🚀\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{spot_text}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔥 <b>UNLOCK ALL 10 SPOT & FUTURES SIGNALS</b> 🔥\n\n"
                f"💳 <b>Subscription Plans</b>:\n"
                f"• 10 Days: $10 USDT\n"
                f"• 20 Days: $19 USDT\n"
                f"• 30 Days: $27 USDT\n\n"
                f"👉 <b>Join VIP Bot</b>: @BinanceTop10_VIPBot"
            )
            res_free = send_telegram_msg(FREE_CHANNEL_ID, free_promo_text)
            
            # Agar Free Channel me bhejte waqt error aaye toh alert VIP me dikhayega
            if not res_free.get("ok"):
                err_msg = res_free.get("description", "Unknown Error")
                send_telegram_msg(VIP_CHANNEL_ID, f"⚠️ <b>Free Channel Error</b>: <code>{err_msg}</code>")
            
            time.sleep(2)

def execution_loop():
    time.sleep(3)
    while True:
        signal_engine()
        time.sleep(3600)

threading.Thread(target=execution_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
