import os
import time
import requests
import pandas as pd
import numpy as np
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
SYMBOL = "BTCUSDT"

def get_fear_and_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/").json()
        return int(r['data'][0]['value'])
    except: return 50

def get_data(limit=150):
    url = f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval=1h&limit={limit}"
    data = requests.get(url).json()
    df = pd.DataFrame(data, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'])
    df[['open', 'high', 'low', 'close', 'vol']] = df[['open', 'high', 'low', 'close', 'vol']].astype(float)
    return df

def add_indicators(df):
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['rsi'] = 100 - (100 / (1 + gain / loss))
    
    # Bollinger Bands
    df['sma20'] = df['close'].rolling(window=20).mean()
    df['std20'] = df['close'].rolling(window=20).std()
    df['lower_band'] = df['sma20'] - (df['std20'] * 2)
    df['upper_band'] = df['sma20'] + (df['std20'] * 2)

    # EMA-d trendi jaoks
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    # ATR (Volatiilsus stop-lossi jaoks)
    df['high_low'] = df['high'] - df['low']
    df['atr'] = df['high_low'].rolling(window=14).mean()
    
    return df

def run_super_bot():
    print(f"💎 SUPER-BOT KÄIVITATUD: {SYMBOL}")
    
    # ÕPPIMISE JA STRATEEGIA SEADED
    target_rsi_buy = 32.0
    trailing_stop_price = 0.0
    entry_price = 0.0
    last_balance = 10000.0

    while True:
        try:
            df = add_indicators(get_data(100))
            fng = get_fear_and_greed()
            curr = df.iloc[-1]
            price = curr['close']
            
            portfolio = supabase.table("portfolio").select("*").eq("id", 1).execute().data[0]
            usdt = float(portfolio['usdt_balance'])
            btc = float(portfolio['btc_balance'])
            total_now = usdt + (btc * price)

            # --- ISEÕPPIMINE: KORRIGEERIME KONSERVATIIVSUST ---
            if total_now < last_balance * 0.995: # Kui kaotasime 0.5%
                target_rsi_buy = max(25.0, target_rsi_buy - 0.2) # Muutu rangemaks
                print(f"🛡️ Konservatiivsus tõusis: Uus RSI target {round(target_rsi_buy, 1)}")
            elif total_now > last_balance * 1.005: # Kui võitsime 0.5%
                target_rsi_buy = min(35.0, target_rsi_buy + 0.1) # Muutu julgemaks
            
            last_balance = total_now

            action = "HOLD"
            reason = "Ootel"

            # --- OSTU LOOGIKA (Super-Bot filtrid) ---
            if usdt > 10:
                # Osta kui: RSI on madal JA hind on BB põhja lähedal JA EMA trend ei ole järsult alla
                if (curr['rsi'] < target_rsi_buy or price <= curr['lower_band']) and (price > curr['ema50']):
                    action = "BUY"
                    entry_price = price
                    trailing_stop_price = price * 0.98 # Algne stop loss 2%
                    btc_to_buy = usdt / price
                    supabase.table("portfolio").update({"usdt_balance": 0, "btc_balance": btc_to_buy}).eq("id", 1).execute()
                    reason = f"BUY: RSI {round(curr['rsi'],1)} | Trend OK"

            # --- MÜÜGI LOOGIKA (Trailing Stop-Loss + Indikaatorid) ---
            elif btc > 0:
                # Uuendame trailing stopi kui hind tõuseb
                if price * 0.98 > trailing_stop_price:
                    trailing_stop_price = price * 0.98
                
                # Müü kui: Hind kukub alla trailing stopi VÕI RSI on liiga kõrge
                if price <= trailing_stop_price:
                    action = "SELL"
                    reason = "TRAILING STOP: Kasum kaitstud / Kahjum piiratud"
                elif curr['rsi'] > 68 or fng > 80:
                    action = "SELL"
                    reason = f"PROFIT SELL: RSI {round(curr['rsi'],1)} või Greed kõrge"
                
                if action == "SELL":
                    usdt_rec = btc * price
                    supabase.table("portfolio").update({"usdt_balance": usdt_rec, "btc_balance": 0}).eq("id", 1).execute()
                    entry_price = 0
                    trailing_stop_price = 0

            # --- ANDMETE SALVESTAMINE ---
            supabase.table("portfolio").update({"total_value_usdt": total_now, "last_updated": "now()"}).eq("id", 1).execute()
            
            analysis = f"{reason} | RSI-Tgt: {round(target_rsi_buy, 1)} | F&G: {fng} | ATR: {round(curr['atr'], 2)}"
            supabase.table("trade_logs").insert({
                "symbol": SYMBOL, "price": price, "rsi": curr['rsi'], "action": action, "analysis_summary": analysis
            }).execute()

            print(f"📊 {time.strftime('%H:%M')} | Hind: {price} | Portfell: {round(total_now, 2)} | {action}")

        except Exception as e:
            print(f"❌ Viga: {e}")
        time.sleep(60)

run_super_bot()