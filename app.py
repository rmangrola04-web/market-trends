import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
import yfinance as yf
import pandas as pd
import numpy as np

app = FastAPI(title="Universal Indian Stock Market Terminal")

# क्विक लिस्ट (Quick Select List)
CATEGORIZED_ASSETS = {
    "INDEX F&O / FUTURES": {
        "NIFTY 50 FUTURES": "^NSEI",
        "BANK NIFTY FUTURES": "^NSEBANK",
        "FIN NIFTY FUTURES": "NIFTY_FIN_SERVICE.NS",
        "SENSEX FUTURES": "^BSESN",
        "MIDCAP SELECT FUTURES": "^NSEMDCP50"
    },
    "COMMODITIES & FUTURES": {
        "CRUDE OIL FUTURES": "CL=F",
        "NATURAL GAS FUTURES": "NG=F",
        "GOLD FUTURES": "GC=F",
        "SILVER FUTURES": "SI=F"
    },
    "TOP CASH & POPULAR": {
        "RELIANCE": "RELIANCE.NS",
        "HDFC BANK": "HDFCBANK.NS",
        "ICICI BANK": "ICICIBANK.NS",
        "STATE BANK OF INDIA": "SBIN.NS",
        "TCS": "TCS.NS",
        "INFOSYS": "INFY.NS",
        "ZOMATO": "ZOMATO.NS",
        "SUZLON ENERGY": "SUZLON.NS",
        "JIO FINANCIAL": "JIOFIN.NS",
        "IRFC": "IRFC.NS",
        "TATA MOTORS": "TATAMOTORS.NS",
        "BSE LIMITED": "BSE.NS"
    }
}

ALL_SYMBOLS = {}
for cat, items in CATEGORIZED_ASSETS.items():
    ALL_SYMBOLS.update(items)

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

@app.get("/api/categories")
def get_categories():
    return CATEGORIZED_ASSETS

@app.get("/api/data")
def get_market_data(symbol_key: str = "NIFTY 50 FUTURES", timeframe: str = "5m"):
    raw_query = symbol_key.strip().upper()
    
    # यदि प्री-डिफ़ाइन्ड लिस्ट में है तो वह टिकर लें, वर्ना सीधे NSE / Yahoo टिकर बनाएं
    if raw_query in ALL_SYMBOLS:
        ticker = ALL_SYMBOLS[raw_query]
    elif raw_query.startswith("^") or "=" in raw_query or raw_query.endswith(".NS") or raw_query.endswith(".BO"):
        ticker = raw_query
    else:
        # डिफ़ॉल्ट रूप से किसी भी भारतीय कैश स्टॉक के आगे .NS जोड़ें
        ticker = f"{raw_query}.NS"

    period_map = {
        "1m": "1d",
        "2m": "1d",
        "3m": "5d",
        "5m": "5d",
        "15m": "1mo",
        "30m": "1mo",
        "1h": "1mo",
        "1d": "1y",
        "1wk": "2y"
    }
    selected_period = period_map.get(timeframe, "5d")
    yf_interval = "60m" if timeframe == "1h" else ("1wk" if timeframe == "1wk" else timeframe)
    
    try:
        df = yf.download(ticker, period=selected_period, interval=yf_interval, progress=False)
        
        # अगर NSE पर न मिले तो BSE (.BO) चेक करें
        if df.empty and not raw_query.startswith("^") and "=" not in raw_query:
            ticker = f"{raw_query}.BO"
            df = yf.download(ticker, period=selected_period, interval=yf_interval, progress=False)
            
        daily_df = yf.download(ticker, period="5d", interval="1d", progress=False)
        
        if df.empty:
            return {"error": f"Symbol '{raw_query}' not found. Please check spelling."}
            
        if len(df) < 10:
            df = yf.download(ticker, period="1mo", interval="1d", progress=False)
            daily_df = df
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if isinstance(daily_df.columns, pd.MultiIndex):
            daily_df.columns = daily_df.columns.get_level_values(0)
            
        df['EMA_9'] = df['Close'].ewm(span=9, adjust=False).mean()
        df['EMA_21'] = df['Close'].ewm(span=21, adjust=False).mean()
        df['RSI'] = calculate_rsi(df['Close'], 14)
        
        df = df.dropna()
        latest = df.iloc[-1]
        
        prev_day = daily_df.iloc[-2] if len(daily_df) >= 2 else daily_df.iloc[-1]
        prev_high = float(prev_day['High'])
        prev_low = float(prev_day['Low'])
        prev_close = float(prev_day['Close'])
        
        pivot = (prev_high + prev_low + prev_close) / 3.0
        r1 = (2 * pivot) - prev_low
        s1 = (2 * pivot) - prev_high
        r2 = pivot + (prev_high - prev_low)
        s2 = pivot - (prev_high - prev_low)
        
        ltp = float(latest['Close'])
        rsi_val = float(latest['RSI'])
        ema9 = float(latest['EMA_9'])
        ema21 = float(latest['EMA_21'])
        
        # स्ट्राइक साइज ऑटो-कैलकुलेशन
        if "BANK NIFTY" in raw_query:
            strike_step = 100
        elif "SENSEX" in raw_query:
            strike_step = 100
        elif "NIFTY" in raw_query or "CRUDE" in raw_query:
            strike_step = 50
        elif ltp < 100:
            strike_step = 2.5
        elif ltp < 500:
            strike_step = 10
        elif ltp < 2000:
            strike_step = 20
        else:
            strike_step = 50
            
        atm_strike = round(ltp / strike_step) * strike_step
        itm_call_strike = atm_strike - strike_step
        itm_put_strike = atm_strike + strike_step
        
        signal = "WAIT / NO TRADE ZONE"
        signal_type = "neutral"
        strike_recommendation = f"ATM: {atm_strike} | ITM: {itm_call_strike} CE / {itm_put_strike} PE"

        if ltp > ema9 > ema21 and rsi_val > 55:
            signal = "BUY CALL (CE) / BUY CASH"
            signal_type = "buy"
            target_price = round(r2 if ltp > r1 else r1, 2)
            stop_loss = round(ema21 if ema21 < ltp else s1, 2)
            strike_recommendation = f"{itm_call_strike} CE (ITM) / {atm_strike} CE (ATM)"
        elif ltp < ema9 < ema21 and rsi_val < 45:
            signal = "BUY PUT (PE) / SHORT"
            signal_type = "sell"
            target_price = round(s2 if ltp < s1 else s1, 2)
            stop_loss = round(ema21 if ema21 > ltp else r1, 2)
            strike_recommendation = f"{itm_put_strike} PE (ITM) / {atm_strike} PE (ATM)"
        else:
            target_price = round(r1, 2)
            stop_loss = round(s1, 2)

        candles = []
        for idx, row in df.iterrows():
            candles.append({
                "time": int(idx.timestamp()),
                "open": round(float(row['Open']), 2),
                "high": round(float(row['High']), 2),
                "low": round(float(row['Low']), 2),
                "close": round(float(row['Close']), 2)
            })

        currency_symbol = "$" if ("=" in ticker or ticker in ["CL=F", "NG=F", "GC=F", "SI=F"]) else "₹"

        return {
            "symbol": raw_query,
            "ticker": ticker,
            "currency": currency_symbol,
            "ltp": round(ltp, 2),
            "rsi": round(rsi_val, 2),
            "signal": signal,
            "signal_type": signal_type,
            "strike_rec": strike_recommendation,
            "levels": {
                "entry": round(ltp, 2),
                "target": target_price,
                "stop_loss": stop_loss,
                "pivot": round(pivot, 2),
                "r1": round(r1, 2),
                "r2": round(r2, 2),
                "s1": round(s1, 2),
                "s2": round(s2, 2)
            },
            "candles": candles
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/", response_class=FileResponse)
def serve_index():
    return FileResponse("index.html")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
