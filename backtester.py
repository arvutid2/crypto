import os
import pandas as pd
import pandas_ta as ta
from binance.client import Client
from dotenv import load_dotenv

load_dotenv()
client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))

SYMBOL = 'BTCUSDT'

# kopeeritud mõningad meetodid bot.py-st

def prepare_dataframe(klines):
    df = pd.DataFrame(klines, columns=['time','open','high','low','close','volume','_','_','_','_','_','_'])
    df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].apply(pd.to_numeric)
    df['rsi'] = ta.rsi(df['close'], length=14)
    macd = ta.macd(df['close'])
    df['macd'] = macd.iloc[:,0]
    df['macd_signal'] = macd.iloc[:,2]
    bbands = ta.bbands(df['close'], length=20, std=2)
    df['bb_lower'] = bbands.iloc[:,0]
    df['bb_upper'] = bbands.iloc[:,2]
    df['ema50'] = ta.ema(df['close'], length=50)
    df['ema200'] = ta.ema(df['close'], length=200)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    try:
        df['vwap'] = ta.vwap(df['high'], df['low'], df['close'], df['volume'])
        stoch = ta.stoch(df['high'], df['low'], df['close'])
        df['stoch_k'] = stoch.iloc[:,0]
        df['stoch_d'] = stoch.iloc[:,1]
    except Exception:
        pass
    return df


def backtest(start_str="500 hours ago UTC"):
    klines = client.get_historical_klines(SYMBOL, '1m', start_str)
    df = prepare_dataframe(klines)

    last_buy = None
    pnl_history = []

    for i in range(2, len(df)):
        window = df.iloc[:i+1].copy()
        action, summary, pnl, pred = analyze_signals(window)
        # siin analyseerime liikumist aga ei logi tegelikku orderit
        if action == 'BUY':
            last_buy = window.iloc[-1]['close']
        elif action == 'SELL' and last_buy is not None:
            pnl_history.append(((window.iloc[-1]['close'] - last_buy) / last_buy) * 100)
            last_buy = None
    print(f"Backtest finished items: {len(pnl_history)} trades, avg pnl {pd.Series(pnl_history).mean():.2f}%")

# backtestile on vaja bot.iset ja model loadimist
from bot import analyze_signals

if __name__ == '__main__':
    backtest()
