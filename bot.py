import os
import time
import pandas as pd
import pandas_ta as ta
import joblib
import warnings
import requests
from binance.client import Client
from supabase import create_client
from dotenv import load_dotenv
import logging

# 1. LOGIMINE JA SÜSTEEMI SEADED
warnings.filterwarnings("ignore", category=UserWarning)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [bot] %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

SYMBOL = 'BTCUSDT'
INTERVAL = Client.KLINE_INTERVAL_5MINUTE
last_buy_price = None

# Funktsioon Fear & Greed indeksi saamiseks
def get_fear_greed_index():
    try:
        r = requests.get('https://api.alternative.me/fng/')
        return int(r.json()['data'][0]['value'])
    except:
        return 50  # Neutraalne, kui väärtust ei saa

def get_market_data(symbol):
    try:
        klines = client.get_historical_klines(symbol, INTERVAL, "3 days ago UTC")
        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'])
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
        df['rsi'] = ta.rsi(df['close'], length=14)
        df['ema50'] = ta.ema(df['close'], length=50)
        df['ema200'] = ta.ema(df['close'], length=200)
        return df
    except Exception as e:
        logger.error(f"Viga Binance andmetega: {e}")
        return None

def get_order_book_status(symbol):
    try:
        depth = client.get_order_book(symbol=symbol, limit=20)
        bid_vol = sum(float(bid[1]) for bid in depth['bids'])
        ask_vol = sum(float(ask[1]) for ask in depth['asks'])
        ratio = bid_vol / ask_vol if ask_vol > 0 else 1.0
        return bid_vol > ask_vol, ratio
    except:
        return True, 1.0

def analyze_signals(df):
    global last_buy_price
    if df is None or len(df) < 200:
        return "HOLD", "Kogume ajalugu...", 0, 1.0

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    price = curr['close']
    rsi = curr['rsi']
    
    # --- 1. MASINÕPPE ENNUSTUS ---
    prediction = 0.5
    if os.path.exists('trading_brain.pkl'):
        try:
            brain_model = joblib.load('trading_brain.pkl')
            input_df = pd.DataFrame([[price, rsi]], columns=['price', 'rsi'])
            prediction = brain_model.predict(input_df)[0]
        except: pass

    # --- 2. TEHNILINE ANALÜÜS ---
    bullish_book, book_ratio = get_order_book_status(SYMBOL)
    is_green = curr['close'] > curr['open']
    volume_surge = curr['volume'] > prev['volume']
    
    action = "HOLD"
    summary = ""
    profit_pct = 0

    # --- 3. OTSUSTAMISE LOOGIKA ---
    
    # OSTU REEGEL (Kui meil pole positsiooni)
    if last_buy_price is None:
        if (price > curr['ema50'] > curr['ema200'] and rsi < 55 and is_green and volume_surge) or \
           (prediction == 1 and price > curr['ema50']):
            action = "BUY"
            last_buy_price = price
            summary = f"🚀 BUY | AI:{prediction} | RSI:{rsi:.1f}"
            logger.info(f"💰 POSITSIOON AVATUD: {price}")

    # MÜÜGI REEGEL (Kui meil ON positsioon - Siia lisandub Stop-Loss)
    elif last_buy_price is not None:
        profit_pct = ((price - last_buy_price) / last_buy_price) * 100
        
        # A. STOP-LOSS (Hädapidur -2%)
        if profit_pct <= -2.0:
            action = "SELL"
            summary = f"🛑 STOP-LOSS: {profit_pct:.2f}% | Hind: {price}"
            logger.warning(f"⚠️ STOP-LOSS AKTIVEERITUD: {profit_pct:.2f}%")
            last_buy_price = None

        # B. TAKE-PROFIT (Kindel kasum +3%)
        elif profit_pct >= 3.0:
            action = "SELL"
            summary = f"🎯 TAKE-PROFIT: {profit_pct:.2f}% | AI:{prediction}"
            logger.info(f"✅ TAKE-PROFIT SAAVUTATUD: {profit_pct:.2f}%")
            last_buy_price = None

        # C. STRATEEGILINE MÜÜK (RSI või AI põhjal)
        elif rsi > 68 or (prediction == 0 and rsi > 55) or price < curr['ema50']:
            action = "SELL"
            summary = f"💰 STRATEEGILINE SELL: {profit_pct:.2f}% | AI:{prediction}"
            logger.info(f"✅ MÜÜK SIGNAALI PÕHJAL: {profit_pct:.2f}%")
            last_buy_price = None

    if action == "HOLD":
        summary = f"HOLD | RSI:{rsi:.1f} | AI:{prediction} | Book:{book_ratio:.2f}"

    return action, summary, profit_pct, book_ratio

def start_bot():
    logger.info("🔥 SENTINEL V16 - F&G, PNL JA PRESSURE ACTIVE")
    
    while True:
        try:
            df = get_market_data(SYMBOL)
            if df is not None:
                action, summary, profit, ratio = analyze_signals(df)
                last_row = df.iloc[-1]
                fng_value = get_fear_greed_index() # Võtame F&G väärtuse
                
                # Nüüd saadame KÕIK andmed Supabase'i
                data = {
                    "symbol": SYMBOL,
                    "price": float(last_row['close']),
                    "rsi": float(last_row['rsi']) if not pd.isna(last_row['rsi']) else 0,
                    "action": action,
                    "analysis_summary": summary,
                    "pnl": float(profit) if profit != 0 else None,
                    "market_pressure": float(ratio),
                    "fear_greed_index": fng_value,
                    "bot_confidence": 1 if action in ["BUY", "SELL"] else 0
                }
                
                supabase.table("trade_logs").insert(data).execute()
                logger.info(f"📈 {SYMBOL}: {last_row['close']} | F&G: {fng_value} | {summary}")
            
            time.sleep(30)
        except Exception as e:
            logger.error(f"Viga: {e}")
            time.sleep(10)

if __name__ == "__main__":
    start_bot()