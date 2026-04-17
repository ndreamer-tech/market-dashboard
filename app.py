"""
Market Dashboard - Flask Backend (수정판)
yfinance 제거, Yahoo Finance API 직접 호출
"""

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import requests
from datetime import datetime
import time, os

app = Flask(__name__, static_folder="static")
CORS(app)

_cache = {"data": None, "ts": 0}
CACHE_SEC = 600

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

def fetch_yahoo(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {"interval": "1d", "range": "5d"}
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = r.json()
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]
        if len(closes) < 2:
            return None, None
        chg = (closes[-1] - closes[0]) / closes[0] * 100
        return round(closes[-1], 2), round(chg, 2)
    except Exception as e:
        print(f"  [오류] {symbol}: {e}")
        return None, None

def fetch_yahoo2(symbol):
    try:
        url = "https://query2.finance.yahoo.com/v8/finance/chart/" + symbol
        params = {"interval": "1d", "range": "5d"}
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = r.json()
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]
        if len(closes) < 2:
            return None, None
        chg = (closes[-1] - closes[0]) / closes[0] * 100
        return round(closes[-1], 2), round(chg, 2)
    except:
        return None, None

def safe_fetch(symbol):
    val, chg = fetch_yahoo(symbol)
    if val is None:
        val, chg = fetch_yahoo2(symbol)
    return val, chg

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def scale(v, bad, good):
    if v is None:
        return 5
    if bad == good:
        return 5
    return round(clamp((v - bad) / (good - bad) * 10, 0, 10), 1)

def collect():
    raw = {}
    print("📡 데이터 수집 시작...")

    raw["TNX"], raw["TNX_chg"]       = safe_fetch("^TNX")
    raw["DXY"], raw["DXY_chg"]       = safe_fetch("DX-Y.NYB")
    raw["HYG"], raw["HYG_chg"]       = safe_fetch("HYG")
    raw["TLT"], raw["TLT_chg"]       = safe_fetch("TLT")
    raw["OIL"], raw["OIL_chg"]       = safe_fetch("CL=F")
    raw["BDRY"], raw["BDRY_chg"]     = safe_fetch("BDRY")
    raw["SOXX"], raw["SOXX_chg"]     = safe_fetch("SOXX")
    raw["VIX"], raw["VIX_chg"]       = safe_fetch("^VIX")
    raw["SPX"], raw["SPX_chg"]       = safe_fetch("^GSPC")
    raw["NDX"], raw["NDX_chg"]       = safe_fetch("^IXIC")
    raw["KOSPI"], raw["KOSPI_chg"]   = safe_fetch("^KS11")
    raw["USDKRW"], raw["USDKRW_chg"] = safe_fetch("USDKRW=X")
    raw["EWY"], raw["EWY_chg"]       = safe_fetch("EWY")
    raw["ARKK"], raw["ARKK_chg"]     = safe_fetch("ARKK")
    raw["GOLD"], raw["GOLD_chg"]     = safe_fetch("GC=F")

    print(f"  VIX={raw['VIX']}, OIL={raw['OIL']}, TNX={raw['TNX']}, NDX_chg={raw['NDX_chg']}")

    sc = {}
    sc["rate"]       = int(round(scale(raw["TNX_chg"],    1.5,  -1.5)))
    sc["dollar"]     = int(round(scale(raw["DXY_chg"],    2.0,  -2.0)))
    sc["credit"]     = int(round(scale(raw["HYG_chg"],   -3.0,   2.0)))
    sc["fomc"]       = int(round(scale(raw["TLT_chg"],   -4.0,   3.0)))
    sc["oil"]        = int(round(scale(raw["OIL_chg"],   10.0,  -5.0)))
    sc["freight"]    = int(round(scale(raw["BDRY_chg"],  15.0,  -5.0)))
    sc["semi"]       = int(round(scale(raw["SOXX_chg"], -10.0,   5.0)))
    oil_val          = raw["OIL"] or 75
    sc["chokepoint"] = int(round(scale(oil_val,          110.0,  65.0)))
    tnx_val          = raw["TNX"] or 4.5
    sc["cb"]         = int(round(scale(tnx_val,            5.5,   3.0)))
    sc["fiscal"]     = int(round(scale(raw["GOLD_chg"],    5.0,  -2.0)))
    dxy_c            = raw["DXY_chg"] or 0
    oil_c            = raw["OIL_chg"] or 0
    sc["tariff"]     = int(round(scale((dxy_c + oil_c)/2,  5.0,  -3.0)))
    ndx_c            = raw["NDX_chg"] or 0
    spx_c            = raw["SPX_chg"] or 0
    sc["reg"]        = int(round(scale(ndx_c - spx_c,     -3.0,   3.0)))
    vix              = raw["VIX"] or 20
    sc["vix"]        = int(round(scale(vix,               35.0,  15.0)))
    ewy_c            = raw["EWY_chg"] or 0
    usd_c            = raw["USDKRW_chg"] or 0
    sc["foreign"]    = int(round(scale(ewy_c - usd_c*0.5, -5.0,   5.0)))
    sc["retail"]     = int(round(scale(raw["ARKK_chg"],    8.0,  -3.0)))
    sc["narrative"]  = int(round(scale(ndx_c,              8.0,  -2.0)))

    situation = "normal"
    if vix > 28 and oil_c > 5:
        situation = "war"
    elif (raw["TNX_chg"] or 0) > 0.8 or tnx_val > 5.0:
        situation = "policy"
    elif vix > 35:
        situation = "pandemic"
    elif ndx_c > 3 and vix < 20:
        situation = "tech"

    collected = sum(1 for k in ["VIX","OIL","TNX","NDX"] if raw.get(k) is not None)
    print(f"  수집 {collected}/4, 상황={situation}, 점수샘플={sc}")

    return {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "situation": situation,
        "collected": collected,
        "scores": sc,
        "raw": {
            "vix":        raw["VIX"] or 0,
            "spx_chg":    raw["SPX_chg"] or 0,
            "ndx_chg":    raw["NDX_chg"] or 0,
            "kospi_chg":  raw["KOSPI_chg"] or 0,
            "usdkrw":     raw["USDKRW"] or 0,
            "usdkrw_chg": raw["USDKRW_chg"] or 0,
            "oil":        raw["OIL"] or 0,
            "oil_chg":    raw["OIL_chg"] or 0,
            "tnx":        raw["TNX"] or 0,
            "tnx_chg":    raw["TNX_chg"] or 0,
            "dxy":        raw["DXY"] or 0,
            "dxy_chg":    raw["DXY_chg"] or 0,
            "soxx_chg":   raw["SOXX_chg"] or 0,
            "ewy_chg":    raw["EWY_chg"] or 0,
        }
    }

@app.route("/api/data")
def api_data():
    global _cache
    now = time.time()
    if _cache["data"] and now - _cache["ts"] < CACHE_SEC:
        return jsonify(_cache["data"])
    try:
        data = collect()
        _cache = {"data": data, "ts": now}
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/test")
def api_test():
    results = {}
    for sym in ["^VIX", "^GSPC", "CL=F", "^TNX", "DX-Y.NYB", "^KS11", "USDKRW=X"]:
        val, chg = safe_fetch(sym)
        results[sym] = {"val": val, "chg": chg}
    return jsonify(results)

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
