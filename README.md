# crypto

This repository hosts a simple crypto trading bot and an accompanying AI model (brain) that learns from past trades.

## Getting Started

1. **Install dependencies**
   ```sh
   pip install -r requirements.txt
   ```

2. **Set environment variables** in a `.env` file:
   ```ini
   BINANCE_API_KEY=...
   BINANCE_API_SECRET=...
   SUPABASE_URL=...
   SUPABASE_KEY=...
   ```

3. **Run the bot**
   ```sh
   python bot.py
   ```

4. **Train the model** (automatically every 10 min) or manually:
   ```sh
   python brain.py
   ```


## New features (2026)

- **Richer feature set**: VWAP, stochastics, volume, enhanced indicators
- **Stronger learner**: XGBoost classifier (falls back to RandomForest if missing)
- **Validation split** with accuracy logging
- **Online learning** with `partial_fit` support
- **Backtester**: `backtester.py` uses historical klines and the same signal logic
- Updated `requirements.txt` with `xgboost`, `stable-baselines3`, `gym` for future RL experiments

## Next steps

- Extend backtester with commission, slippage
- Explore reinforcement‑learning agents under `reinf_agent.py` (not yet added)
- Add a dashboard or metrics logging for model drift

## Notes

This code is for educational purposes; trading live involves risk. Always paper‑trade first!
