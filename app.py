import os
import sqlite3
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

import yfinance as yf
import requests
import pyotp
from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
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
# 2. HTML + JS (FRONTEND INTEGRATED)
# ==========================================
# अब HTML को Python के अंदर ही रखा गया है, ताकि कैशिंग और रिफ्रेश की समस्या न आए।
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="hi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Options Pro Terminal</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans antialiased">

  <div id="loginOverlay" class="flex items-center justify-center min-h-screen px-4">
    <div class="bg-slate-900 border border-slate-800 p-8 rounded-2xl w-full max-w-md shadow-2xl">
      <div class="flex items-center justify-center mb-6">
        <span class="text-3xl mr-2">🎯</span>
        <h1 id="authTitle" class="text-2xl font-black text-sky-400">ऑप्शन बाइंग टर्मिनल</h1>
      </div>
      <form id="loginForm" class="space-y-4">
        <div>
          <label class="block text-[11px] uppercase text-slate-400 mb-1">यूज़रनेम</label>
          <input id="usernameInput" type="text" value="admin" required class="w-full bg-slate-800 border border-slate-700 px-4 py-2.5 rounded-lg text-sm">
        </div>
        <div>
          <label class="block text-[11px] uppercase text-slate-400 mb-1">पासवर्ड</label>
          <input id="passwordInput" type="password" placeholder="••••••••" required class="w-full bg-slate-800 border border-slate-700 px-4 py-2.5 rounded-lg text-sm">
        </div>
        <button id="loginSubmitBtn" type="submit" class="w-full bg-sky-600 hover:bg-sky-500 font-bold py-2.5 rounded-lg transition">सुरक्षित लॉगिन</button>
      </form>
      <div class="mt-4 text-center">
        <button id="toggleAuthBtn" onclick="toggleAuthMode()" class="text-sm text-sky-400 hover:underline">नया खाता बनाएं (Sign Up)</button>
      </div>
    </div>
  </div>

  <div id="mainTerminal" class="hidden max-w-7xl mx-auto p-4 space-y-6">
    <header class="flex flex-wrap justify-between items-center border-b border-slate-800 pb-4 gap-4">
      <div>
        <h1 class="text-2xl font-black text-transparent bg-clip-text bg-gradient-to-r from-sky-400 to-emerald-400">OPTION BUYER PRO</h1>
        <p class="text-xs text-slate-400 font-mono" id="clock"></p>
      </div>
      <div class="relative w-full md:w-80">
        <div class="flex items-center bg-slate-900 border border-slate-700 rounded-xl px-3 py-2">
          <span class="text-slate-400 mr-2">🔍</span>
          <input id="searchBar" type="text" placeholder="सर्च: NIFTY, Crude, Reliance..." oninput="handleSearch(this.value)" class="bg-transparent text-xs w-full focus:outline-none">
        </div>
        <div id="searchResults" class="absolute left-0 right-0 top-12 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl z-50 hidden max-h-60 overflow-y-auto"></div>
      </div>
      <div class="flex items-center gap-3">
        <div id="connectionBadge" class="text-xs font-semibold px-3 py-1.5 rounded-lg bg-rose-500/20 text-rose-400 border border-rose-500/30">ब्रोकर: अन-लिंक ✕</div>
        <button onclick="logoutUser()" class="text-xs bg-slate-800 border border-slate-700 px-3 py-1.5 rounded-lg hover:bg-slate-700">लॉगआउट 🔒</button>
      </div>
    </header>

    <div class="grid grid-cols-2 md:grid-cols-5 gap-3">
      <div class="bg-slate-900 border border-slate-800 p-3 rounded-xl"><div class="text-[10px] text-slate-400">वर्तमान स्टॉक</div><div id="dispSymbol" class="text-sm font-bold text-sky-400">--</div></div>
      <div class="bg-slate-900 border border-slate-800 p-3 rounded-xl"><div class="text-[10px] text-slate-400">लाइव कीमत</div><div id="dispPrice" class="text-sm font-bold">₹ --</div></div>
      <div class="bg-slate-900 border border-slate-800 p-3 rounded-xl border-l-4 border-l-emerald-500"><div class="text-[10px] text-emerald-400">PDH</div><div id="dispPDH" class="text-sm font-bold text-emerald-400">₹ --</div></div>
      <div class="bg-slate-900 border border-slate-800 p-3 rounded-xl border-l-4 border-l-rose-500"><div class="text-[10px] text-rose-400">PDL</div><div id="dispPDL" class="text-sm font-bold text-rose-400">₹ --</div></div>
      <div class="bg-slate-900 border border-slate-800 p-3 rounded-xl"><div class="text-[10px] text-amber-400">सिग्नल</div><div id="dispSignal" class="text-xs font-bold text-amber-400">NEUTRAL</div></div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div class="lg:col-span-2 bg-slate-900 border border-slate-800 p-4 rounded-2xl shadow-xl">
        <div class="flex justify-between items-center mb-2">
          <span class="text-xs font-bold text-slate-300">इंट्राडे टेक्निकल चार्ट</span>
          <span class="text-[10px] text-emerald-400">● Live 5M</span>
        </div>
        <div id="tvChart" class="w-full h-96 rounded-lg overflow-hidden"></div>
      </div>

      <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl shadow-xl flex flex-col justify-between">
        <div>
          <h2 class="text-sm font-bold text-emerald-400 mb-3">ऑप्शन बाइंग (CE / PE)</h2>
          <div class="space-y-4">
            <div>
              <label class="text-[10px] text-slate-400">स्ट्राइक प्राइस चुनें</label>
              <select id="optStrike" class="w-full bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-700 mt-1"></select>
            </div>
            <div>
              <label class="text-[10px] text-slate-400">क्वांटिटी</label>
              <input id="optLots" type="number" value="1" min="1" class="w-full bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-700 mt-1">
            </div>
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3 pt-4">
          <button onclick="executeOptionOrder('CE')" class="bg-emerald-600 hover:bg-emerald-500 text-xs font-black py-3 rounded-xl transition">BUY CALL (CE)</button>
          <button onclick="executeOptionOrder('PE')" class="bg-rose-600 hover:bg-rose-500 text-xs font-black py-3 rounded-xl transition">BUY PUT (PE)</button>
        </div>
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
      <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl shadow-xl">
        <h2 class="text-sm font-bold text-sky-400 mb-3">मल्टी-ब्रोकर गेटवे</h2>
        <select id="brokerSelect" onchange="renderBrokerForm()" class="w-full bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-700 mb-3">
          <option value="dhan">Dhan (धन)</option>
          <option value="angelone">Angel One</option>
        </select>
        <div id="brokerFields" class="space-y-2 mb-3"></div>
        <div class="flex gap-2">
          <button onclick="linkSelectedBroker()" class="w-1/2 bg-emerald-600 py-2 rounded-lg text-xs font-bold">लिंक करें</button>
          <button onclick="unlinkSelectedBroker()" class="w-1/2 bg-rose-600 py-2 rounded-lg text-xs font-bold">अन-लिंक</button>
        </div>
      </div>

      <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl shadow-xl">
        <h2 class="text-xs font-bold text-slate-400 mb-2">सिस्टम ऑडिट ट्रेल (Logs)</h2>
        <div id="logContainer" class="bg-black/60 p-4 rounded-xl font-mono text-xs text-emerald-400 h-40 overflow-y-auto space-y-1"></div>
      </div>
    </div>
  </div>

  <script>
    let authToken = localStorage.getItem("token");
    let currentActiveSymbol = "RELIANCE.NS";
    let loadedChartSymbol = ""; 
    let isSignUpMode = false;

    setInterval(() => {
      document.getElementById("clock").innerText = new Date().toLocaleString("hi-IN", { timeZone: "Asia/Kolkata" });
    }, 1000);

    if (authToken) initTerminal();

    function toggleAuthMode() {
      isSignUpMode = !isSignUpMode;
      document.getElementById("authTitle").innerText = isSignUpMode ? "नया रजिस्ट्रेशन" : "ऑप्शन टर्मिनल";
      document.getElementById("loginSubmitBtn").innerText = isSignUpMode ? "रजिस्टर करें" : "लॉगिन";
      document.getElementById("toggleAuthBtn").innerText = isSignUpMode ? "पहले से खाता है? लॉगिन करें" : "नया खाता बनाएं (Sign Up)";
    }

    document.getElementById("loginForm").onsubmit = async (e) => {
      e.preventDefault();
      const u = document.getElementById("usernameInput").value.trim();
      const p = document.getElementById("passwordInput").value.trim();
      if (isSignUpMode) {
        const res = await fetch("/api/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: u, password: p }) });
        const data = await res.json();
        alert(data.message || data.detail);
        if (res.ok) toggleAuthMode();
      } else {
        const fd = new FormData(); fd.append("username", u); fd.append("password", p);
        const res = await fetch("/token", { method: "POST", body: fd });
        if (res.ok) {
          authToken = (await res.json()).access_token; localStorage.setItem("token", authToken); initTerminal();
        } else alert("गलत यूज़रनेम या पासवर्ड!");
      }
    };

    function logoutUser() { localStorage.removeItem("token"); location.reload(); }

    function initTerminal() {
      document.getElementById("loginOverlay").classList.add("hidden");
      document.getElementById("mainTerminal").classList.remove("hidden");
      renderBrokerForm();
      loadMarketData(currentActiveSymbol);
      fetchStatus();
      setInterval(fetchStatus, 3000);
      setInterval(() => loadMarketData(currentActiveSymbol), 10000); // 10s auto-refresh
    }

    async function handleSearch(query) {
      const box = document.getElementById("searchResults");
      if (!query.trim()) return box.classList.add("hidden");
      const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`, { headers: { "Authorization": `Bearer ${authToken}` }});
      if (res.ok) {
        const list = await res.json();
        box.innerHTML = list.map(i => `<div onclick="selectSymbol('${i.symbol}')" class="p-2 hover:bg-slate-800 cursor-pointer text-xs">${i.name} (${i.symbol})</div>`).join("");
        box.classList.remove("hidden");
      }
    }

    function selectSymbol(sym) {
      currentActiveSymbol = sym;
      document.getElementById("searchResults").classList.add("hidden");
      document.getElementById("searchBar").value = "";
      loadMarketData(sym);
    }

    async function loadMarketData(sym) {
      try {
        const res = await fetch(`/api/market-data?symbol=${encodeURIComponent(sym)}`, { headers: { "Authorization": `Bearer ${authToken}` }});
        if (res.ok) {
          const d = await res.json();
          document.getElementById("dispSymbol").innerText = d.symbol;
          document.getElementById("dispPrice").innerText = `₹ ${d.current_price}`;
          document.getElementById("dispPDH").innerText = `₹ ${d.pdh}`;
          document.getElementById("dispPDL").innerText = `₹ ${d.pdl}`;
          document.getElementById("dispSignal").innerText = d.recommendation;

          // स्ट्राइक प्राइस ड्रॉपडाउन सिर्फ तभी अपडेट होगा जब नया सिंबल चुना हो
          const sel = document.getElementById("optStrike");
          if (loadedChartSymbol !== sym) {
             sel.innerHTML = d.strikes.map(s => `<option value="${s}" ${s === d.atm_strike ? 'selected' : ''}>${s} ${s === d.atm_strike ? '(ATM)' : ''}</option>`).join("");
          }
          
          renderTradingViewChart(sym);
        }
      } catch (e) {}
    }

    function renderTradingViewChart(sym) {
      // ✅ CHART AUTO REFRESH FIX: अगर सिंबल सेम है, तो चार्ट को मत छेड़ो।
      if (loadedChartSymbol === sym) return;
      loadedChartSymbol = sym;

      let tvSymbol = "BSE:" + sym.replace(".NS", "").replace(".BO", "");
      if (sym === "CL=F") tvSymbol = "TVC:USOIL";
      else if (sym === "^NSEI") tvSymbol = "NSE:NIFTY";
      else if (sym === "^NSEBANK") tvSymbol = "NSE:BANKNIFTY";
      else if (sym.includes("RELIANCE")) tvSymbol = "BSE:RELIANCE";

      document.getElementById("tvChart").innerHTML = `
        <iframe style="width: 100%; height: 100%; min-height: 480px; border: none; border-radius: 8px;" 
        src="https://s.tradingview.com/widgetembed/?frameElementId=tradingview_widget&symbol=${encodeURIComponent(tvSymbol)}&interval=5&hidesidetoolbar=0&symboledit=1&saveimage=1&toolbarbg=131722&studies=[]&theme=dark&style=1&timezone=Asia%2FKolkata&locale=in"></iframe>
      `;
    }

    function renderBrokerForm() {
      const b = document.getElementById("brokerSelect").value;
      const f = document.getElementById("brokerFields");
      if (b === "dhan") f.innerHTML = `<input id="f_cid" placeholder="Client ID" class="w-full bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-700 mb-2"><input id="f_tok" type="password" placeholder="Access Token" class="w-full bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-700">`;
      else f.innerHTML = `<input id="f_cid" placeholder="Client Code" class="w-full bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-700 mb-2"><input id="f_key" placeholder="SmartAPI Key" class="w-full bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-700 mb-2"><input id="f_pin" type="password" placeholder="MPIN" class="w-full bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-700 mb-2"><input id="f_totp" type="password" placeholder="TOTP" class="w-full bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-700">`;
    }

    async function fetchStatus() {
      if (!authToken) return;
      const res = await fetch("/api/terminal/status", { headers: { "Authorization": `Bearer ${authToken}` }});
      if (res.status === 401) return logoutUser();
      const d = await res.json();
      const b = document.getElementById("connectionBadge");
      b.className = d.is_connected ? "text-xs font-semibold px-3 py-1.5 rounded-lg bg-emerald-500/20 text-emerald-400" : "text-xs font-semibold px-3 py-1.5 rounded-lg bg-rose-500/20 text-rose-400";
      b.innerText = d.is_connected ? `ब्रोकर: ${d.active_broker} ✓` : "ब्रोकर: अन-लिंक ✕";
      document.getElementById("logContainer").innerHTML = d.logs.map(l => `<div>${l}</div>`).reverse().join("");
    }

    async function linkSelectedBroker() {
      const payload = {
        broker: document.getElementById("brokerSelect").value,
        client_id: document.getElementById("f_cid")?.value || "",
        access_token: document.getElementById("f_tok")?.value || null,
        api_key: document.getElementById("f_key")?.value || null,
        pin: document.getElementById("f_pin")?.value || null,
        totp_secret: document.getElementById("f_totp")?.value || null
      };
      const res = await fetch("/api/broker/link", { method: "POST", headers: { "Content-Type": "application/json", "Authorization": `Bearer ${authToken}` }, body: JSON.stringify(payload) });
      alert((await res.json()).message || "एरर");
      fetchStatus();
    }

    async function unlinkSelectedBroker() {
      await fetch("/api/broker/unlink", { method: "POST", headers: { "Authorization": `Bearer ${authToken}` }});
      fetchStatus();
    }

    async function executeOptionOrder(type) {
      const payload = {
        symbol: currentActiveSymbol, strike: parseFloat(document.getElementById("optStrike").value), option_type: type, lots: parseInt(document.getElementById("optLots").value)
      };
      const res = await fetch("/api/order/buy-option", { method: "POST", headers: { "Content-Type": "application/json", "Authorization": `Bearer ${authToken}` }, body: JSON.stringify(payload) });
      const d = await res.json();
      alert(res.ok ? d.message : `एरर: ${d.detail}`);
      fetchStatus();
    }
  </script>
</body>
</html>
"""

# ==========================================
# 3. DATABASE SETUP
# ==========================================
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)")
        admin_pass = hashlib.sha256("admin@123".encode()).hexdigest()
        conn.execute("INSERT OR IGNORE INTO users (username, password_hash) VALUES (?, ?)", ("admin", admin_pass))
        conn.commit()

def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try: yield conn
    finally: conn.close()

# ==========================================
# 4. APP INIT
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="Option Terminal", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

MASTER_SYMBOLS = [
    {"symbol": "^NSEI", "name": "NIFTY 50", "segment": "INDEX", "step": 50},
    {"symbol": "^NSEBANK", "name": "BANKNIFTY", "segment": "INDEX", "step": 100},
    {"symbol": "CL=F", "name": "CRUDE OIL", "segment": "COMMODITY", "step": 50},
    {"symbol": "RELIANCE.NS", "name": "Reliance", "segment": "EQUITY", "step": 20},
]

TERMINAL_STATE = {
    "active_broker": None, "is_connected": False, "broker_display_id": "", "logs": [f"{datetime.now().strftime('%H:%M:%S')} - सिस्टम तैयार है।"]
}
broker_instances = {}

# ==========================================
# 5. API ROUTES
# ==========================================
def get_current_user(token: str = Depends(oauth2_scheme), db: sqlite3.Connection = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if not db.execute("SELECT * FROM users WHERE username = ?", (payload.get("sub"),)).fetchone(): raise HTTPException(401)
        return payload.get("sub")
    except JWTError: raise HTTPException(401, "सत्र समाप्त")

class AuthReq(BaseModel): username: str; password: str
class BrokerReq(BaseModel): broker: str; client_id: str; api_key: Optional[str] = None; access_token: Optional[str] = None; pin: Optional[str] = None; totp_secret: Optional[str] = None
class OrderReq(BaseModel): symbol: str; strike: float; option_type: str; lots: int

@app.post("/api/register")
def register(req: AuthReq, db: sqlite3.Connection = Depends(get_db)):
    try:
        db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (req.username.strip(), hashlib.sha256(req.password.encode()).hexdigest()))
        db.commit()
        return {"message": "रजिस्ट्रेशन सफल!"}
    except sqlite3.IntegrityError: raise HTTPException(400, "यूज़रनेम पहले से मौजूद है!")

@app.post("/token")
def login(form: OAuth2PasswordRequestForm = Depends(), db: sqlite3.Connection = Depends(get_db)):
    if db.execute("SELECT * FROM users WHERE username = ? AND password_hash = ?", (form.username, hashlib.sha256(form.password.encode()).hexdigest())).fetchone():
        return {"access_token": jwt.encode({"sub": form.username, "exp": datetime.utcnow() + timedelta(minutes=720)}, SECRET_KEY, algorithm=ALGORITHM), "token_type": "bearer"}
    raise HTTPException(401, "गलत यूज़रनेम/पासवर्ड")

@app.get("/api/search")
def search(q: str): return [s for s in MASTER_SYMBOLS if q.lower() in s["symbol"].lower() or q.lower() in s["name"].lower()][:10]

@app.get("/api/market-data")
def market_data(symbol: str):
    try:
        df = yf.Ticker(symbol).history(period="5d", interval="5m")
        df_d = yf.Ticker(symbol).history(period="5d", interval="1d")
        cp = round(float(df["Close"].iloc[-1]), 2)
        pdh = round(float(df_d.iloc[-2]["High"]), 2) if len(df_d) >= 2 else cp
        pdl = round(float(df_d.iloc[-2]["Low"]), 2) if len(df_d) >= 2 else cp
        
        step = next((s["step"] for s in MASTER_SYMBOLS if s["symbol"] == symbol), 50)
        atm = round(cp / step) * step
        
        return {"symbol": symbol, "current_price": cp, "pdh": pdh, "pdl": pdl, "atm_strike": atm, "strikes": [atm - (step*2), atm - step, atm, atm + step, atm + (step*2)], "recommendation": "BULLISH (CE)" if cp > pdh else "BEARISH (PE)" if cp < pdl else "NEUTRAL"}
    except Exception as e: raise HTTPException(400, str(e))

@app.get("/api/terminal/status")
def status_api(): return TERMINAL_STATE

@app.post("/api/broker/link")
def link(req: BrokerReq):
    try:
        if req.broker == "dhan": broker_instances["client"] = dhanhq(req.client_id, req.access_token)
        elif req.broker == "angelone":
            smart = SmartConnect(api_key=req.api_key)
            if not smart.generateSession(req.client_id, req.pin, pyotp.TOTP(req.totp_secret).now() if req.totp_secret else "").get("status"): raise Exception("Angel One Login Failed")
            broker_instances["client"] = smart
        
        TERMINAL_STATE.update({"active_broker": req.broker.upper(), "is_connected": True, "broker_display_id": req.client_id[:3]+"**"})
        TERMINAL_STATE["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - {req.broker.upper()} लिंक्ड।")
        return {"message": "ब्रोकर कनेक्ट हो गया!"}
    except Exception as e: raise HTTPException(400, str(e))

@app.post("/api/broker/unlink")
def unlink():
    broker_instances.clear(); TERMINAL_STATE.update({"active_broker": None, "is_connected": False})
    return {"message": "डिस्कनेक्टेड"}

@app.post("/api/order/buy-option")
def buy_order(req: OrderReq):
    if not TERMINAL_STATE["is_connected"]: raise HTTPException(400, "पहले ब्रोकर लिंक करें!")
    
    # 🔴 REAL ORDER PLACEMENT LOGIC
    broker = TERMINAL_STATE["active_broker"]
    client = broker_instances.get("client")
    order_msg = f"BUY {req.symbol} {req.strike} {req.option_type} ({req.lots} Lots)"

    try:
        if broker == "DHAN":
            # Dhan Order API Call
            client.place_order(
                security_id="13", # Placeholder ID
                exchange_segment=client.NSE_FNO,
                transaction_type=client.BUY,
                quantity=req.lots * 15, # Nifty lot size example
                order_type=client.MARKET,
                product_type=client.INTRADAY,
                price=0
            )
        elif broker == "ANGELONE":
            # Angel One Order API Call
            client.placeOrder({
                "variety": "NORMAL",
                "tradingsymbol": f"{req.symbol}{req.strike}{req.option_type}",
                "symboltoken": "3045", # Placeholder
                "transactiontype": "BUY",
                "exchange": "NFO",
                "ordertype": "MARKET",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "quantity": req.lots * 15
            })

        TERMINAL_STATE["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - [ORDER SUCCESS] {order_msg}")
        return {"message": f"ऑर्डर भेजा गया: {order_msg}"}
    except Exception as e:
        TERMINAL_STATE["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - [ORDER FAILED] {str(e)}")
        raise HTTPException(400, f"ऑर्डर फेल: {str(e)}")

@app.get("/", response_class=HTMLResponse)
def root(): return HTMLResponse(content=HTML_CONTENT)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), reload=True)