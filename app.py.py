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
          <input id="usernameInput" type="text" value="admin" required class="w-full bg-slate-800 border border-slate-700 px-4 py-2.5 rounded-lg text-sm focus:outline-none focus:border-sky-500">
        </div>
        <div>
          <label class="block text-[11px] uppercase text-slate-400 mb-1">पासवर्ड</label>
          <input id="passwordInput" type="password" placeholder="••••••••" required class="w-full bg-slate-800 border border-slate-700 px-4 py-2.5 rounded-lg text-sm focus:outline-none focus:border-sky-500">
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
          <input id="searchBar" type="text" placeholder="सर्च: NIFTY, Sensex, Crude, SBIN..." oninput="handleSearch(this.value)" class="bg-transparent text-xs w-full focus:outline-none">
        </div>
        <div id="searchResults" class="absolute left-0 right-0 top-12 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl z-50 hidden max-h-60 overflow-y-auto"></div>
      </div>
      <div class="flex items-center gap-3">
        <div id="connectionBadge" class="text-xs font-semibold px-3 py-1.5 rounded-lg bg-rose-500/20 text-rose-400 border border-rose-500/30">ब्रोकर: अन-लिंक ✕</div>
        <button onclick="logoutUser()" class="text-xs bg-slate-800 border border-slate-700 px-3 py-1.5 rounded-lg hover:bg-slate-700 text-slate-300">लॉगआउट 🔒</button>
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
              <label class="text-[10px] text-slate-400">लॉट साइज / क्वांटिटी</label>
              <input id="optLots" type="number" value="1" min="1" class="w-full bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-700 mt-1">
            </div>
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3 pt-4">
          <button onclick="executeOptionOrder('CE')" class="bg-emerald-600 hover:bg-emerald-500 text-xs font-black py-3 rounded-xl transition shadow-lg shadow-emerald-600/30">BUY CALL (CE)</button>
          <button onclick="executeOptionOrder('PE')" class="bg-rose-600 hover:bg-rose-500 text-xs font-black py-3 rounded-xl transition shadow-lg shadow-rose-600/30">BUY PUT (PE)</button>
        </div>
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
      <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl shadow-xl">
        <h2 class="text-sm font-bold text-sky-400 mb-3">मल्टी-ब्रोकर गेटवे</h2>
        <select id="brokerSelect" onchange="renderBrokerForm()" class="w-full bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-700 mb-3 font-semibold">
          <option value="dhan">Dhan (धन)</option>
          <option value="angelone">Angel One (SmartAPI)</option>
        </select>
        <div id="brokerFields" class="space-y-2 mb-3"></div>
        <div class="flex gap-2">
          <button onclick="linkSelectedBroker()" class="w-1/2 bg-emerald-600 py-2 rounded-lg text-xs font-bold hover:bg-emerald-500">लिंक करें</button>
          <button onclick="unlinkSelectedBroker()" class="w-1/2 bg-rose-600 py-2 rounded-lg text-xs font-bold hover:bg-rose-500">अन-लिंक</button>
        </div>
      </div>

      <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl shadow-xl">
        <h2 class="text-xs font-bold text-slate-400 mb-2 uppercase">सिस्टम ऑडिट ट्रेल (Logs)</h2>
        <div id="logContainer" class="bg-black/60 p-4 rounded-xl font-mono text-xs text-emerald-400 h-40 overflow-y-auto space-y-1"></div>
      </div>
    </div>
  </div>

  <script>
    let authToken = localStorage.getItem("token");
    let currentActiveSymbol = "^NSEI"; 
    let loadedChartSymbol = ""; 
    let isSignUpMode = false;

    setInterval(() => {
      document.getElementById("clock").innerText = new Date().toLocaleString("hi-IN", { timeZone: "Asia/Kolkata" });
    }, 1000);

    if (authToken) initTerminal();

    function toggleAuthMode() {
      isSignUpMode = !isSignUpMode;
      document.getElementById("authTitle").innerText = isSignUpMode ? "नया यूज़र रजिस्ट्रेशन" : "ऑप्शन बाइंग टर्मिनल";
      document.getElementById("loginSubmitBtn").innerText = isSignUpMode ? "खाता बनाएं (Register)" : "सुरक्षित लॉगिन";
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
      setInterval(() => loadMarketData(currentActiveSymbol), 10000); // 10s auto-refresh prices
    }

    async function handleSearch(query) {
      const box = document.getElementById("searchResults");
      if (!query.trim()) return box.classList.add("hidden");
      const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`, { headers: { "Authorization": `Bearer ${authToken}` }});
      if (res.ok) {
        const list = await res.json();
        if(list.length === 0) {
            box.innerHTML = `<div class="p-3 text-xs text-slate-500">कोई स्टॉक/कमोडिटी नहीं मिली।</div>`;
        } else {
            box.innerHTML = list.map(i => `<div onclick="selectSymbol('${i.symbol}')" class="p-2.5 hover:bg-slate-800 cursor-pointer border-b border-slate-800/50 flex justify-between items-center"><span class="text-xs font-bold text-white">${i.name} <span class="text-[10px] text-slate-400 font-mono ml-1">(${i.symbol})</span></span><span class="text-[9px] px-2 py-0.5 rounded bg-slate-800 text-sky-400 font-bold border border-slate-700">${i.segment}</span></div>`).join("");
        }
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
             sel.innerHTML = d.strikes.map(s => `<option value="${s}" ${s === d.atm_strike ? 'selected' : ''}>${s}${s === d.atm_strike ? '(ATM)' : ''}</option>`).join("");
          }
          
          renderTradingViewChart(sym);
        }
      } catch (e) {}
    }

    function renderTradingViewChart(sym) {
      // ✅ CHART AUTO REFRESH FIX
      if (loadedChartSymbol === sym) return;
      loadedChartSymbol = sym;

      let tvSymbol = "BSE:" + sym.replace(".NS", "").replace(".BO", "");
      if (sym === "CL=F") tvSymbol = "TVC:USOIL";
      else if (sym === "GC=F") tvSymbol = "TVC:GOLD";
      else if (sym === "SI=F") tvSymbol = "TVC:SILVER";
      else if (sym === "NG=F") tvSymbol = "TVC:NATURALGAS";
      else if (sym === "HG=F") tvSymbol = "TVC:COPPER";
      else if (sym === "^NSEI") tvSymbol = "NSE:NIFTY";
      else if (sym === "^NSEBANK") tvSymbol = "NSE:BANKNIFTY";
      else if (sym === "NIFTY_FIN_SERVICE.NS") tvSymbol = "NSE:FINNIFTY";
      else if (sym === "^BSESN") tvSymbol = "BSE:SENSEX";
      else if (sym === "^BSEBANK") tvSymbol = "BSE:BANKEX";
      else if (sym === "^INDIAVIX") tvSymbol = "NSE:INDIAVIX";
      else if (sym.includes(".NS")) tvSymbol = "NSE:" + sym.replace(".NS", "");

      document.getElementById("tvChart").innerHTML = `
        <iframe style="width: 100%; height: 100%; min-height: 480px; border: none; border-radius: 8px;" 
        src="https://s.tradingview.com/widgetembed/?frameElementId=tradingview_widget&symbol=${encodeURIComponent(tvSymbol)}&interval=5&hidesidetoolbar=0&symboledit=1&saveimage=1&toolbarbg=131722&studies=[]&theme=dark&style=1&timezone=Asia%2FKolkata&locale=in