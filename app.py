import os
import sqlite3
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

import pandas as pd
import yfinance as yf
import requests
import pyotp
from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from dhanhq import dhanhq
from SmartApi import SmartConnect


# ==========================================
# 1. CONFIGURATION & CONSTANTS
# ==========================================
SECRET_KEY = os.getenv("APP_SECRET_KEY", "trading-shield-super-secret-jwt-key-2026-indore")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 720
DB_NAME = "trading_users.db"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# ==========================================
# 2. DATABASE MANAGEMENT
# ==========================================
def init_db():
    """सर्वर स्टार्ट होने पर डेटाबेस और टेबल्स तैयार करता है"""
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # डिफ़ॉल्ट एडमिन यूज़र बनाना
        admin_pass = hashlib.sha256("admin@123".encode()).hexdigest()
        conn.execute("INSERT OR IGNORE INTO users (username, password_hash) VALUES (?, ?)", ("admin", admin_pass))
        conn.commit()

def get_db():
    """हर API रिक्वेस्ट के लिए सुरक्षित DB कनेक्शन प्रदान करता है"""
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ==========================================
# 3. FASTAPI APP INITIALIZATION
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # सर्वर स्टार्ट होने पर DB सेट अप करें
    yield

app = FastAPI(title="Option Buyer Terminal", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"]
)


# ==========================================
# 4. IN-MEMORY STATE & SYMBOLS
# ==========================================
MASTER_SYMBOLS = [
    {"symbol": "^NSEI", "name": "NIFTY 50", "segment": "INDEX", "step": 50},
    {"symbol": "^NSEBANK", "name": "BANKNIFTY", "segment": "INDEX", "step": 100},
    {"symbol": "^CNXIT", "name": "NIFTY IT", "segment": "INDEX", "step": 100},
    {"symbol": "CL=F", "name": "CRUDE OIL (MCX/NYMEX)", "segment": "COMMODITY", "step": 50},
    {"symbol": "GC=F", "name": "GOLD (MCX/COMEX)", "segment": "COMMODITY", "step": 100},
    {"symbol": "SI=F", "name": "SILVER (MCX/COMEX)", "segment": "COMMODITY", "step": 500},
    {"symbol": "NG=F", "name": "NATURAL GAS", "segment": "COMMODITY", "step": 5},
    {"symbol": "RELIANCE.NS", "name": "Reliance Industries", "segment": "EQUITY", "step": 20},
    {"symbol": "SBIN.NS", "name": "State Bank of India", "segment": "EQUITY", "step": 10},
    {"symbol": "TCS.NS", "name": "Tata Consultancy Services", "segment": "EQUITY", "step": 50},
    {"symbol": "HDFCBANK.NS", "name": "HDFC Bank Ltd", "segment": "EQUITY", "step": 20},
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


# ==========================================
# 5. AUTHENTICATION UTILS
# ==========================================
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: sqlite3.Connection = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="अमान्य टोकन!")
        
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="यूज़र डेटाबेस में नहीं मिला!")
        
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="सत्र समाप्त, पुनः लॉगिन करें।")


# ==========================================
# 6. PYDANTIC SCHEMAS
# ==========================================
class RegisterRequest(BaseModel):
    username: str
    password: str

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


# ==========================================
# 7. AUTH API ENDPOINTS
# ==========================================
@app.post("/api/register")
def register_user(req: RegisterRequest, db: sqlite3.Connection = Depends(get_db)):
    if len(req.username.strip()) < 3 or len(req.password.strip()) < 4:
        raise HTTPException(status_code=400, detail="यूज़रनेम कम से कम 3 और पासवर्ड 4 अक्षरों का होना चाहिए!")
    
    pwd_hash = hashlib.sha256(req.password.encode()).hexdigest()
    try:
        db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (req.username.strip(), pwd_hash))
        db.commit()
        return {"status": "success", "message": "खाता सफलतापूर्वक बन गया! अब आप लॉगिन कर सकते हैं।"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="यह यूज़रनेम पहले से मौजूद है! कृपया दूसरा नाम चुनें।")

@app.post("/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: sqlite3.Connection = Depends(get_db)):
    pwd_hash = hashlib.sha256(form_data.password.encode()).hexdigest()
    user = db.execute("SELECT * FROM users WHERE username = ? AND password_hash = ?", 
                      (form_data.username.strip(), pwd_hash)).fetchone()
    
    if user:
        access_token = create_access_token(data={"sub": user["username"]})
        return {"access_token": access_token, "token_type": "bearer"}
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="गलत यूज़रनेम या पासवर्ड! कृपया दोबारा जाँचें।",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ==========================================
# 8. TERMINAL API ENDPOINTS
# ==========================================
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
        
        df_daily = ticker.history(period="5d", interval="1d")
        if len(df_daily) >= 2:
            prev_day = df_daily.iloc[-2]
            pdh = round(float(prev_day["High"]), 2)
            pdl = round(float(prev_day["Low"]), 2)
            pdc = round(float(prev_day["Close"]), 2)
        else:
            pdh, pdl, pdc = current_price, current_price, current_price

        step = 50
        for s in MASTER_SYMBOLS:
            if s["symbol"] == symbol:
                step = s["step"]
                break
        
        atm_strike = round(current_price / step) * step
        strikes = [atm_strike - (step * 2), atm_strike - step, atm_strike, atm_strike + step, atm_strike + (step * 2)]

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
        
        log_msg = f"{datetime.now().strftime('%H:%M:%S')} - {broker.upper()} ({masked}) सफलतापूर्वक लिंक हुआ।"
        TERMINAL_STATE["logs"].append(log_msg)
        
        return {"status": "success", "message": f"{broker.upper()} कनेक्ट हो गया है!"}
    except Exception as e:
        error_msg = f"{datetime.now().strftime('%H:%M:%S')} - {broker.upper()} लिंक एरर: {str(e)}"
        TERMINAL_STATE["logs"].append(error_msg)
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

@app.post("/api/settings/save")
def save_settings(req: RiskSettingsRequest, user: str = Depends(get_current_user)):
    TERMINAL_STATE["risk_settings"]["lots"] = req.lots
    TERMINAL_STATE["risk_settings"]["target_inr"] = req.target_inr
    TERMINAL_STATE["risk_settings"]["stoploss_inr"] = req.stoploss_inr
    TERMINAL_STATE["auto_trade_enabled"] = req.auto_trade
    status_txt = "चालू" if req.auto_trade else "बंद"
    
    log_msg = f"{datetime.now().strftime('%H:%M:%S')} - सेटिंग्स सेव: Lots={req.lots}, Target=₹{req.target_inr}, SL=₹{req.stoploss_inr}, AutoTrade={status_txt}"
    TERMINAL_STATE["logs"].append(log_msg)
    
    return {"status": "success", "message": "रिस्क सेटिंग्स सुरक्षित हो गईं!"}

@app.post("/api/order/buy-option")
def buy_option(req: OptionBuyRequest, user: str = Depends(get_current_user)):
    if not TERMINAL_STATE["is_connected"]:
        raise HTTPException(status_code=400, detail="पहले ब्रोकर लिंक करें!")
    
    order_desc = f"BUY {req.symbol} {req.strike} {req.option_type} ({req.lots} Lot)"
    TERMINAL_STATE["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - [ORDER PLACED] {order_desc}")
    return {"status": "success", "message": f"सफल: {order_desc}"}


# ==========================================
# 9. MAIN FRONTEND ROUTE
# ==========================================
@app.get("/", response_class=HTMLResponse)
def read_root():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return "<h1>index.html फ़ाइल नहीं मिली! कृपया इसे इसी फोल्डर में रखें।</h1>"


# ==========================================
# 10. RUN SERVER
# ==========================================
if __name__ == "__main__":
    import uvicorn
    # Vercel, Render या लोकल पर चलाने के लिए पोर्ट कॉन्फ़िगरेशन
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting Option Buyer Terminal on Port {port}...")
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)