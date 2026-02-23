import os
import time
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier
from supabase import create_client
from dotenv import load_dotenv
import logging
from cleaner import run_smart_cleanup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [brain] %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

DASHBOARD_INTERVAL = 5
TRAIN_INTERVAL = 1800
OPTIMIZE_INTERVAL = 86400

def optimize_strategy():
    logger.info("🔧 Optimeerin strateegiat...")
    try:
        # Võtame tehingud, kus PnL ei ole 0
        res = supabase.table("trade_logs").select("*").neq("pnl", 0).limit(100).execute()
        
        # MUUDETUD: Nüüd piisab 2 tehingust, et aju hakkaks õppima
        if not res.data or len(res.data) < 2:
            logger.info("Ootan veel tehinguid (vajalik 2), et seadeid muuta.")
            return

        df = pd.DataFrame(res.data)
        avg_pnl = df['pnl'].mean()
        
        settings = {"stop_loss": -2.0, "take_profit": 3.0, "min_ai_confidence": 0.6}
        if avg_pnl < 0:
            settings = {"stop_loss": -1.5, "take_profit": 2.5, "min_ai_confidence": 0.7}
        elif avg_pnl > 0.5:
            settings = {"stop_loss": -2.5, "take_profit": 4.0, "min_ai_confidence": 0.5}

        supabase.table("bot_settings").update(settings).eq("id", 1).execute()
        logger.info(f"✅ Uued seaded: {settings}")
    except Exception as e:
        logger.error(f"Optimeerimise viga: {e}")

def run_brain_cycle(last_train_time):
    # Dashboardi uuendus
    try:
        res = supabase.table("trade_logs").select("*").order("created_at", desc=True).limit(500).execute()
        if res.data:
            df = pd.DataFrame(res.data)
            pnl_sum = df['pnl'].sum()
            new_total = 9979.54 * (1 + (pnl_sum / 100))
            supabase.table("portfolio").update({
                "total_value_usdt": float(new_total),
                "last_updated": "now()"
            }).eq("id", 1).execute()
    except: pass

    # AI Treening
    current_time = time.time()
    if current_time - last_train_time >= TRAIN_INTERVAL:
        # ... (sama treeningloogika mis varem)
        return current_time
    return last_train_time

if __name__ == "__main__":
    last_train_time = 0
    last_cleanup_time = time.time()
    last_optimize_time = 0
    
    while True:
        last_train_time = run_brain_cycle(last_train_time)
        curr = time.time()
        
        if curr - last_cleanup_time >= 86400:
            run_smart_cleanup()
            last_cleanup_time = curr
            
        if curr - last_optimize_time >= OPTIMIZE_INTERVAL:
            optimize_strategy()
            last_optimize_time = curr
            
        time.sleep(DASHBOARD_INTERVAL)