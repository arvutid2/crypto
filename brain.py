import os
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier
from supabase import create_client
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [brain] %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

def run_brain():
    logger.info("🧠 Brain alustab tööd...")
    
    # 1. TÕMBAME ANDMED ANALÜÜSIKS
    res = supabase.table("trade_logs").select("*").order("created_at", desc=True).limit(500).execute()
    if not res.data or len(res.data) < 20:
        logger.warning("Liiga vähe andmeid.")
        return

    df = pd.DataFrame(res.data)
    
    # --- AI TREENIMINE ---
    df['target'] = (df['price'].shift(-3) > df['price']).astype(int)
    # Kasutame kõiki uusi tulpasid, mida bot.py kogub
    features = ['price', 'rsi', 'market_pressure', 'fear_greed_index']
    
    # Täidame tühjad lahtrid, et kood ei katkeks
    X = df[features].fillna(0)
    y = df['target'].fillna(0)

    model = RandomForestClassifier(n_estimators=100)
    model.fit(X, y)
    joblib.dump(model, 'trading_brain.pkl')
    logger.info("✅ AI Mudel treenitud.")

    # --- DASHBOARDI UUENDAMINE (PORTFOLIO TABEL) ---
    # Arvutame kogukasumi (PnL summa)
    # Pildi järgi on sul 'pnl' tulp olemas, võtame sealt summad
    pnl_sum = df['pnl'].dropna().sum()
    
    # Algne balanss (võtame näiteks sinu pildil oleva 9979.54 baasiks)
    base_balance = 9979.54
    # Arvutame uue väärtuse: algne + (algne * kogukasum protsentides / 100)
    new_total = base_balance * (1 + (pnl_sum / 100))
    
    logger.info(f"📊 Arvutatud PnL: {pnl_sum:.2f}% | Uus saldo: {new_total:.2f} USDT")

    try:
        # Uuendame 'portfolio' tabelis rida, kus id=1
        portfolio_update = {
            "total_value_usdt": float(new_total),
            "usdt_balance": float(new_total), # Eeldame, et hetkel on kõik USDT-s
            "last_updated": "now()"
        }
        
        supabase.table("portfolio").update(portfolio_update).eq("id", 1).execute()
        logger.info("🚀 Dashboardi portfell on nüüd Supabase'is uuendatud!")
    except Exception as e:
        logger.error(f"Viga portfelli uuendamisel: {e}")

if __name__ == "__main__":
    run_brain()