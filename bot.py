import os
import time
import requests
import pandas as pd
import numpy as np
from supabase import create_client
from dotenv import load_dotenv

# Seadistus
load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
SYMBOL = "BTCUSDT"
INITIAL_CAPITAL = 10000.0

def get_data(limit=100):
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

    # EMA 20 ja 50 (Trendi ristumine)
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()

    # Bollinger Bands
    df['sma20'] = df['close'].rolling(window=20).mean()
    df['std20'] = df['close'].rolling(window=20).std()
    df['upper_band'] = df['sma20'] + (df['std20'] * 2)
    df['lower_band'] = df['sma20'] - (df['std20'] * 2)

    # Candlestick Patterns: Hammer
    body = abs(df['close'] - df['open'])
    lower_shadow = df[['open', 'close']].min(axis=1) - df['low']
    upper_shadow = df['high'] - df[['open', 'close']].max(axis=1)
    df['is_hammer'] = (lower_shadow > body * 2) & (upper_shadow < body * 0.5)
    
    return df

def run_ultimate_bot():
    print(f"🚀 ULTIMATE AI BOT KÄIVITATUD ({SYMBOL})")
    entry_price = 0.0 # Hoiame meeles, mis hinnaga ostsime

    while True:
        try:
            df = add_indicators(get_data(100))
            curr = df.iloc[-1]
            prev = df.iloc[-2]
            
            portfolio = supabase.table("portfolio").select("*").eq("id", 1).execute().data[0]
            usdt = float(portfolio['usdt_balance'])
            btc = float(portfolio['btc_balance'])
            price = curr['close']
            
            action = "HOLD"
            reason = "Ootame signaali"

            # --- ANALÜÜS ---
            is_oversold = curr['rsi'] < 30
            is_overbought = curr['rsi'] > 70
            trend_up = curr['ema20'] > curr['ema50']
            hammer_detected = curr['is_hammer']

            # --- OSTU STRATEEGIA ---
            if usdt > 10:
                # Osta kui: RSI on madal JA (on Hammer muster VÕI hind põrkab alumiselt bandilt)
                if (is_oversold and (hammer_detected or price <= curr['lower_band'])):
                    action = "BUY"
                    entry_price = price
                    btc_to_buy = usdt / price
                    supabase.table("portfolio").update({"usdt_balance": 0, "btc_balance": btc_to_buy}).eq("id", 1).execute()
                    reason = f"BUY: RSI {round(curr['rsi'],1)} + Hammer muster"

            # --- MÜÜGI / RISKHALDUSE STRATEEGIA ---
            elif btc > 0:
                # 1. Stop Loss (2%)
                if price <= entry_price * 0.98:
                    action = "SELL"
                    reason = "STOP LOSS: 2% kukkumine"
                # 2. Take Profit (3%)
                elif price >= entry_price * 1.03:
                    action = "SELL"
                    reason = "TAKE PROFIT: 3% kasum käes"
                # 3. Indikaatori põhine müük
                elif is_overbought:
                    action = "SELL"
                    reason = f"SELL: RSI {round(curr['rsi'],1)} liiga kõrge"
                
                if action == "SELL":
                    usdt_to_receive = btc * price
                    supabase.table("portfolio").update({"usdt_balance": usdt_to_receive, "btc_balance": 0}).eq("id", 1).execute()
                    entry_price = 0

            # --- PORTFELLI JA LOGIDE UUENDAMINE ---
            total_val = usdt + (btc * price)
            supabase.table("portfolio").update({"total_value_usdt": total_val, "last_updated": "now()"}).eq("id", 1).execute()

            # Salvestame põhjaliku logi masinõppe jaoks
            supabase.table("trade_logs").insert({
                "symbol": SYMBOL,
                "price": price,
                "rsi": curr['rsi'],
                "action": action,
                "analysis_summary": f"{reason} | Trend: {'UP' if trend_up else 'DOWN'} | Portfolio: {round(total_val, 2)}"
            }).execute()

            print(f"🕒 {time.strftime('%H:%M:%S')} | Hind: {price} | RSI: {round(curr['rsi'],1)} | {action}")

        except Exception as e:
            print(f"❌ Viga: {e}")
        
        time.sleep(60)

if __name__ == "__main__":
    run_ultimate_bot()