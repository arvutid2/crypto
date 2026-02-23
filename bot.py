import os
import time
import requests
import pandas as pd
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

# Ühendus Supabase'iga
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)

SYMBOL = "BTCUSDT"

def get_crypto_data():
    url = f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval=1h&limit=50"
    data = requests.get(url).json()
    df = pd.DataFrame(data, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'])
    df['close'] = df['close'].astype(float)
    return df

def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_portfolio():
    res = supabase.table("portfolio").select("*").eq("id", 1).execute()
    return res.data[0]

def update_portfolio(usdt, btc, price):
    total = usdt + (btc * price)
    supabase.table("portfolio").update({
        "usdt_balance": usdt,
        "btc_balance": btc,
        "total_value_usdt": total,
        "last_updated": "now()"
    }).eq("id", 1).execute()

def run_bot():
    print("🚀 Bot õpib ja kaupleb...")
    
    while True:
        try:
            df = get_crypto_data()
            current_price = df['close'].iloc[-1]
            rsi = calculate_rsi(df).iloc[-1]
            portfolio = get_portfolio()
            
            usdt = float(portfolio['usdt_balance'])
            btc = float(portfolio['btc_balance'])
            
            action = "HOLD"
            summary = f"RSI: {round(rsi, 2)}. "
            
            # --- LIHTNE ÕPPIMISLOOGIKA (AI ALGE) ---
            # Bot vaatab trendi (viimased 3 tundi)
            last_3_hours = df['close'].tail(3).mean()
            is_uptrend = current_price > last_3_hours

            if rsi < 35 and usdt > 10:
                # OSTA: Kui RSI on madal ja meil on raha
                btc_to_buy = usdt / current_price
                update_portfolio(0, btc_to_buy, current_price)
                action = "BUY"
                summary += "Otsus: Madal RSI + Trend. Ostsime virtuaalselt BTC."
            
            elif rsi > 65 and btc > 0.0001:
                # MÜÜ: Kui RSI on kõrge ja meil on BTC-d
                usdt_from_sell = btc * current_price
                update_portfolio(usdt_from_sell, 0, current_price)
                action = "SELL"
                summary += "Otsus: Kõrge RSI. Müüsime kasumi lukustamiseks."
            
            else:
                summary += "Ootame paremat hetke (HOLD)."

            # Salvestame logisse
            supabase.table("trade_logs").insert({
                "symbol": SYMBOL,
                "price": current_price,
                "rsi": rsi,
                "action": action,
                "analysis_summary": summary
            }).execute()

            print(f"✅ Hind: {current_price} | RSI: {round(rsi, 1)} | Portfell: {round(usdt + btc * current_price, 2)} USDT")
            
        except Exception as e:
            print(f"❌ Viga: {e}")
            
        time.sleep(60) # Testimiseks 1 minut, hiljem 900 (15 min)

run_bot()