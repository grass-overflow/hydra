from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import numpy as np
import logging
import os
from stable_baselines3 import PPO

logger = logging.getLogger("RLAgentService")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="RL Agent Model Service")

MODEL_PATH = os.getenv("MODEL_PATH", "ppo_kubernetes_hardened.zip")
try:
    model = PPO.load(MODEL_PATH)
    logger.info(f"Loaded RL model successfully from {MODEL_PATH}")
except Exception as e:
    logger.warning(f"Could not load model from {MODEL_PATH}: {e}. Service will return random/fall-back actions.")
    model = None

class StateInput(BaseModel):
    state: List[float]

@app.post("/predict")
def predict_action(input_data: StateInput):
    if len(input_data.state) != 9:
        raise HTTPException(status_code=400, detail=f"State must have exactly 9 dimensions. Received {len(input_data.state)}")
        
    if model is None:
        logger.warning("Model not loaded. Returning fallback action (no-op).")
        return {"action": 0, "dummy": True}
        
    state = np.array(input_data.state, dtype=np.float32)
    action, _states = model.predict(state, deterministic=True)
    
    action_idx = int(np.asarray(action).item())
    logger.info(f"Predicted action {action_idx} for state {input_data.state}")
    return {"action": action_idx}

@app.get("/health")
def health():
    return {"status": "OK", "model_loaded": model is not None}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
