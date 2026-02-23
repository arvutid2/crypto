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

def train_brain():
    logger.info("🧠 Brain alustab treeningandmete kogumist...")
    
    # 1. Tõmbame viimased 500 rida andmeid
    res = supabase.table("trade_logs").select("*").order("created_at", desc=True).limit(500).execute()
    if not res.data or len(res.data) < 100:
        logger.warning("Liiga vähe andmeid treenimiseks. Vaja vähemalt 100 rida.")
        return

    df = pd.DataFrame(res.data)
    
    # 2. Märgistamine (Labeling) - ÕPETAME AJULE, MIS ON "HEA"
    # Loome sihtmärgi: 1, kui hind tõusis järgmise 3 kirje jooksul, muidu 0
    df['target'] = (df['price'].shift(-3) > df['price']).astype(int)
    
    # Valime tunnused (Features), mille põhjal aju otsustab
    features = ['price', 'rsi'] # Siia lisame hiljem volume jm
    X = df[features].fillna(0)
    y = df['target'].fillna(0)

    # 3. Masinõppe mudel (Random Forest)
    model = RandomForestClassifier(n_estimators=100)
    model.fit(X, y)
    
    # 4. Salvestame "aju" faili
    joblib.dump(model, 'trading_brain.pkl')
    logger.info("✅ Uus mudel on treenitud ja salvestatud: trading_brain.pkl")

if __name__ == "__main__":
    train_brain()