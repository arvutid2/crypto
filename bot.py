import os
import time
import pandas as pd
import pandas_ta as ta
from binance.client import Client
from supabase import create_client
from dotenv import load_dotenv
import logging

# 1. LOGIMINE JA SEADED
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [bot] %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

SYMBOL = 'BTCUSDT'
INTERVAL = Client.KLINE_INTERVAL_5MINUTE
last_buy_price = None

def get_market_data(symbol):
    try:
        # KÜÜNLAD JA INDIKAATORID: Küsime 3 päeva ajalugu
        klines = client.get_historical_klines(symbol, INTERVAL, "3 days ago UTC")
        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'])
        
        # Tüübiteisendus
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, axis=1)
        
        # Arvutame indikaatorid
        df['rsi'] = ta.rsi(df['close'], length=14)
        df['ema50'] = ta.ema(df['close'], length=50)
        df['ema200'] = ta.ema(df['close'], length=200)
        
        return df
    except Exception as e:
        logger.error(f"Viga andmete pärimisel: {e}")
        return None

def get_order_book_status(symbol):
    try:
        # ORDER BOOK: Vaatame ostu- ja müügiseinte suhet (top 20)
        depth = client.get_order_book(symbol=symbol, limit=20)
        bid_vol = sum(float(ask[1]) for ask in depth['bids']) # Ostusoovid
        ask_vol = sum(float(ask[1]) for ask in depth['asks']) # Müügisoovid
        
        # Kui ostusoove on rohkem, on surve üles
        return bid_vol > ask_vol, bid_vol / ask_vol
    except:
        return True, 1.0

def analyze_signals(df):
    global last_buy_price
    if df is None or len(df) < 200:
        return "HOLD", "Kogume ajalugu (EMA200)...", 0

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    # ORDER BOOK ANALÜÜS
    bullish_book, book_ratio = get_order_book_status(SYMBOL)
    
    # KÜÜNALDE JA MAHU ANALÜÜS
    is_green = curr['close'] > curr['open']
    volume_surge = curr['volume'] > prev['volume']
    
    profit_pct = 0
    action = "HOLD"
    summary = ""

    # --- ULTIMATE STRATEEGIA ---
    
    # 1. OSTU TINGIMUSED (KÕIK PEAVAD KLAPPIMA):
    # - Trend: Hind > EMA50 ja EMA50 > EMA200
    # - Momentum: RSI < 50 (agressiivne sisenemine)
    # - Küünal: Roheline ja kasvav maht
    # - Book: Ostusurve on suurem kui müügisurve
    
    if (curr['close'] > curr['ema50'] > curr['ema200']) and \
       (curr['rsi'] < 50) and is_green and volume_surge and bullish_book:
        
        action = "BUY"
        last_buy_price = curr['close']
        summary = f"🚀 SUPER BUY: RSI:{curr['rsi']:.1f} | Vol+ | Book Ratio:{book_ratio:.2f}"

    # 2. MÜÜGI TINGIMUSED:
    # - RSI ülemüüdud (> 65)
    # - VÕI Hind kukub alla EMA50 (Trendi murdumine)
    # - VÕI Trailing stop-loss: hind kukub alla eelmise küünla madalaima punkti
    
    elif last_buy_price and (curr['rsi'] > 65 or curr['close'] < curr['ema50'] or curr['close'] < prev['low']):
        action = "SELL"
        profit_pct = ((curr['close'] - last_buy_price) / last_buy_price) * 100
        summary = f"💰 SELL: Kasum {profit_pct:.2f}% | RSI:{curr['rsi']:.1f}"
        last_buy_price = None

    else:
        summary = f"JÄLGIN: RSI:{curr['rsi']:.1f} | Book Ratio:{book_ratio:.2f} | Trend: {'UP' if curr['close'] > curr['ema50'] else 'DOWN'}"

    return action, summary, profit_pct

def start_bot():
    logger.info("🚀 ULTIMATE SENTINEL V13 KÄIVITATUD - KÕIK SÜSTEEMID ONLINE!")
    
    while True:
        try:
            df = get_market_data(SYMBOL)
            if df is not None:
                action, summary, profit = analyze_signals(df)
                last_price = df.iloc[-1]['close']
                
                # Salvestame Supabase'i
                # Kontrolli, et Supabase tabelis on: symbol, price, rsi, action, analysis_summary
                data = {
                    "symbol": SYMBOL,
                    "price": float(last_price),
                    "rsi": float(df.iloc[-1]['rsi']) if not pd.isna(df.iloc[-1]['rsi']) else 0,
                    "action": action,
                    "analysis_summary": summary
                }
                
                supabase.table("trade_logs").insert(data).execute()
                logger.info(f"✅ {SYMBOL} @ {last_price} | {action} | {summary}")
            
            time.sleep(30) # Kontroll iga 30 sekundi järel
            
        except Exception as e:
            logger.error(f"Viga tsüklis: {e}")
            time.sleep(10)

if __name__ == "__main__":
    start_bot()