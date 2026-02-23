import os
import time
import pandas as pd
import pandas_ta as ta
import joblib
from binance.client import Client
from supabase import create_client
from dotenv import load_dotenv
import logging

# 1. LOGIMINE JA SEADISTUS
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [bot] %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# Ühendused
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

SYMBOL = 'BTCUSDT'
INTERVAL = Client.KLINE_INTERVAL_5MINUTE
last_buy_price = None

def get_market_data(symbol):
    try:
        # Küsime 3 päeva ajalugu, et indikaatorid oleksid täpsed
        klines = client.get_historical_klines(symbol, INTERVAL, "3 days ago UTC")
        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'])
        
        # Numbrite teisendus
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
        
        # Indikaatorid (Küünalde analüüs + Trend)
        df['rsi'] = ta.rsi(df['close'], length=14)
        df['ema50'] = ta.ema(df['close'], length=50)
        df['ema200'] = ta.ema(df['close'], length=200)
        
        return df
    except Exception as e:
        logger.error(f"Viga andmete pärimisel: {e}")
        return None

def get_order_book_status(symbol):
    try:
        depth = client.get_order_book(symbol=symbol, limit=20)
        bid_vol = sum(float(bid[1]) for bid in depth['bids'])
        ask_vol = sum(float(ask[1]) for ask in depth['asks'])
        return bid_vol > ask_vol, bid_vol / ask_vol
    except:
        return True, 1.0

def analyze_signals(df):
    global last_buy_price
    if df is None or len(df) < 200:
        return "HOLD", "Kogume ajalugu (EMA200)...", 0

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    price = curr['close']
    rsi = curr['rsi']
    
    # 1. MASINÕPPE ENNUSTUS (Brain.py poolt loodud fail)
    prediction = 0.5 # Neutraalne, kui mudelit pole
    try:
        if os.path.exists('trading_brain.pkl'):
            brain_model = joblib.load('trading_brain.pkl')
            # Ennustame viimase hinna ja RSI põhjal
            prediction = brain_model.predict([[price, rsi]])[0]
            logger.info(f"🧠 AI Ennustus: {'TÕUSEB' if prediction == 1 else 'EI TÕUSE'}")
    except Exception as e:
        logger.warning(f"Aju ei saanud vastata: {e}")

    # 2. TEHNILINE ANALÜÜS
    bullish_book, book_ratio = get_order_book_status(SYMBOL)
    is_green = curr['close'] > curr['open']
    volume_surge = curr['volume'] > prev['volume']
    
    action = "HOLD"
    summary = ""
    profit_pct = 0

    # --- AGRESSIIVNE AI STRATEEGIA ---
    # Osta kui: 
    # (Reeglid klapivad) VÕI (AI on väga kindel JA trend on UP)
    
    if (price > curr['ema50'] > curr['ema200'] and rsi < 50 and is_green and volume_surge) or \
       (prediction == 1 and price > curr['ema50'] and rsi < 55):
        
        action = "BUY"
        last_buy_price = price
        summary = f"🚀 BUY: AI:{prediction} | RSI:{rsi:.1f} | Book:{book_ratio:.2f}"

    # Müü kui:
    # RSI on liiga kõrge VÕI AI ennustab langust VÕI trend murdub
    elif last_buy_price and (rsi > 65 or (prediction == 0 and rsi > 55) or price < curr['ema50']):
        action = "SELL"
        profit_pct = ((price - last_buy_price) / last_buy_price) * 100
        summary = f"💰 SELL: Kasum {profit_pct:.2f}% | AI:{prediction}"
        last_buy_price = None
    
    else:
        summary = f"HOLD: RSI:{rsi:.1f} | AI Ennustus:{prediction} | Book:{book_ratio:.2f}"

    return action, summary, profit_pct

def start_bot():
    logger.info("🚀 ULTIMATE SENTINEL V14 - AI ENGINE STARTING...")
    
    while True:
        try:
            df = get_market_data(SYMBOL)
            if df is not None:
                action, summary, profit = analyze_signals(df)
                last_row = df.iloc[-1]
                
                # Salvestame Supabase'i (et Brain.py saaks siit õppida)
                data = {
                    "symbol": SYMBOL,
                    "price": float(last_row['close']),
                    "rsi": float(last_row['rsi']) if not pd.isna(last_row['rsi']) else 0,
                    "action": action,
                    "analysis_summary": summary
                }
                
                supabase.table("trade_logs").insert(data).execute()
                logger.info(f"✅ {SYMBOL} @ {last_row['close']} | {action} | {summary}")
            
            # Kontrollime turgu iga 30 sekundi järel
            time.sleep(30)
            
        except Exception as e:
            logger.error(f"Viga tsüklis: {e}")
            time.sleep(10)

if __name__ == "__main__":
    start_bot()