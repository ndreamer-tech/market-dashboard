"""
Market Dashboard - Flask Backend
실행: python app.py
접속: http://localhost:5000
"""

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import yfinance as yf
import requests
from datetime import datetime
import json, os, time

app = Flask(__name__, static_folder="static")
CORS(app)

# ── 캐시 (같은 날 여러 번 요청해도 API 1회만 호출) ──────────
_cache = {"data": None, "ts": 0}
CACHE_SEC = 600  # 10분 캐시


def safe_get(ticker, period="5d", key="Close"):
    try:
        hist = yf.Ticker(ticker).history(period=period)
        if hist.empty:
            return None
        return float(hist[key].dropna().iloc[-1])
    except:
        return None


def get_chg(ticker, period="5d"):
    try:
        hist = yf.Ticker(ticker).history(period=period)["Close"].dropna()
        if len(hist) < 2:
            return None
        return round((hist.iloc[-1] - hist.iloc[0]) / hist.iloc[0] * 100, 2)
    except:
        return None


def get_fred(series_id):
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        r = requests.get(url, timeout=8)
        for line in reversed(r.text.strip().split("\n")[1:]):
            parts = line.split(",")
            if len(parts) == 2 and parts[1].strip() not in (".", ""):
                return float(parts[1].strip())
    except:
        return None


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

    # 유동성
    raw["TNX"] = safe_get("^TNX")
    raw["TNX_chg"] = get_chg("^TNX")
    raw["DXY"] = safe_get("DX-Y.NYB")
    raw["DXY_chg"] = get_chg("DX-Y.NYB")
    raw["HYG_chg"] = get_chg("HYG")
    raw["TLT_chg"] = get_chg("TLT")

    # 공급망
    raw["OIL"] = safe_get("CL=F")
    raw["OIL_chg"] = get_chg("CL=F")
    raw["BDRY_chg"] = get_chg("BDRY")
    raw["SOXX_chg"] = get_chg("SOXX")

    # 심리
    raw["VIX"] = safe_get("^VIX")
    raw["SPX_chg"] = get_chg("^GSPC")
    raw["NDX_chg"] = get_chg("^IXIC")
    raw["KOSPI_chg"] = get_chg("^KS11")
    raw["USDKRW"] = safe_get("USDKRW=X")
    raw["USDKRW_chg"] = get_chg("USDKRW=X")
    raw["EWY_chg"] = get_chg("EWY")
    raw["ARKK_chg"] = get_chg("ARKK")

    # 점수 변환
    sc = {}
    sc["rate"]       = int(round(scale(raw["TNX_chg"],  1.5, -1.5)))
    sc["dollar"]     = int(round(scale(raw["DXY_chg"],  2.0, -2.0)))
    sc["credit"]     = int(round(scale(raw["HYG_chg"],  -3.0, 2.0)))
    sc["fomc"]       = int(round(scale(raw["TLT_chg"],  -4.0, 3.0)))
    sc["oil"]        = int(round(scale(raw["OIL_chg"],  10.0, -5.0)))
    sc["freight"]    = int(round(scale(raw["BDRY_chg"], 15.0, -5.0)))
    sc["semi"]       = int(round(scale(raw["SOXX_chg"], -10.0, 5.0)))
    oil_val = raw["OIL"] or 75
    sc["chokepoint"] = int(round(scale(oil_val,         110.0, 65.0)))
    tnx_val = raw["TNX"] or 4.5
    sc["cb"]         = int(round(scale(tnx_val,         5.5, 3.0)))
    gold_chg = get_chg("GC=F") or 0
    sc["fiscal"]     = int(round(scale(gold_chg,        5.0, -2.0)))
    dxy_chg = raw["DXY_chg"] or 0
    oil_chg = raw["OIL_chg"] or 0
    sc["tariff"]     = int(round(scale((dxy_chg + oil_chg) / 2, 5.0, -3.0)))
    ndx_chg = raw["NDX_chg"] or 0
    spx_chg = raw["SPX_chg"] or 0
    sc["reg"]        = int(round(scale(ndx_chg - spx_chg, -3.0, 3.0)))
    vix = raw["VIX"] or 20
    sc["vix"]        = int(round(scale(vix,              35.0, 15.0)))
    ewy_chg = raw["EWY_chg"] or 0
    usdkrw_chg = raw["USDKRW_chg"] or 0
    sc["foreign"]    = int(round(scale(ewy_chg - usdkrw_chg * 0.5, -5.0, 5.0)))
    arkk_chg = raw["ARKK_chg"] or 0
    sc["retail"]     = int(round(scale(arkk_chg,         8.0, -3.0)))
    sc["narrative"]  = int(round(scale(ndx_chg,          8.0, -2.0)))

    # 상황 자동 감지
    situation = "normal"
    if (vix or 20) > 28 and (oil_chg or 0) > 5:
        situation = "war"
    elif (raw["TNX_chg"] or 0) > 0.8 or (tnx_val or 4.5) > 5.0:
        situation = "policy"
    elif (vix or 20) > 35:
        situation = "pandemic"
    elif ndx_chg > 3 and (vix or 20) < 20:
        situation = "tech"

    return {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "situation": situation,
        "scores": sc,
        "raw": {
            "vix":        round(raw["VIX"] or 0, 2),
            "spx_chg":    round(raw["SPX_chg"] or 0, 2),
            "ndx_chg":    round(raw["NDX_chg"] or 0, 2),
            "kospi_chg":  round(raw["KOSPI_chg"] or 0, 2),
            "usdkrw":     round(raw["USDKRW"] or 0, 2),
            "usdkrw_chg": round(raw["USDKRW_chg"] or 0, 2),
            "oil":        round(raw["OIL"] or 0, 2),
            "oil_chg":    round(raw["OIL_chg"] or 0, 2),
            "tnx":        round(raw["TNX"] or 0, 2),
            "tnx_chg":    round(raw["TNX_chg"] or 0, 2),
            "dxy":        round(raw["DXY"] or 0, 2),
            "dxy_chg":    round(raw["DXY_chg"] or 0, 2),
            "soxx_chg":   round(raw["SOXX_chg"] or 0, 2),
            "ewy_chg":    round(raw["EWY_chg"] or 0, 2),
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


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
