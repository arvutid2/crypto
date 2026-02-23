import os
import time
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier
from supabase import create_client
from dotenv import load_dotenv
import logging

# Seadistame logid
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [brain] %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

# AJASTUSE SEADED
DASHBOARD_UPDATE_INTERVAL = 5  # sekundit
AI_TRAIN_INTERVAL = 1800      # 30 minutit (1800 sekundit)

def run_brain_cycle(last_train_time):
    current_time = time.time()
    
    # 1. TÕMBAME VIIMASED ANDMED
    res = supabase.table("trade_logs").select("*").order("created_at", desc=True).limit(500).execute()
    if not res.data or len(res.data) < 20:
        return last_train_time

    df = pd.DataFrame(res.data)
    
    # --- OSA A: DASHBOARDI UUENDAMINE (Iga 5 sekundi järel) ---
    try:
        pnl_sum = df['pnl'].dropna().sum()
        base_balance = 9979.54
        new_total = base_balance * (1 + (pnl_sum / 100))
        
        portfolio_update = {
            "total_value_usdt": float(new_total),
            "usdt_balance": float(new_total),
            "last_updated": "now()"
        }
        
        supabase.table("portfolio").update(portfolio_update).eq("id", 1).execute()
        logger.info(f"📊 Live Dashboard: {new_total:.2f} USDT (PnL: {pnl_sum:.2f}%)")
    except Exception as e:
        logger.error(f"Viga Dashboardi uuendamisel: {e}")

    # --- OSA B: AI TREENIMINE (Iga 30 minuti järel) ---
    if current_time - last_train_time >= AI_TRAIN_INTERVAL:
        logger.info("🧠 Alustan AI treenimist uute andmetega...")
        try:
            df['target'] = (df['price'].shift(-3) > df['price']).astype(int)
            features = ['price', 'rsi', 'market_pressure', 'fear_greed_index']
            
            X = df[features].fillna(0)
            y = df['target'].fillna(0)

            model = RandomForestClassifier(n_estimators=100)
            model.fit(X, y)
            joblib.dump(model, 'trading_brain.pkl')
            
            logger.info("✅ AI Mudel on värskendatud ja salvestatud!")
            return current_time  # Uuendame viimase treeningu aega
        except Exception as e:
            logger.error(f"Viga AI treenimisel: {e}")
            return last_train_time
            
    return last_train_time

if __name__ == "__main__":
    logger.info("🚀 Brain teenus käivitatud!")
    logger.info(f"Dashboard uueneb iga {DASHBOARD_UPDATE_INTERVAL}s, AI iga {AI_TRAIN_INTERVAL/60}min järel.")
    
    last_train_time = 0 # Sunnib esimesel käivitusel kohe treenima
    
    while True:
        last_train_time = run_brain_cycle(last_train_time)
        time.sleep(DASHBOARD_UPDATE_INTERVAL)