import os
import sqlite3
import hashlib
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
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
  <title>Options Pro Terminal - AI Enabled</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
  <style>
    #chartWrapper:fullscreen { background-color: #020617; padding: 10px; overflow: hidden; }
    #chartWrapper:fullscreen #chartGrid { height: calc(100vh - 20px) !important; }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans antialiased">

  <div id="loginOverlay" class="flex items-center justify-center min-h-screen px-4">
    <div class="bg-slate-900 border border-slate-800 p-8 rounded-2xl w-full max-w-md shadow-2xl">
      <div class="flex items-center justify-center mb-6">
        <span class="text-4xl mr-3">🧠</span>
        <h1 class="text-2xl font-black text-transparent bg-clip-text bg-gradient-to-r from-sky-400 to-indigo-400">AI ट्रेडिंग टर्मिनल</h1>
      </div>
      
      <div class="flex mb-6 border-b border-slate-800">
        <button id="tabLogin" onclick="switchAuthTab('login')" class="flex-1 py-2 text-sm font-bold text-sky-400 border-b-2 border-sky-400 transition">लॉगिन (Login)</button>
        <button id="tabSignup" onclick="switchAuthTab('signup')" class="flex-1 py-2 text-sm font-bold text-slate-500 border-b-2 border-transparent transition hover:text-slate-300">नया अकाउंट (Sign Up)</button>
      </div>

      <form id="authForm" class="space-y-4">
        <div>
          <label class="block text-[11px] uppercase text-slate-400 mb-1">यूज़रनेम</label>
          <input id="usernameInput" type="text" value="admin" required class="w-full bg-slate-800 border border-slate-700 px-4 py-2.5 rounded-lg text-sm focus:outline-none focus:border-sky-500">
        </div>
        <div>
          <label class="block text-[11px] uppercase text-slate-400 mb-1">पासवर्ड</label>
          <input id="passwordInput" type="password" placeholder="••••••••" required class="w-full bg-slate-800 border border-slate-700 px-4 py-2.5 rounded-lg text-sm focus:outline-none focus:border-sky-500">
        </div>
        <button id="authSubmitBtn" type="submit" class="w-full bg-sky-600 hover:bg-sky-500 font-bold py-2.5 rounded-lg transition">सिस्टम में प्रवेश करें</button>
      </form>
    </div>
  </div>

  <div id="mainTerminal" class="hidden max-w-7xl mx-auto p-4 space-y-6">
    <header class="flex flex-wrap justify-between items-center border-b border-slate-800 pb-4 gap-4">
      <div>
        <h1 class="text-2xl font-black text-transparent bg-clip-text bg-gradient-to-r from-sky-400 to-indigo-400">AI BUYER PRO</h1>
        <p class="text-xs text-slate-400 font-mono" id="clock"></p>
      </div>
      <div class="relative w-full md:w-80">
        <div class="flex items-center bg-slate-900 border border-slate-700 rounded-xl px-3 py-2">
          <span class="text-slate-400 mr-2">🔍</span>
          <input id="searchBar" type="text" placeholder="सर्च: NIFTY, Sensex, Crude..." oninput="handleSearch(this.value)" class="bg-transparent text-xs w-full focus:outline-none">
        </div>
        <div id="searchResults" class="absolute left-0 right-0 top-12 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl z-50 hidden max-h-60 overflow-y-auto"></div>
      </div>
      <div class="flex items-center gap-3">
        <div id="connectionBadge" class="text-xs font-semibold px-3 py-1.5 rounded-lg bg-rose-500/20 text-rose-400 border border-rose-500/30">ब्रोकर: अन-लिंक ✕</div>
        <button onclick="logoutUser()" class="text-xs bg-slate-800 border border-slate-700 px-3 py-1.5 rounded-lg hover:bg-slate-700 text-slate-300">लॉगआउट 🔒</button>
      </div>
    </header>

    <div class="grid grid-cols-2 md:grid-cols-5 gap-3">
      <div class="bg-slate-900 border border-slate-800 p-3 rounded-xl"><div class="text-[10px] text-slate-400">वर्तमान स्टॉक</div><div id="dispSymbol" class="text-sm font-bold text-indigo-400">--</div></div>
      <div class="bg-slate-900 border border-slate-800 p-3 rounded-xl"><div class="text-[10px] text-slate-400">लाइव कीमत</div>