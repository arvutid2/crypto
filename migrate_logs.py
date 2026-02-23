"""Backfill missing indicator columns in `trade_logs` table.

This script fetches all rows where one of the new features is null and
recomputes them based on the market data at the time of the log.
It uses the same indicator functions as `bot.get_market_data`.

Usage:
    python migrate_logs.py
"""
import os
import time
import pandas as pd
import pandas_ta as ta
from binance.client import Client
from supabase import create_client
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [migrate] %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))
SYMBOL = 'BTCUSDT'


# copy of indicator logic, returns df with new columns present

def enrich_df(df: pd.DataFrame) -> pd.DataFrame:
    df['rsi'] = ta.rsi(df['close'], length=14)
    macd = ta.macd(df['close'])
    df['macd'] = macd.iloc[:, 0]
    df['macd_signal'] = macd.iloc[:, 2]
    bbands = ta.bbands(df['close'], length=20, std=2)
    df['bb_lower'] = bbands.iloc[:, 0]
    df['bb_upper'] = bbands.iloc[:, 2]
    df['ema50'] = ta.ema(df['close'], length=50)
    df['ema200'] = ta.ema(df['close'], length=200)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    try:
        df['vwap'] = ta.vwap(df['high'], df['low'], df['close'], df['volume'])
        stoch = ta.stoch(df['high'], df['low'], df['close'])
        df['stoch_k'] = stoch.iloc[:, 0]
        df['stoch_d'] = stoch.iloc[:, 1]
    except Exception:
        pass
    return df


def backfill_records(limit=100):
    # fetch rows missing any of the target columns
    cols = ['volume', 'vwap', 'stoch_k', 'stoch_d']
    query = supabase.table('trade_logs')
    for c in cols:
        query = query.or_(f"{c}.is.null")
    # supabase-python doesn't support or chaining easily; so we'll simply
    # do select and filter in pandas below.
    res = supabase.table('trade_logs').select('*').limit(limit).execute()
    if not res.data:
        logger.info('No rows returned.')
        return
    df = pd.DataFrame(res.data)
    to_process = df[[c for c in cols if c in df.columns]].isna().any(axis=1)
    df = df[to_process]
    logger.info(f"Processing {len(df)} rows for backfill")

    for idx, row in df.iterrows():
        ts = row['created_at']
        # fetch a bit of market data around the timestamp
        try:
            end = pd.to_datetime(ts).strftime('%Y-%m-%d %H:%M:%S') + ' UTC'
            klines = client.get_historical_klines(SYMBOL, '1m', end, limit=10)
            mdf = pd.DataFrame(klines, columns=['time','open','high','low','close','volume','_','_','_','_','_','_'])
            mdf[['open','high','low','close','volume']] = mdf[['open','high','low','close','volume']].apply(pd.to_numeric)
            mdf = enrich_df(mdf)
            # take the last row (closest to timestamp)
            newvals = mdf.iloc[-1]
            update = {k: float(newvals[k]) for k in cols if k in newvals}
            if update:
                logger.info(f"Updating row {row['id']} with {update}")
                supabase.table('trade_logs').update(update).eq('id', row['id']).execute()
        except Exception as e:
            logger.error(f"Error processing row {row['id']}: {e}")


if __name__ == '__main__':
    backfill_records(limit=2000)
