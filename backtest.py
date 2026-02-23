import pandas as pd
import joblib
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

def run_backtest():
    print("📥 Tõmban andmeid testimiseks...")
    # Tõmbame viimased 1000 rida ajalugu
    res = supabase.table("trade_logs").select("*").not_.is_("vwap", "null").order("created_at", desc=True).execute()
    
    if not res.data or len(res.data) < 20:
        print("❌ Testimiseks on liiga vähe täielikke andmeid (vajalik vähemalt 20 rida).")
        return

    df = pd.DataFrame(res.data)
    df = df.iloc[::-1] # Keerame andmed õigesse ajajärjekorda

    if not os.path.exists('trading_brain_xgb.pkl'):
        print("❌ XGBoost mudelit ei leitud. Treeni esmalt brain.py-ga!")
        return

    model = joblib.load('trading_brain_xgb.pkl')
    
    alg_saldo = 1000.0  # USDT
    saldo = alg_saldo
    kogus = 0
    tehinguid = 0
    
    print(f"🚀 Alustan simulatsiooni {len(df)} küünlaga...")
    
    for i in range(len(df)):
        row = df.iloc[i]
        price = float(row['price'])
        
        # SAMA JÄRJEKORD MIS BOT.PY-S!
        features = [[
            price, row['rsi'], row['macd'], row['macd_signal'],
            row['vwap'], row['stoch_k'], row['stoch_d'],
            row['atr'], row['ema200'], row['market_pressure']
        ]]
        
        prediction = model.predict_proba(features)[0][1]
        
        # OSTA (kui AI ennustus > 0.7 ja meil pole veel positsiooni)
        if prediction > 0.7 and kogus == 0:
            kogus = saldo / price
            saldo = 0
            tehinguid += 1
            print(f"[{row['created_at']}] BUY: Hind {price:.2f} | AI: {prediction:.2f}")

        # MÜÜ (kui AI ennustus < 0.3 ja meil on positsioon)
        elif (prediction < 0.3 or row['stoch_k'] > 80) and kogus > 0:
            saldo = kogus * price
            kogus = 0
            tehinguid += 1
            kasum = saldo - alg_saldo
            print(f"[{row['created_at']}] SELL: Hind {price:.2f} | Saldo: {saldo:.2f} | Kasum: {kasum:.2f}%")

    lõpp_väärtus = saldo + (kogus * float(df.iloc[-1]['price']))
    print("-" * 30)
    print(f"SIMULATSIOONI TULEMUS:")
    print(f"Algne saldo: {alg_saldo} USDT")
    print(f"Lõplik saldo: {lõpp_väärtus:.2f} USDT")
    print(f"Kokku tehinguid: {tehinguid}")
    print(f"Netokasum: {((lõpp_väärtus - alg_saldo) / alg_saldo) * 100:.2f}%")

if __name__ == "__main__":
    run_backtest()