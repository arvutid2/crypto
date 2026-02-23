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

# --- AI KAALUD (Algseaded, mida bot hakkab ise muulma) ---
# Need näitavad, kui palju bot ühte või teist indikaatorit usaldab (1-5 skaalal)
weights = {
    "rsi": 3.0,
    "bb_lower": 2.0,
    "trend_4h": 4.0,
    "fng": 2.0
}

def get_binance_data(interval, limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval={interval}&limit={limit}"
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
    # Bollinger
    df['sma20'] = df['close'].rolling(window=20).mean()
    df['std20'] = df['close'].rolling(window=20).std()
    df['lower_band'] = df['sma20'] - (df['std20'] * 2)
    # Trend
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    return df

def get_fear_and_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/").json()
        return int(r['data'][0]['value'])
    except: return 50

def ai_self_learning():
    """Analüüsib viimaseid logisid ja muudab kaalusid (weights)"""
    global weights
    try:
        # Toome viimased 10 logi, kus tehti mingi otsus (BUY/SELL)
        logs = supabase.table("trade_logs").select("*").neq("action", "HOLD").order("created_at", desc=True).limit(5).execute().data
        
        if len(logs) < 2:
            return # Pole veel piisavalt ajalugu, et õppida

        print("🧠 AI Brain: Analüüsin mineviku vigu...")
        for log in logs:
            # Lihtsustatud õppimisloogika:
            # Kui tehing oli SELL, aga hind tõusis edasi -> RSI/F&G valetasid (liiga varajane müük)
            # Kui tehing oli BUY, aga hind langes -> Trendi-analüüs oli nõrk
            current_price = float(get_binance_data('1m', 1).iloc[-1]['close'])
            trade_price = float(log['price'])
            
            if log['action'] == "BUY" and current_price < trade_price:
                # "Ma ostsin, aga hind langes. Ma usaldasin liiga palju RSI-d ja BB-d."
                weights['rsi'] = max(1.0, weights['rsi'] - 0.1)
                weights['trend_4h'] = min(5.0, weights['trend_4h'] + 0.1)
            elif log['action'] == "SELL" and current_price > trade_price:
                # "Ma müüsin, aga hind tõusis. Ma olin liiga kartlik."
                weights['fng'] = max(1.0, weights['fng'] - 0.1)
                
    except Exception as e:
        print(f"Iseõppimise viga: {e}")

def run_ultimate_ai_bot():
    print(f"🤖 ULTIMATE AI v6 KÄIVITATUD: {SYMBOL}")
    
    while True:
        try:
            # 1. Õppimise faas
            ai_self_learning()
            
            # 2. Andmete kogumine
            df_1h = add_indicators(get_binance_data('1h'))
            df_4h = add_indicators(get_binance_data('4h'))
            fng = get_fear_and_greed()
            
            curr_1h = df_1h.iloc[-1]
            curr_4h = df_4h.iloc[-1]
            price = curr_1h['close']
            
            portfolio = supabase.table("portfolio").select("*").eq("id", 1).execute().data[0]
            usdt = float(portfolio['usdt_balance'])
            btc = float(portfolio['btc_balance'])
            
            # --- AI OTSUSTUS-MAATRIKS ---
            score = 0
            max_score = sum(weights.values())
            
            if curr_1h['rsi'] < 30: score += weights['rsi']
            if price <= curr_1h['lower_band']: score += weights['bb_lower']
            if curr_4h['close'] > curr_4h['ema200']: score += weights['trend_4h']
            if fng < 30: score += weights['fng']
            
            # Arvutame usaldusprotsendi (0-100%)
            confidence = (score / max_score) * 100
            
            action = "HOLD"
            reason = f"Usaldus: {round(confidence, 1)}%"

            # OSTAME ainult siis, kui usaldus on üle 70%
            if usdt > 10 and confidence >= 70:
                action = "BUY"
                btc_to_buy = usdt / price
                supabase.table("portfolio").update({"usdt_balance": 0, "btc_balance": btc_to_buy}).eq("id", 1).execute()
                reason = f"AI BUY: Confidence {round(confidence, 1)}%"

            # MÜÜME kui RSI on kõrge või portfell on kasumis
            elif btc > 0 and (curr_1h['rsi'] > 65 or fng > 75):
                action = "SELL"
                usdt_rec = btc * price
                supabase.table("portfolio").update({"usdt_balance": usdt_rec, "btc_balance": 0}).eq("id", 1).execute()
                reason = "AI PROFIT SELL"

            # 3. Portfelli ja logide uuendamine
            total_now = usdt + (btc * price)
            supabase.table("portfolio").update({"total_value_usdt": total_now}).eq("id", 1).execute()
            
            # Salvestame analüüsi koos selle hetke kaaludega
            analysis = f"{reason} | Weights: R:{round(weights['rsi'],1)} T:{round(weights['trend_4h'],1)} | F&G: {fng}"
            supabase.table("trade_logs").insert({
                "symbol": SYMBOL, "price": price, "rsi": curr_1h['rsi'], "action": action, "analysis_summary": analysis
            }).execute()

            print(f"📊 {time.strftime('%H:%M')} | Hind: {price} | AI Confidence: {round(confidence, 1)}% | {action}")

        except Exception as e:
            print(f"❌ Viga: {e}")
        time.sleep(60)

run_ultimate_ai_bot()