import os
import time
import pandas as pd
import joblib
from xgboost import XGBClassifier
from supabase import create_client
from dotenv import load_dotenv
import logging

# LOGIMISE SEADISTUS
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [brain] %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

try:
    supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))
    logger.info("✅ Supabase ühendus loodud.")
except Exception as e:
    logger.error(f"❌ Supabase ühenduse viga: {e}")

TRAIN_INTERVAL = 60 # Kontrollime iga minuti järel

def train_ai_model():
    logger.info("🧠 Kontrollin andmeid uue mudeli jaoks...")
    try:
        # PÄRING: Võtame ainult need read, kus MACD ja STOCH on olemas (ignoreerime Bollingeri)
        res = supabase.table("trade_logs") \
            .select("*") \
            .not_.is_("macd", "null") \
            .not_.is_("stoch_k", "null") \
            .not_.is_("vwap", "null") \
            .order("created_at", desc=True) \
            .limit(1000) \
            .execute()
        
        if not res.data or len(res.data) < 15:
            logger.info(f"Ootel: Vaja on vähemalt 15 rida uute andmetega. Hetkel leitud: {len(res.data) if res.data else 0}")
            return False

        df = pd.DataFrame(res.data)
        
        # Target: Kas hind tõusis järgmise 5 minuti jooksul?
        df = df.sort_values('created_at')
        df['target'] = (df['price'].shift(-5) > df['price']).astype(int)
        
        # Kasutame ainult neid tunnuseid, mis su pildil olid täidetud
        features = [
            'price', 'rsi', 'macd', 'macd_signal', 
            'vwap', 'stoch_k', 'stoch_d', 'atr', 'ema200',
            'market_pressure'
        ]
        
        # Puhastame ainult nende tunnuste põhjal
        train_df = df.dropna(subset=features + ['target'])
        
        if len(train_df) < 10:
            logger.info(f"Pärast puhastust jäi liiga vähe ridu ({len(train_df)}). Ootame veel andmeid.")
            # Prindime välja, mis täpselt puudu on, et debugida
            missing = df[features].isnull().sum()
            logger.info(f"Puuduvad väärtused: \n{missing[missing > 0]}")
            return False

        X = train_df[features]
        y = train_df['target']

        # XGBoost mudel
        model = XGBClassifier(
            n_estimators=100, 
            learning_rate=0.05, 
            max_depth=5, 
            random_state=42,
            objective='binary:logistic'
        )
        model.fit(X, y)
        
        joblib.dump(model, 'trading_brain_xgb.pkl')
        logger.info(f"🚀 UUS XGBOOST MUDEL LOODUD! Treenitud {len(X)} rea põhjal.")
        return True
        
    except Exception as e:
        logger.error(f"Viga treenimisel: {e}")
        return False

if __name__ == "__main__":
    logger.info("🚀 Brain.py V2 (Tolerantne režiim) on käivitatud...")
    
    while True:
        success = train_ai_model()
        if success:
            logger.info("✅ Mudel on värskendatud. Järgmine kontroll 1h pärast.")
            time.sleep(3600) # Kui mudel on valmis, pole vaja iga minut treenida
        else:
            time.sleep(TRAIN_INTERVAL)