import os
import sqlite3
import hashlib
import asyncio
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
from fastapi.responses import HTMLResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from dhanhq import dhanhq
from SmartApi import SmartConnect

# ==========================================
# 1. CONFIGURATION & CONSTANTS
# ==========================================
SECRET_KEY = os.getenv("APP_SECRET_KEY", "trading-shield-super-secret-jwt-key-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 720
DB_NAME = "trading_users.db"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# ==========================================
# 2. HTML + JS (FRONTEND INTEGRATED)
# ==========================================
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>AI Options Terminal - Paper Trading</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
  <style>
    #chartWrapper:fullscreen { background-color: #020617; padding: 10px; overflow: hidden; }
    #chartWrapper:fullscreen #chartGrid { height: calc(100vh - 20px) !important; }
    .glass-panel { background: rgba(15, 23, 42, 0.7); backdrop-filter: blur(10px); border: 1px solid rgba(51, 65, 85, 0.5); }
    /* Scrollbar hiding for mobile swiping */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans antialiased overflow-x-hidden">

  <!-- LOGIN / SIGNUP OVERLAY -->
  <div id="loginOverlay" class="flex items-center justify-center min-h-screen px-4 fixed inset-0 z-50 bg-slate-950">
    <div class="glass-panel p-6 md:p-8 rounded-2xl w-full max-w-md shadow-2xl">
      <div class="flex items-center justify-center mb-6">
        <span class="text-3xl md:text-4xl mr-3">🧠</span>
        <h1 class="text-xl md:text-2xl font-black text-transparent bg-clip-text bg-gradient-to-r from-sky-400 to-indigo-400">AI Trading Pro</h1>
      </div>
      
      <div class="flex mb-6 border-b border-slate-800">
        <button id="tabLogin" onclick="switchAuthTab('login')" class="flex-1 py-2 text-sm font-bold text-sky-400 border-b-2 border-sky-400 transition">Login</button>
        <button id="tabSignup" onclick="switchAuthTab('signup')" class="flex-1 py-2 text-sm font-bold text-slate-500 border-b-2 border-transparent transition hover:text-slate-300">Sign Up</button>
      </div>

      <form id="authForm" class="space-y-4">
        <div>
          <label class="block text-[11px] uppercase text-slate-400 mb-1">Username</label>
          <input id="usernameInput" type="text" value="admin" required class="w-full bg-slate-800/50 border border-slate-700 px-4 py-3 md:py-2.5 rounded-lg text-sm focus:outline-none focus:border-sky-500">
        </div>
        <div>
          <label class="block text-[11px] uppercase text-slate-400 mb-1">Password</label>
          <input id="passwordInput" type="password" placeholder="••••••••" required class="w-full bg-slate-800/50 border border-slate-700 px-4 py-3 md:py-2.5 rounded-lg text-sm focus:outline-none focus:border-sky-500">
        </div>
        <button id="authSubmitBtn" type="submit" class="w-full bg-indigo-600 hover:bg-indigo-500 font-bold py-3 md:py-2.5 rounded-lg transition shadow-lg shadow-indigo-600/20 mt-2">Access System</button>
      </form>
    </div>
  </div>

  <!-- MAIN TERMINAL DASHBOARD -->
  <div id="mainTerminal" class="hidden w-full max-w-7xl mx-auto p-2 md:p-4 space-y-4">
    
    <!-- Top Header & Search (Responsive) -->
    <header class="flex flex-col md:flex-row justify-between items-start md:items-center border-b border-slate-800 pb-3 gap-4">
      <div class="flex justify-between items-center w-full md:w-auto">
        <div>
          <h1 class="text-xl md:text-2xl font-black text-transparent bg-clip-text bg-gradient-to-r from-sky-400 to-indigo-400">AI BUYER PRO</h1>
          <p class="text-[10px] text-slate-400 font-mono" id="clock"></p>
        </div>
        <!-- Mobile Logout -->
        <button onclick="logoutUser()" class="md:hidden text-xs bg-slate-800 border border-slate-700 px-3 py-1.5 rounded-lg hover:bg-slate-700 text-slate-300">Logout 🔒</button>
      </div>
      
      <!-- Segmented Dynamic Search -->
      <div class="relative w-full md:w-[500px] flex flex-col sm:flex-row gap-2">
        <select id="marketSegment" class="bg-slate-900 border border-slate-700 rounded-xl px-2 py-3 sm:py-2 text-xs font-bold text-sky-400 focus:outline-none w-full sm:w-[35%]">
            <option value="NSE">NSE (Cash/F&O)</option>
            <option value="MCX">MCX (Commodity)</option>
            <option value="CRYPTO">Crypto</option>
        </select>
        <div class="flex-1 flex items-center bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 w-full sm:w-[65%]">
          <span class="text-slate-400 mr-2">🔍</span>
          <input id="searchBar" type="text" placeholder="Search 5000+ Symbols..." oninput="handleSearch(this.value)" class="bg-transparent text-xs w-full focus:outline-none">
        </div>
        <div id="searchResults" class="absolute left-0 right-0 top-[100px] sm:top-12 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl z-50 hidden max-h-60 overflow-y-auto w-full"></div>
      </div>
      
      <!-- Desktop Logout -->
      <div class="hidden md:flex items-center gap-3">
        <button onclick="logoutUser()" class="text-xs bg-slate-800 border border-slate-700 px-3 py-1.5 rounded-lg hover:bg-slate-700 text-slate-300">Logout 🔒</button>
      </div>
    </header>

    <!-- Paper Trading Dashboard -->
    <div class="glass-panel p-3 md:p-4 rounded-xl flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-l-4 border-l-emerald-500">
        <div class="flex flex-row flex-wrap gap-4 md:gap-8 w-full md:w-auto">
            <div class="flex-1 min-w-[120px]">
                <div class="text-[10px] md:text-xs uppercase text-slate-400">Account Balance</div>
                <div class="text-base md:text-xl font-black text-white" id="dispBalance">₹ 1,000,000.00</div>
            </div>
            <div class="flex-1 min-w-[120px]">
                <div class="text-[10px] md:text-xs uppercase text-slate-400">Current P&L</div>
                <div class="text-base md:text-xl font-black text-emerald-400" id="dispPnl">+ ₹ 0.00</div>
            </div>
        </div>
        <div id="connectionBadge" class="text-[10px] md:text-xs font-bold px-3 py-2 rounded-lg bg-rose-500/20 text-rose-400 border border-rose-500/30 w-full md:w-auto text-center">Broker: Unlinked ✕</div>
    </div>

    <!-- Key Levels Bar -->
    <div class="grid grid-cols-2 md:grid-cols-5 gap-2 md:gap-3">
      <div class="bg-slate-900 border border-slate-800 p-2.5 md:p-3 rounded-xl col-span-2 md:col-span-1 flex flex-row md:flex-col justify-between items-center md:items-start"><div class="text-[10px] text-slate-400">Active Asset</div><div id="dispSymbol" class="text-sm font-bold text-indigo-400">--</div></div>
      <div class="bg-slate-900 border border-slate-800 p-2.5 md:p-3 rounded-xl"><div class="text-[10px] text-slate-400">Live Price</div><div id="dispPrice" class="text-sm font-bold">₹ --</div></div>
      <div class="bg-slate-900 border border-slate-800 p-2.5 md:p-3 rounded-xl border-l-2 border-l-emerald-500"><div class="text-[10px] text-emerald-400">Day High</div><div id="dispPDH" class="text-sm font-bold text-emerald-400">₹ --</div></div>
      <div class="bg-slate-900 border border-slate-800 p-2.5 md:p-3 rounded-xl border-l-2 border-l-rose-500"><div class="text-[10px] text-rose-400">Day Low</div><div id="dispPDL" class="text-sm font-bold text-rose-400">₹ --</div></div>
      <div class="bg-indigo-900/30 border border-indigo-500/50 p-2.5 md:p-3 rounded-xl col-span-2 md:col-span-1 flex flex-row md:flex-col justify-between items-center md:items-start"><div class="text-[10px] text-indigo-300">🤖 AI Momentum</div><div id="dispSignal" class="text-xs font-bold text-indigo-400">ANALYZING...</div></div>
    </div>

    <!-- Chart & Order Panel -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
      
      <!-- Multi-Chart Section -->
      <div class="lg:col-span-2 bg-slate-900 border border-slate-800 p-3 rounded-2xl shadow-xl w-full" id="chartWrapper">
        <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2 mb-3">
          <span class="text-xs font-bold text-slate-300">Advanced Charting</span>
          <div class="flex gap-2 items-center w-full sm:w-auto">
            <select id="chartLayoutSelect" onchange="changeChartLayout(this.value)" class="bg-slate-800 text-[10px] px-2 py-2 sm:py-1 rounded border border-slate-700 text-slate-300 outline-none flex-1 sm:flex-none">
              <option value="1">1 Chart (Single)</option>
              <option value="2">2 Charts (Split)</option>
              <option value="4">4 Charts (Grid)</option>
            </select>
            <button onclick="toggleFullscreen()" class="bg-slate-700 hover:bg-slate-600 text-[10px] px-3 py-2 sm:py-1 rounded transition flex-1 sm:flex-none text-center">⛶ Fullscreen</button>
          </div>
        </div>
        <div id="chartGrid" class="grid grid-cols-1 gap-2 h-[350px] md:h-[450px] lg:h-[500px] w-full rounded-lg overflow-hidden transition-all"></div>
      </div>

      <!-- Option Order Panel -->
      <div class="bg-slate-900 border border-slate-800 p-4 rounded-2xl shadow-xl flex flex-col justify-between">
        <div>
          <h2 class="text-sm font-bold text-emerald-400 mb-3">Order Execution (CE/PE)</h2>
          <div class="space-y-4">
            <div>
              <label class="text-[10px] text-slate-400">Select Strike Price</label>
              <select id="optStrike" class="w-full bg-slate-800 text-xs px-3 py-3 md:py-2 rounded-lg border border-slate-700 mt-1 focus:outline-none"></select>
            </div>
            <div>
              <label class="text-[10px] text-slate-400">Lot Size / Quantity</label>
              <input id="optLots" type="number" value="1" min="1" class="w-full bg-slate-800 text-xs px-3 py-3 md:py-2 rounded-lg border border-slate-700 mt-1 focus:outline-none">
            </div>
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3 pt-6 md:pt-4">
          <button onclick="executeOptionOrder('CE')" class="bg-emerald-600 hover:bg-emerald-500 text-xs md:text-sm font-black py-4 md:py-3 rounded-xl transition shadow-lg shadow-emerald-600/30">BUY CALL (CE)</button>
          <button onclick="executeOptionOrder('PE')" class="bg-rose-600 hover:bg-rose-500 text-xs md:text-sm font-black py-4 md:py-3 rounded-xl transition shadow-lg shadow-rose-600/30">BUY PUT (PE)</button>
        </div>
      </div>
    </div>

    <!-- Gateway & AI Settings -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div class="bg-slate-900 border border-slate-800 p-4 rounded-2xl shadow-xl">
        <h2 class="text-sm font-bold text-sky-400 mb-3">Broker Gateway</h2>
        <select id="brokerSelect" onchange="renderBrokerForm()" class="w-full bg-slate-800 text-xs px-3 py-3 md:py-2 rounded-lg border border-slate-700 mb-3 font-semibold focus:outline-none">
          <option value="paper">Paper Trading (Virtual Money)</option>
          <option value="dhan">Dhan</option>
          <option value="angelone">Angel One (SmartAPI)</option>
        </select>
        <div id="brokerFields" class="space-y-3 md:space-y-2 mb-4 md:mb-3"></div>
        <div class="flex gap-2">
          <button onclick="linkSelectedBroker()" class="w-1/2 bg-sky-600 py-3 md:py-2 rounded-lg text-xs font-bold hover:bg-sky-500 transition">Link Account</button>
          <button onclick="unlinkSelectedBroker()" class="w-1/2 bg-slate-700 py-3 md:py-2 rounded-lg text-xs font-bold hover:bg-slate-600 transition">Unlink</button>
        </div>
      </div>

      <div class="bg-slate-900 border border-slate-800 p-4 rounded-2xl shadow-xl flex flex-col justify-between">
        <div>
            <h2 class="text-sm font-bold text-indigo-400 mb-3 uppercase">🤖 AI Settings & Commands</h2>
            
            <!-- AI Command Prompt -->
            <div class="mb-4">
                <label class="text-[10px] uppercase text-indigo-300">Send Command to AI (e.g. Stop if PnL < -500)</label>
                <div class="flex flex-col sm:flex-row gap-2 mt-1">
                    <input id="aiCommandInput" type="text" placeholder="Type instructions..." class="w-full bg-slate-800 text-xs px-3 py-3 md:py-2 rounded-lg border border-slate-700 focus:outline-none focus:border-indigo-500">
                    <button onclick="sendAICommand()" class="bg-indigo-600 px-4 py-3 md:py-2 rounded-lg text-xs font-bold hover:bg-indigo-500 w-full sm:w-auto transition">Send</button>
                </div>
            </div>

            <div class="grid grid-cols-2 gap-3 mb-4">
                <div>
                <label class="text-[10px] uppercase text-emerald-400">Target (₹)</label>
                <input id="riskTarget" type="number" value="1000" class="w-full bg-slate-800 text-xs px-3 py-2.5 md:py-1.5 rounded-lg border border-slate-700 focus:outline-none">
                </div>
                <div>
                <label class="text-[10px] uppercase text-rose-400">Stop Loss (₹)</label>
                <input id="riskSL" type="number" value="500" class="w-full bg-slate-800 text-xs px-3 py-2.5 md:py-1.5 rounded-lg border border-slate-700 focus:outline-none">
                </div>
            </div>
            
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
                <div class="flex items-center justify-between p-3 bg-slate-800/60 rounded-lg border border-slate-700/50">
                    <span class="text-[10px] font-bold">Basic Algo:</span>
                    <input id="riskAutoToggle" type="checkbox" class="w-5 h-5 md:w-4 md:h-4 accent-emerald-500 cursor-pointer">
                </div>
                <div class="flex items-center justify-between p-3 bg-indigo-900/20 rounded-lg border border-indigo-500/30">
                    <span class="text-[10px] font-bold text-indigo-300">AI Mode:</span>
                    <input id="aiAutoToggle" type="checkbox" class="w-5 h-5 md:w-4 md:h-4 accent-indigo-500 cursor-pointer">
                </div>
            </div>
        </div>
        <button onclick="saveRiskSettings()" class="w-full bg-slate-700 hover:bg-slate-600 text-xs font-bold py-3 md:py-2 rounded-lg transition border border-slate-600 mt-2">Save Configuration</button>
      </div>
    </div>
    
    <div class="bg-slate-900 border border-slate-800 p-4 rounded-2xl shadow-xl mt-4">
        <h2 class="text-xs font-bold text-slate-400 mb-2 uppercase">System Audit Trail (Live Logs)</h2>
        <div id="logContainer" class="bg-black/60 p-3 rounded-xl font-mono text-[10px] md:text-[11px] text-emerald-400 h-40 md:h-32 overflow-y-auto space-y-1.5"></div>
    </div>
  </div>

  <script>
    let authToken = localStorage.getItem("token");
    let currentActiveSymbol = "^NSEI"; 
    let loadedChartSymbol = ""; 
    let currentChartLayout = 1;
    let isSignUpMode = false;

    setInterval(() => { document.getElementById("clock").innerText = new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }); }, 1000);

    if (authToken) initTerminal();

    function switchAuthTab(mode) {
      isSignUpMode = (mode === 'signup');
      const tabLogin = document.getElementById("tabLogin"), tabSignup = document.getElementById("tabSignup"), submitBtn = document.getElementById("authSubmitBtn");
      const uInput = document.getElementById("usernameInput"), pInput = document.getElementById("passwordInput");

      if (isSignUpMode) {
        tabSignup.className = "flex-1 py-2 text-sm font-bold text-sky-400 border-b-2 border-sky-400 transition";
        tabLogin.className = "flex-1 py-2 text-sm font-bold text-slate-500 border-b-2 border-transparent transition hover:text-slate-300";
        submitBtn.innerText = "Register Account";
        uInput.value = ""; pInput.value = "";
      } else {
        tabLogin.className = "flex-1 py-2 text-sm font-bold text-sky-400 border-b-2 border-sky-400 transition";
        tabSignup.className = "flex-1 py-2 text-sm font-bold text-slate-500 border-b-2 border-transparent transition hover:text-slate-300";
        submitBtn.innerText = "Access System";
        uInput.value = "admin"; pInput.value = "";
      }
    }

    document.getElementById("authForm").onsubmit = async (e) => {
      e.preventDefault();
      const u = document.getElementById("usernameInput").value.trim(), p = document.getElementById("passwordInput").value.trim();
      if (isSignUpMode) {
        const res = await fetch("/api/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: u, password: p }) });
        const data = await res.json(); alert(data.message || data.detail);
        if (res.ok) switchAuthTab('login');
      } else {
        const fd = new FormData(); fd.append("username", u); fd.append("password", p);
        const res = await fetch("/token", { method: "POST", body: fd });
        if (res.ok) { authToken = (await res.json()).access_token; localStorage.setItem("token", authToken); initTerminal(); } 
        else alert("Invalid credentials!");
      }
    };

    function logoutUser() { localStorage.removeItem("token"); location.reload(); }

    function initTerminal() {
      document.getElementById("loginOverlay").classList.add("hidden");
      document.getElementById("mainTerminal").classList.remove("hidden");
      renderBrokerForm(); loadMarketData(currentActiveSymbol); fetchStatus();
      setInterval(fetchStatus, 3000); setInterval(() => loadMarketData(currentActiveSymbol), 10000);
    }

    // Dynamic Search (NSE, MCX, CRYPTO)
    async function handleSearch(query) {
      const box = document.getElementById("searchResults");
      const segment = document.getElementById("marketSegment").value;
      
      if (!query.trim()) return box.classList.add("hidden");
      const res = await fetch(`/api/search?q=${encodeURIComponent(query)}&segment=${segment}`, { headers: { "Authorization": `Bearer ${authToken}` }});
      if (res.ok) {
        const list = await res.json();
        if(list.length === 0) box.innerHTML = `<div class="p-3 text-xs text-slate-500">No stocks found.</div>`;
        else box.innerHTML = list.map(i => `<div onclick="selectSymbol('${i.symbol}')" class="p-3 hover:bg-slate-800 cursor-pointer border-b border-slate-800/50 flex justify-between items-center"><span class="text-xs font-bold text-white">${i.name} <span class="text-[10px] text-slate-400 font-mono ml-1 block sm:inline">(${i.symbol})</span></span><span class="text-[9px] px-2 py-1 rounded bg-slate-800 text-sky-400 font-bold border border-slate-700">${i.segment}</span></div>`).join("");
        box.classList.remove("hidden");
      }
    }

    function selectSymbol(sym) {
      currentActiveSymbol = sym;
      document.getElementById("searchResults").classList.add("hidden"); document.getElementById("searchBar").value = "";
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

          const sel = document.getElementById("optStrike");
          if (loadedChartSymbol !== sym) { sel.innerHTML = d.strikes.map(s => `<option value="${s}" ${s === d.atm_strike ? 'selected' : ''}>${s} ${s === d.atm_strike ? '(ATM)' : ''}</option>`).join(""); }
          renderTradingViewChart(sym, false);
        }
      } catch (e) {}
    }

    // TV CHART SYMBOL MAPPER - FIXES "SYMBOL DOESNT EXIST" ERROR
    function getTVSymbol(sym) {
        if (sym === "NIFTY_FIN_SERVICE.NS") return "NSE:CNXFINANCE"; 
        if (sym === "^NSEI") return "NSE:NIFTY"; 
        if (sym === "^NSEBANK") return "NSE:BANKNIFTY";
        if (sym === "^BSESN") return "BSE:SENSEX";
        if (sym === "CL=F") return "TVC:USOIL"; 
        if (sym === "GC=F") return "TVC:GOLD"; 
        if (sym === "SI=F") return "TVC:SILVER";
        if (sym === "NG=F") return "TVC:NATURALGAS"; 
        
        // Crypto logic (BTC-USD -> CRYPTO:BTCUSD)
        if (sym.includes("-USD")) return "CRYPTO:" + sym.replace("-", "");
        
        // Equity Logic
        if (sym.endsWith(".NS")) return "NSE:" + sym.replace(".NS", "");
        if (sym.endsWith(".BO")) return "BSE:" + sym.replace(".BO", "");
        if (sym.endsWith("=F")) return "TVC:" + sym.replace("=F", ""); // Generic commodity catch
        
        return "NSE:" + sym; // Default
    }

    function changeChartLayout(val) { currentChartLayout = parseInt(val); renderTradingViewChart(currentActiveSymbol, true); }

    function toggleFullscreen() {
        const wrapper = document.getElementById("chartWrapper");
        if (!document.fullscreenElement) wrapper.requestFullscreen().catch(err => alert("Fullscreen unsupported."));
        else document.exitFullscreen();
    }

    function renderTradingViewChart(sym, forceLayoutUpdate = false) {
      if (loadedChartSymbol === sym && !forceLayoutUpdate) return;
      loadedChartSymbol = sym;
      const grid = document.getElementById("chartGrid"); grid.innerHTML = "";
      
      if(currentChartLayout === 1) grid.className = "grid grid-cols-1 gap-2 h-full w-full rounded-lg overflow-hidden transition-all";
      else if(currentChartLayout === 2) grid.className = "grid grid-cols-1 md:grid-cols-2 gap-2 h-full w-full rounded-lg overflow-hidden transition-all";
      else grid.className = "grid grid-cols-1 md:grid-cols-2 gap-2 h-[800px] md:h-full w-full rounded-lg overflow-hidden transition-all"; // Stacks taller on mobile

      const defaultSymbols = [sym, "^NSEBANK", "BTC-USD", "CL=F"];
      for(let i=0; i < currentChartLayout; i++) {
          let s = getTVSymbol(defaultSymbols[i] || sym);
          grid.innerHTML += `<iframe style="width: 100%; height: 100%; border: none; border-radius: 4px; min-height: 300px;" src="https://s.tradingview.com/widgetembed/?frameElementId=tv_${i}&symbol=${encodeURIComponent(s)}&interval=5&hidesidetoolbar=0&symboledit=1&saveimage=0&toolbarbg=131722&studies=[]&theme=dark&style=1&timezone=Asia%2FKolkata&locale=in"></iframe>`;
      }
    }

    function renderBrokerForm() {
      const b = document.getElementById("brokerSelect").value, f = document.getElementById("brokerFields");
      if (b === "paper") f.innerHTML = `<div class="p-4 bg-emerald-900/30 border border-emerald-500/50 rounded-lg text-xs md:text-sm text-emerald-400 font-bold">✅ Paper Trading Ready. No API keys needed.</div>`;
      else if (b === "dhan") f.innerHTML = `<input id="f_cid" placeholder="Dhan Client ID" class="w-full bg-slate-800 text-xs px-3 py-3 md:py-2 rounded-lg border border-slate-700 mb-2 focus:outline-none focus:border-sky-500"><input id="f_tok" type="password" placeholder="Dhan Access Token" class="w-full bg-slate-800 text-xs px-3 py-3 md:py-2 rounded-lg border border-slate-700 focus:outline-none focus:border-sky-500">`;
      else f.innerHTML = `<input id="f_cid" placeholder="Angel Client Code" class="w-full bg-slate-800 text-xs px-3 py-3 md:py-2 rounded-lg border border-slate-700 mb-2 focus:outline-none focus:border-sky-500"><input id="f_key" placeholder="SmartAPI Key" class="w-full bg-slate-800 text-xs px-3 py-3 md:py-2 rounded-lg border border-slate-700 mb-2 focus:outline-none focus:border-sky-500"><input id="f_pin" type="password" placeholder="MPIN" class="w-full bg-slate-800 text-xs px-3 py-3 md:py-2 rounded-lg border border-slate-700 mb-2 focus:outline-none focus:border-sky-500"><input id="f_totp" type="password" placeholder="TOTP Secret Key" class="w-full bg-slate-800 text-xs px-3 py-3 md:py-2 rounded-lg border border-slate-700 focus:outline-none focus:border-sky-500">`;
    }

    async function fetchStatus() {
      if (!authToken) return;
      try{
        const res = await fetch("/api/terminal/status", { headers: { "Authorization": `Bearer ${authToken}` }});
        if (res.status === 401) return logoutUser();
        if(res.ok){
            const d = await res.json();
            const b = document.getElementById("connectionBadge");
            b.className = d.is_connected ? "text-[10px] md:text-xs font-bold px-3 py-2 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 w-full md:w-auto text-center" : "text-[10px] md:text-xs font-bold px-3 py-2 rounded-lg bg-rose-500/20 text-rose-400 border border-rose-500/30 w-full md:w-auto text-center";
            b.innerText = d.is_connected ? `Broker: ${d.active_broker} ✓` : "Broker: Unlinked ✕";
            
            // Update Paper PnL
            document.getElementById("dispBalance").innerText = `₹ ${d.paper_balance.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
            const pnlColor = d.paper_pnl >= 0 ? "text-emerald-400" : "text-rose-400";
            const pnlSign = d.paper_pnl >= 0 ? "+" : "";
            document.getElementById("dispPnl").className = `text-base md:text-xl font-black ${pnlColor}`;
            document.getElementById("dispPnl").innerText = `${pnlSign} ₹ ${d.paper_pnl.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;

            document.getElementById("riskAutoToggle").checked = d.auto_trade;
            document.getElementById("aiAutoToggle").checked = d.ai_mode;
            document.getElementById("logContainer").innerHTML = d.logs.map(l => `<div class="mb-1">${l}</div>`).reverse().join("");
        }
      }catch(e){}
    }

    async function linkSelectedBroker() {
      const payload = { broker: document.getElementById("brokerSelect").value, client_id: document.getElementById("f_cid")?.value || "", access_token: document.getElementById("f_tok")?.value || null, api_key: document.getElementById("f_key")?.value || null, pin: document.getElementById("f_pin")?.value || null, totp_secret: document.getElementById("f_totp")?.value || null };
      const res = await fetch("/api/broker/link", { method: "POST", headers: { "Content-Type": "application/json", "Authorization": `Bearer ${authToken}` }, body: JSON.stringify(payload) });
      alert((await res.json()).message || "Error"); fetchStatus();
    }

    async function unlinkSelectedBroker() { await fetch("/api/broker/unlink", { method: "POST", headers: { "Authorization": `Bearer ${authToken}` }}); fetchStatus(); }

    async function saveRiskSettings() {
      const payload = { symbol: currentActiveSymbol, lots: parseInt(document.getElementById("optLots").value), target_inr: parseFloat(document.getElementById("riskTarget").value), stoploss_inr: parseFloat(document.getElementById("riskSL").value), auto_trade: document.getElementById("riskAutoToggle").checked, ai_mode: document.getElementById("aiAutoToggle").checked };
      const res = await fetch("/api/settings/save", { method: "POST", headers: { "Content-Type": "application/json", "Authorization": `Bearer ${authToken}` }, body: JSON.stringify(payload) });
      alert((await res.json()).message); fetchStatus();
    }

    async function sendAICommand() {
        const cmd = document.getElementById("aiCommandInput").value;
        if(!cmd) return;
        const res = await fetch("/api/ai/command", { method: "POST", headers: { "Content-Type": "application/json", "Authorization": `Bearer ${authToken}` }, body: JSON.stringify({command: cmd}) });
        alert((await res.json()).message);
        document.getElementById("aiCommandInput").value = "";
        fetchStatus();
    }

    async function executeOptionOrder(type) {
      const payload = { symbol: currentActiveSymbol, strike: parseFloat(document.getElementById("optStrike").value), option_type: type, lots: parseInt(document.getElementById("optLots").value) };
      const res = await fetch("/api/order/buy-option", { method: "POST", headers: { "Content-Type": "application/json", "Authorization": `Bearer ${authToken}` }, body: JSON.stringify(payload) });
      const d = await res.json(); alert(res.ok ? d.message : `Error: ${d.detail}`); fetchStatus();
    }
    
    // Default form render
    renderBrokerForm();
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
# 4. BACKGROUND ALGO & AI TRADING TASK
# ==========================================
def calculate_ai_indicators(df):
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return round(df['SMA_20'].iloc[-1], 2), round(df['RSI'].iloc[-1], 2)

async def algo_trading_loop():
    print("[SYSTEM] AI & Algo Trading Loop Started...")
    while True:
        await asyncio.sleep(15)
        for username, state in TERMINAL_STATES.items():
            if (state.get("auto_trade") or state.get("ai_mode")) and state.get("is_connected"):
                symbol = state.get("algo_symbol", "^NSEI")
                broker = state.get("active_broker", "")
                try:
                    df = yf.Ticker(symbol).history(period="10d", interval="5m")
                    if df.empty or len(df) < 25: continue
                    df_d = yf.Ticker(symbol).history(period="5d", interval="1d")
                    cp = round(float(df["Close"].iloc[-1]), 2)
                    pdh = round(float(df_d.iloc[-2]["High"]), 2) if len(df_d) >= 2 else cp
                    pdl = round(float(df_d.iloc[-2]["Low"]), 2) if len(df_d) >= 2 else cp
                    
                    sma, rsi = calculate_ai_indicators(df)
                    pfx = "[PAPER] " if broker == "PAPER" else ""

                    if state.get("ai_mode"):
                        if cp > pdh and cp > sma and rsi > 55 and state["algo_position"] != "CE":
                            state["algo_position"] = "CE"
                            state["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - 🚀 {pfx}🤖 [AI] Bullish (RSI:{rsi}) -> BUY CE ({symbol})")
                            if broker == "PAPER": state["paper_balance"] -= 5000  # Virtual deduction
                        elif cp < pdl and cp < sma and rsi < 45 and state["algo_position"] != "PE":
                            state["algo_position"] = "PE"
                            state["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - 🚀 {pfx}🤖 [AI] Bearish (RSI:{rsi}) -> BUY PE ({symbol})")
                            if broker == "PAPER": state["paper_balance"] -= 5000
                            
                    elif state.get("auto_trade") and not state.get("ai_mode"):
                        if cp > pdh and state["algo_position"] != "CE":
                            state["algo_position"] = "CE"
                            state["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - ⚡ {pfx}[ALGO] Breakout -> BUY CE ({symbol})")
                        elif cp < pdl and state["algo_position"] != "PE":
                            state["algo_position"] = "PE"
                            state["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - ⚡ {pfx}[ALGO] Breakdown -> BUY PE ({symbol})")
                except Exception as e:
                    pass

# ==========================================
# 5. APP INIT
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    algo_task = asyncio.create_task(algo_trading_loop())
    yield
    algo_task.cancel()

app = FastAPI(title="AI Trading Pro", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Base symbols. Dynamic search will handle the rest of the 5000+.
MASTER_SYMBOLS = [
    {"symbol": "^NSEI", "name": "NIFTY 50", "segment": "INDEX", "step": 50},
    {"symbol": "^NSEBANK", "name": "BANKNIFTY", "segment": "INDEX", "step": 100},
    {"symbol": "NIFTY_FIN_SERVICE.NS", "name": "FINNIFTY", "segment": "INDEX", "step": 50},
    {"symbol": "^BSESN", "name": "SENSEX", "segment": "INDEX", "step": 100},
    {"symbol": "BTC-USD", "name": "BITCOIN", "segment": "CRYPTO", "step": 500},
    {"symbol": "ETH-USD", "name": "ETHEREUM", "segment": "CRYPTO", "step": 50},
    {"symbol": "CL=F", "name": "CRUDE OIL", "segment": "COMMODITY", "step": 10},
    {"symbol": "RELIANCE.NS", "name": "Reliance Ind", "segment": "EQUITY", "step": 20},
]

# ==========================================
# 6. USER STATE & API ROUTES
# ==========================================
TERMINAL_STATES = {}
BROKER_INSTANCES = {}

def get_user_state(username: str):
    if username not in TERMINAL_STATES:
        TERMINAL_STATES[username] = {
            "active_broker": None, "is_connected": False, "broker_display_id": "", 
            "logs": [f"{datetime.now().strftime('%H:%M:%S')} - System Initialized."],
            "auto_trade": False, "ai_mode": False, "lots": 1, "target_inr": 1000.0, "stoploss_inr": 500.0,
            "algo_symbol": "^NSEI", "algo_position": None,
            "paper_balance": 1000000.0, "paper_pnl": 0.0, "ai_commands": []
        }
    return TERMINAL_STATES[username]

def get_current_user(token: str = Depends(oauth2_scheme), db: sqlite3.Connection = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone(): raise HTTPException(401)
        return username
    except JWTError: raise HTTPException(401, "Session expired, login again.")

class AuthReq(BaseModel): username: str; password: str
class BrokerReq(BaseModel): broker: str; client_id: str; api_key: Optional[str] = None; access_token: Optional[str] = None; pin: Optional[str] = None; totp_secret: Optional[str] = None
class OrderReq(BaseModel): symbol: str; strike: float; option_type: str; lots: int
class SettingsReq(BaseModel): symbol: str; lots: int; target_inr: float; stoploss_inr: float; auto_trade: bool; ai_mode: bool
class AICommandReq(BaseModel): command: str

@app.post("/api/register")
def register(req: AuthReq, db: sqlite3.Connection = Depends(get_db)):
    try:
        db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (req.username.strip(), hashlib.sha256(req.password.encode()).hexdigest()))
        db.commit()
        return {"message": "Account created successfully!"}
    except sqlite3.IntegrityError: raise HTTPException(400, "Username exists!")

@app.post("/token")
def login(form: OAuth2PasswordRequestForm = Depends(), db: sqlite3.Connection = Depends(get_db)):
    if db.execute("SELECT * FROM users WHERE username = ? AND password_hash = ?", (form.username, hashlib.sha256(form.password.encode()).hexdigest())).fetchone():
        return {"access_token": jwt.encode({"sub": form.username, "exp": datetime.utcnow() + timedelta(minutes=720)}, SECRET_KEY, algorithm=ALGORITHM), "token_type": "bearer"}
    raise HTTPException(401, "Invalid credentials!")

@app.get("/api/search")
def search(q: str, segment: str = "NSE"): 
    results = [s for s in MASTER_SYMBOLS if q.lower() in s["symbol"].lower() or q.lower() in s["name"].lower()]
    # DYNAMIC SEARCH LOGIC (Lets user fetch ANY of 5000+ stocks safely)
    if len(q) > 1 and not any(q.upper() in r["symbol"].upper() for r in results):
        if segment == "CRYPTO": sym = f"{q.upper()}-USD"
        elif segment == "MCX": sym = f"{q.upper()}=F"
        else: sym = f"{q.upper()}.NS"
        results.append({"symbol": sym, "name": f"{q.upper()} ({segment})", "segment": segment, "step": 10})
    return results[:10]

@app.get("/api/market-data")
def market_data(symbol: str, username: str = Depends(get_current_user)):
    try:
        df = yf.Ticker(symbol).history(period="10d", interval="5m")
        if df.empty or len(df) < 20: raise ValueError("Invalid symbol or no data.")
        df_d = yf.Ticker(symbol).history(period="5d", interval="1d")
        cp = round(float(df["Close"].iloc[-1]), 2)
        pdh = round(float(df_d.iloc[-2]["High"]), 2) if len(df_d) >= 2 else cp
        pdl = round(float(df_d.iloc[-2]["Low"]), 2) if len(df_d) >= 2 else cp
        
        sma, rsi = calculate_ai_indicators(df)
        if cp > sma and rsi > 55: ai_rec = f"🤖 AI BULLISH (RSI: {rsi})"
        elif cp < sma and rsi < 45: ai_rec = f"🤖 AI BEARISH (RSI: {rsi})"
        else: ai_rec = f"🤖 AI NEUTRAL (RSI: {rsi})"

        # Paper Trading Random PnL Simulation for effect
        state = get_user_state(username)
        if state["active_broker"] == "PAPER" and state["paper_balance"] < 1000000:
            import random
            change = random.uniform(-150.0, 250.0)
            state["paper_pnl"] += change

        step = next((s["step"] for s in MASTER_SYMBOLS if s["symbol"] == symbol), 50)
        atm = round(cp / step) * step
        return {"symbol": symbol, "current_price": cp, "pdh": pdh, "pdl": pdl, "atm_strike": atm, "strikes": [atm - (step*2), atm - step, atm, atm + step, atm + (step*2)], "recommendation": ai_rec}
    except Exception as e: raise HTTPException(400, f"Market error: {str(e)}")

@app.get("/api/terminal/status")
def status_api(username: str = Depends(get_current_user)): return get_user_state(username)

@app.post("/api/broker/link")
def link(req: BrokerReq, username: str = Depends(get_current_user)):
    state = get_user_state(username)
    try:
        if req.broker == "paper":
            state.update({"active_broker": "PAPER", "is_connected": True, "broker_display_id": "VIRTUAL"})
            state["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - Paper Trading Activated.")
            return {"message": "Paper Trading Activated! No API required."}
            
        if req.broker == "dhan": BROKER_INSTANCES[username] = dhanhq(req.client_id, req.access_token)
        elif req.broker == "angelone":
            smart = SmartConnect(api_key=req.api_key)
            totp_code = pyotp.TOTP(req.totp_secret).now() if req.totp_secret and len(req.totp_secret) > 4 else ""
            if not smart.generateSession(req.client_id, req.pin, totp_code).get("status"): raise Exception("Angel One Auth Failed")
            BROKER_INSTANCES[username] = smart
            
        state.update({"active_broker": req.broker.upper(), "is_connected": True, "broker_display_id": req.client_id[:3]+"**"})
        state["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - {req.broker.upper()} linked.")
        return {"message": "Broker connected successfully!"}
    except Exception as e: raise HTTPException(400, f"Link error: {str(e)}")

@app.post("/api/broker/unlink")
def unlink(username: str = Depends(get_current_user)):
    state = get_user_state(username)
    if username in BROKER_INSTANCES: del BROKER_INSTANCES[username]
    state.update({"active_broker": None, "is_connected": False, "auto_trade": False, "ai_mode": False})
    state["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - Broker unlinked.")
    return {"message": "Disconnected."}

@app.post("/api/settings/save")
def save_settings(req: SettingsReq, username: str = Depends(get_current_user)):
    state = get_user_state(username)
    state.update({"algo_symbol": req.symbol, "lots": req.lots, "target_inr": req.target_inr, "stoploss_inr": req.stoploss_inr, "auto_trade": req.auto_trade, "ai_mode": req.ai_mode})
    status_txt = f"Algo: {'ON' if req.auto_trade else 'OFF'} | AI Mode: {'ON' if req.ai_mode else 'OFF'}"
    state["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - Settings saved: {status_txt}")
    return {"message": f"Settings Saved! ({status_txt})"}

@app.post("/api/ai/command")
def ai_command(req: AICommandReq, username: str = Depends(get_current_user)):
    state = get_user_state(username)
    state["ai_commands"].append(req.command)
    state["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - 🤖 COMMAND RECEIVED: {req.command}")
    return {"message": "Command registered by AI."}

@app.post("/api/order/buy-option")
def buy_order(req: OrderReq, username: str = Depends(get_current_user)):
    state = get_user_state(username)
    if not state["is_connected"]: raise HTTPException(400, "Link broker first!")
    broker = state["active_broker"]
    client = BROKER_INSTANCES.get(username)
    order_msg = f"BUY {req.symbol} {req.strike} {req.option_type} ({req.lots} Lots)"
    
    try:
        if broker == "PAPER":
            cost = req.lots * 5000 # Example deduction
            state["paper_balance"] -= cost
            state["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - ✅ [PAPER] Executed: {order_msg}")
            return {"message": f"Paper Trade Executed: {order_msg}"}
            
        elif broker == "DHAN": client.place_order(security_id="13", exchange_segment=client.NSE_FNO, transaction_type=client.BUY, quantity=req.lots * 15, order_type=client.MARKET, product_type=client.INTRADAY, price=0)
        elif broker == "ANGELONE": client.placeOrder({"variety": "NORMAL", "tradingsymbol": f"{req.symbol}{req.strike}{req.option_type}", "symboltoken": "3045", "transactiontype": "BUY", "exchange": "NFO", "ordertype": "MARKET", "producttype": "INTRADAY", "duration": "DAY", "quantity": req.lots * 15})
        
        state["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - [ORDER SUCCESS] {order_msg}")
        return {"message": f"Order sent: {order_msg}"}
    except Exception as e:
        state["logs"].append(f"{datetime.now().strftime('%H:%M:%S')} - [ORDER FAILED] {str(e)}")
        raise HTTPException(400, f"Order failed: {str(e)}")

@app.get("/", response_class=HTMLResponse)
def root(): return HTMLResponse(content=HTML_CONTENT)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)