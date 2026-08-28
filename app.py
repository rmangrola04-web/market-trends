import os
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import pandas as pd
import yfinance as yf
import requests
import pyotp
from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from dhanhq import dhanhq
from SmartApi import SmartConnect

# ----------------- SECURITY CONFIG -----------------
SECRET_KEY = os.getenv("APP_SECRET_KEY", "trading-shield-super-secret-jwt-key-2026-indore")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 720

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", pwd_context.hash("admin@123"))

# ----------------- SEARCH DIRECTORY (CASH, COMMODITY, INDICES) -----------------
MASTER_SYMBOLS = [
    # Indices & F&O
    {"symbol": "^NSEI", "name": "NIFTY 50", "segment": "INDEX", "step": 50},
    {"symbol": "^NSEBANK", "name": "BANKNIFTY", "segment": "INDEX", "step": 100},
    {"symbol": "^CNXIT", "name": "NIFTY IT", "segment": "INDEX", "step": 100},
    # Commodities
    {"symbol": "CL=F", "name": "CRUDE OIL (MCX/NYMEX)", "segment": "COMMODITY", "step": 50},
    {"symbol": "GC=F", "name": "GOLD (MCX/COMEX)", "segment": "COMMODITY", "step": 100},
    {"symbol": "SI=F", "name": "SILVER (MCX/COMEX)", "segment": "COMMODITY", "step": 500},
    {"symbol": "NG=F", "name": "NATURAL GAS", "segment": "COMMODITY", "step": 5},
    # Cash / Equity / Futures
    {"symbol": "RELIANCE.NS", "name": "Reliance Industries", "segment": "EQUITY", "step": 20},
    {"symbol": "SBIN.NS", "name": "State Bank of India", "segment": "EQUITY", "step": 10},
    {"symbol": "TCS.NS", "name": "Tata Consultancy Services", "segment": "EQUITY", "step": 50},
    {"symbol": "HDFCBANK.NS", "name": "HDFC Bank Ltd", "segment": "EQUITY", "step": 20},
    {"symbol": "ICICIBANK.NS", "name": "ICICI Bank", "segment": "EQUITY", "step": 10},
    {"symbol": "INFY.NS", "name": "Infosys Ltd", "segment": "EQUITY", "step": 20},
    {"symbol": "TATAMOTORS.NS", "name": "Tata Motors", "segment": "EQUITY", "step": 10},
    {"symbol": "ITC.NS", "name": "ITC Ltd", "segment": "EQUITY", "step": 5},
    {"symbol": "LT.NS", "name": "Larsen & Toubro", "segment": "EQUITY", "step": 20},
    {"symbol": "AXISBANK.NS", "name": "Axis Bank", "segment": "EQUITY", "step": 10}
]

TERMINAL_STATE = {
    "active_broker": None,
    "is_connected": False,
    "broker_display_id": "",
    "auto_trade_enabled": False,
    "risk_settings": {"lots": 1, "target_inr": 1000.0, "stoploss_inr": 500.0},
    "logs": [f"{datetime.now().strftime('%H:%M:%S')} - ऑप्शन बाइंग टर्मिनल तैयार है।"]
}

broker_instances: Dict[str, Any] = {}

app = FastAPI(title="Option Buyer Terminal")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ----------------- AUTH HELPERS -----------------
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("sub") != ADMIN_USERNAME:
            raise HTTPException(status_code=401, detail="अमान्य टोकन!")
    except JWTError:
        raise HTTPException(status_code=401, detail="सत्र समाप्त, पुनः लॉगिन करें।")
    return payload.get("sub")

# ----------------- SCHEMAS -----------------
class BrokerLinkRequest(BaseModel):
    broker: str
    client_id: str
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    access_token: Optional[str] = None
    pin: Optional[str] = None
    totp_secret: Optional[str] = None

class RiskSettingsRequest(BaseModel):
    lots: int
    target_inr: float
    stoploss_inr: float
    auto_trade: bool

class OptionBuyRequest(BaseModel):
    symbol: str
    strike: float
    option_type: str  # CE or PE
    lots: int

# ----------------- ENDPOINTS -----------------
@app.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    if form_data.username != ADMIN_USERNAME or not pwd_context.verify(form_data.password, ADMIN_PASSWORD_HASH):
        raise HTTPException(status_code=400, detail="गलत यूज़रनेम या पासवर्ड!")
    return {"access_token": create_access_token(data={"sub": form_data.username}), "token_type": "bearer"}

@app.get("/api/search")
def search_symbols(q: str = Query("", min_length=1), user: str = Depends(get_current_user)):
    query = q.lower().strip()
    results = [s for s in MASTER_SYMBOLS if query in s["symbol"].lower() or query in s["name"].lower()]
    return results[:10]

@app.get("/api/market-data")
def get_market_data(symbol: str = Query(...), user: str = Depends(get_current_user)):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="5d", interval="5m")
        if df.empty or len(df) < 5:
            raise HTTPException(status_code=404, detail="डेटा उपलब्ध नहीं!")

        current_price = round(float(df["Close"].iloc[-1]), 2)
        
        # Previous Day High / Low Calculation
        df_daily = ticker.history(period="5d", interval="1d")
        if len(df_daily) >= 2:
            prev_day = df_daily.iloc[-2]
            pdh = round(float(prev_day["High"]), 2)
            pdl = round(float(prev_day["Low"]), 2)
            pdc = round(float(prev_day["Close"]), 2)
        else:
            pdh, pdl, pdc = current_price, current_price, current_price

        # Strike Price Generator (ATM, ITM, OTM)
        step = 50
        for s in MASTER_SYMBOLS:
            if s["symbol"] == symbol:
                step = s["step"]
                break
        
        atm_strike = round(current_price / step) * step
        strikes = [atm_strike - (step * 2), atm_strike - step, atm_strike, atm_strike + step, atm_strike + (step * 2)]

        # Signal Logic based on PDH / PDL Breakout
        recommendation = "NEUTRAL"
        if current_price > pdh:
            recommendation = "BULLISH BREAKOUT (BUY CE)"
        elif current_price < pdl:
            recommendation = "BEARISH BREAKDOWN (BUY PE)"

        return {
            "symbol": symbol,
            "current_price": current_price,
            "pdh": pdh,
            "pdl": pdl,
            "pdc": pdc,
            "atm_strike": atm_strike,
            "strikes": strikes,
            "recommendation": recommendation
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/terminal/status")
def terminal_status(user: str = Depends(get_current_user)):
    return {
        "active_broker": TERMINAL_STATE["active_broker"],
        "is_connected": TERMINAL_STATE["is_connected"],
        "broker_display_id": TERMINAL_STATE["broker_display_id"],
        "auto_trade_enabled": TERMINAL_STATE["auto_trade_enabled"],
        "risk_settings": TERMINAL_STATE["risk_settings"],
        "logs": TERMINAL_STATE["logs"][-20:]
    }

@app.post("/api/broker/link")
def link_broker(req: BrokerLinkRequest, user: str = Depends(get_current_user)):
    broker = req.broker.lower()
    try:
        if broker == "dhan":
            client = dhanhq(req.client_id, req.access_token)
            broker_instances["client"] = client
        elif broker == "angelone":
            smart_api = SmartConnect(api_key=req.api_key)
            totp = pyotp.TOTP(req.totp_secret).now() if req.totp_secret else ""
            session = smart_api.generateSession(req.client_id, req.pin, totp)
            if not session.get("status"):
                raise HTTPException(status_code=400, detail="Angel One Login Failed: " + session.get("message"))
            broker_instances["client"] = smart_api
        elif broker == "sbi":
            broker_instances["client"] = {"broker": "sbi", "client_id": req.client_id}
        elif broker in ["zerodha", "upstox"]:
            broker_instances["client"] = {"broker": broker, "api_key": req.api_key}

        TERMINAL_STATE["active_broker"] = broker.upper()
        TERMINAL_STATE["is_connected"] = True
        masked = req.client_id[:3] + "****" + req.client_id[-2:] if len(req.client_id) > 5 else req.client_id
        TERMINAL_STATE["broker_display_id"] = masked
        TERMINAL_STATE["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - {broker.upper()} ({masked}) सफलतापूर्वक लिंक हुआ।")
        return {"status": "success", "message": f"{broker.upper()} कनेक्ट हो गया है!"}
    except Exception as e:
        TERMINAL_STATE["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - {broker.upper()} लिंक एरर: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/broker/unlink")
def unlink_broker(user: str = Depends(get_current_user)):
    b_name = TERMINAL_STATE["active_broker"] or "ब्रोकर"
    broker_instances.clear()
    TERMINAL_STATE["active_broker"] = None
    TERMINAL_STATE["is_connected"] = False
    TERMINAL_STATE["broker_display_id"] = ""
    TERMINAL_STATE["auto_trade_enabled"] = False
    TERMINAL_STATE["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - {b_name} अनलिंक किया गया।")
    return {"status": "success", "message": "ब्रोकर सफलतापूर्वक डिस्कनेक्ट हुआ।"}

@app.get("/", response_class=HTMLResponse)
def read_root():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return "<h1>index.html फ़ाइल नहीं मिली!</h1>"
@app.post("/api/settings/save")
def save_settings(req: RiskSettingsRequest, user: str = Depends(get_current_user)):
    TERMINAL_STATE["risk_settings"]["lots"] = req.lots
    TERMINAL_STATE["risk_settings"]["target_inr"] = req.target_inr
    TERMINAL_STATE["risk_settings"]["stoploss_inr"] = req.stoploss_inr
    TERMINAL_STATE["auto_trade_enabled"] = req.auto_trade
    status_txt = "चालू" if req.auto_trade else "बंद"
    TERMINAL_STATE["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - सेटिंग्स सेव: Lots={req.lots}, Target=₹{req.target_inr}, SL=₹{req.stoploss_inr}, AutoTrade={status_txt}")
    return {"status": "success", "message": "रिस्क सेटिंग्स सुरक्षित हो गईं!"}

@app.post("/api/order/buy-option")
def buy_option(req: OptionBuyRequest, user: str = Depends(get_current_user)):
    if not TERMINAL_STATE["is_connected"]:
        raise HTTPException(status_code=400, detail="पहले ब्रोकर लिंक करें!")
    
    order_desc = f"BUY {req.symbol} {req.strike} {req.option_type} ({req.lots} Lot)"
    TERMINAL_STATE["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - [ORDER PLACED] {order_desc}")
    return {"status": "success", "message": f"सफल: {order_desc}"}
    if __name__ == "__main__":
        import uvicorn
        port = int(os.environ.get("PORT", 10000))
        uvicorn.run("app:app", host="0.0.0.0", port=port)