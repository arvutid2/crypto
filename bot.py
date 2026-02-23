import os
import time
import pandas as pd
import pandas_ta as ta
from binance.client import Client
from supabase import create_client
from dotenv import load_dotenv
import logging

# 1. Seadistame logimise
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [bot] %(message)s')
logger = logging.getLogger(__name__)

# 2. Laeme keskkonnamuutujad
load_dotenv()

# Kontrollime vajalikke võtmeid
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

# Algatame kliendid
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

SYMBOL = 'BTCUSDT'
INTERVAL = Client.KLINE_INTERVAL_15MINUTE

def get_market_data(symbol):
    try:
        # ÕPPIMINE: Küsime piisavalt ajalugu (7 päeva), et indikaatorid nagu EMA 200 töötaksid kohe
        logger.info(f"Küsime ajaloolisi andmeid sümbolile {symbol}...")
        klines = client.get_historical_klines(symbol, INTERVAL, "7 days ago UTC")
        
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume', 
            'close_time', 'quote_asset_volume', 'number_of_trades', 
            'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
        ])
        
        # Andmete tüübiteisendus
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        
        # --- INDIKAATORITE ARVUTAMINE ---
        # RSI (14 perioodi)
        df['rsi'] = ta.rsi(df['close'], length=14)
        
        # EMA 200 (Vajab vähemalt 200 rida)
        df['ema200'] = ta.ema(df['close'], length=200)
        
        # EMA 50 (Kiirem trendi tuvastamiseks)
        df['ema50'] = ta.ema(df['close'], length=50)
        
        return df
    except Exception as e:
        logger.error(f"Viga andmete pärimisel: {e}")
        return None

def analyze_signals(df):
    if df is None or len(df) < 200:
        return "HOLD", "Ootame andmete kogunemist (EMA 200 vajab aega)."

    last_row = df.iloc[-1]
    price = last_row['close']
    rsi = last_row['rsi']
    ema200 = last_row['ema200']
    
    # LIHTNE STRATEEGIA:
    # BUY: RSI on madal (<35) JA hind on üle EMA 200 (oleme tõusutrendis)
    # SELL: RSI on kõrge (>70)
    
    if rsi < 35 and price > ema200:
        action = "BUY"
        summary = f"RSI on madal ({rsi:.1f}) ja oleme üle EMA 200. Siseneme tõusutrendi."
    elif rsi > 70:
        action = "SELL"
        summary = f"RSI on ülemüüdud ({rsi:.1f}). Aeg kasumit võtta."
    else:
        action = "HOLD"
        summary = f"RSI: {rsi:.1f} | EMA200: {ema200:.0f}. Ootame selgemat signaali."
        
    return action, summary

def start_bot():
    logger.info("🚀 ULTIMATE SENTINEL V11 ARVUTID2 EDITION ON KÄIVITATUD!")
    
    while True:
        try:
            # 1. Hangi andmed
            df = get_market_data(SYMBOL)
            
            if df is not None:
                # 2. Analüüsi
                action, summary = analyze_signals(df)
                last_price = df.iloc[-1]['close']
                last_rsi = df.iloc[-1]['rsi']
                
                # 3. Salvesta Supabase'i
                data_to_save = {
                    "symbol": SYMBOL,
                    "price": float(last_price),
                    "rsi": float(last_rsi) if not pd.isna(last_rsi) else 0,
                    "action": action,
                    "analysis_summary": summary
                }
                
                result = supabase.table("trade_logs").insert(data_to_save).execute()
                logger.info(f"✅ Salvestatud: {SYMBOL} @ {last_price} | Otsus: {action}")
            
            # Oota 60 sekundit enne uut kontrolli
            time.sleep(60)
            
        except Exception as e:
            logger.error(f"Süsteemne viga tsüklis: {e}")
            time.sleep(30)

if __name__ == "__main__":
    start_bot()