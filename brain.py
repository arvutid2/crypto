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

def train_ai_model():
    logger.info("🧠 Alustan süvaõppe treeningut (MACD, BB, ATR, EMA)...")
    try:
        # Tõmbame viimased 1000 rida ajalugu
        res = supabase.table("trade_logs").select("*").order("created_at", desc=True).limit(1000).execute()
        if not res.data or len(res.data) < 50:
            logger.info("Liiga vähe andmeid süvaõppeks. Kogume veel...")
            return False

        df = pd.DataFrame(res.data)
        
        # Määrame sihtmärgi: kas hind tõusis järgmise 5 minuti jooksul?
        df['target'] = (df['price'].shift(-5) > df['price']).astype(int)
        
        # --- KÕIK UUDSED ANDMEKANALID AI JAOKS ---
        features = [
            'price', 'rsi', 'macd', 'macd_signal', 
            'bb_upper', 'bb_lower', 'atr', 'ema200',
            'market_pressure', 'fear_greed_index'
        ]
        
        # Eemaldame tühjad read ja valmistame ette X ja y
        train_df = df.dropna(subset=features + ['target'])
        X = train_df[features]
        y = train_df['target']

        if len(X) < 20: return False

        # Treenime täpsema mudeli
        model = RandomForestClassifier(n_estimators=200, max_depth=10, random_state=42)
        model.fit(X, y)
        
        joblib.dump(model, 'trading_brain.pkl')
        logger.info(f"✅ AI on uue infoga täiendatud! (Treenitud {len(X)} rea peal)")
        return True
    except Exception as e:
        logger.error(f"Viga AI treenimisel: {e}")
        return False

def optimize_strategy():
    logger.info("🔧 Analüüsin strateegia efektiivsust...")
    try:
        res = supabase.table("trade_logs").select("*").neq("pnl", 0).limit(100).execute()
        if not res.data or len(res.data) < 2: return

        df = pd.DataFrame(res.data)
        avg_pnl = df['pnl'].mean()
        
        # Iseõppiv seadete kohandamine
        settings = {"stop_loss": -2.0, "take_profit": 3.0, "min_ai_confidence": 0.6}
        if avg_pnl < 0:
            settings = {"stop_loss": -1.2, "take_profit": 2.0, "min_ai_confidence": 0.75}
        elif avg_pnl > 0.5:
            settings = {"stop_loss": -2.5, "take_profit": 4.5, "min_ai_confidence": 0.55}

        supabase.table("bot_settings").update(settings).eq("id", 1).execute()
        logger.info(f"✅ Strateegia optimeeritud: {settings}")
    except Exception as e:
        logger.error(f"Viga optimeerimisel: {e}")

# (Põhitsükkel jääb samaks, mis varem kutsudes välja train_ai_model ja optimize_strategy)