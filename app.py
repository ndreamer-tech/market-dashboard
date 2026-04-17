"""
Market Dashboard - Flask Backend (v3 - 개선된 지표 로직)
개선: 유가방향 / 지정학리스크 / 관세제재 계산 로직 현실화
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

    raw["TNX"],     raw["TNX_chg"]     = safe_fetch("^TNX")
    raw["DXY"],     raw["DXY_chg"]     = safe_fetch("DX-Y.NYB")
    raw["HYG"],     raw["HYG_chg"]     = safe_fetch("HYG")
    raw["TLT"],     raw["TLT_chg"]     = safe_fetch("TLT")
    raw["OIL"],     raw["OIL_chg"]     = safe_fetch("CL=F")
    raw["BDRY"],    raw["BDRY_chg"]    = safe_fetch("BDRY")
    raw["SOXX"],    raw["SOXX_chg"]    = safe_fetch("SOXX")
    raw["VIX"],     raw["VIX_chg"]     = safe_fetch("^VIX")
    raw["SPX"],     raw["SPX_chg"]     = safe_fetch("^GSPC")
    raw["NDX"],     raw["NDX_chg"]     = safe_fetch("^IXIC")
    raw["KOSPI"],   raw["KOSPI_chg"]   = safe_fetch("^KS11")
    raw["USDKRW"],  raw["USDKRW_chg"]  = safe_fetch("USDKRW=X")
    raw["EWY"],     raw["EWY_chg"]     = safe_fetch("EWY")
    raw["ARKK"],    raw["ARKK_chg"]    = safe_fetch("ARKK")
    raw["GOLD"],    raw["GOLD_chg"]    = safe_fetch("GC=F")

    print(f"  VIX={raw['VIX']}, OIL={raw['OIL']}, TNX={raw['TNX']}, NDX_chg={raw['NDX_chg']}")

    sc = {}

    # ── 유동성 축 ──────────────────────────────────────────
    sc["rate"]   = int(round(scale(raw["TNX_chg"],  1.5,  -1.5)))
    sc["dollar"] = int(round(scale(raw["DXY_chg"],  2.0,  -2.0)))
    sc["credit"] = int(round(scale(raw["HYG_chg"], -3.0,   2.0)))
    sc["fomc"]   = int(round(scale(raw["TLT_chg"], -4.0,   3.0)))

    # ── 공급망 축 ──────────────────────────────────────────

    # ✅ 개선 1: 유가 방향 = 변화율(40%) + 절대값(60%)
    #   이유: 5일 급락해도 WTI $90대면 여전히 인플레 압박
    #   기준: $65=안전, $105=위험 / 변화율: -5%=좋음, +10%=나쁨
    oil_chg_sc = scale(raw["OIL_chg"], 10.0, -5.0)
    oil_lvl_sc = scale(raw["OIL"] or 75, 105.0, 65.0)
    sc["oil"] = int(round(oil_chg_sc * 0.4 + oil_lvl_sc * 0.6))

    sc["freight"] = int(round(scale(raw["BDRY_chg"], 15.0, -5.0)))
    sc["semi"]    = int(round(scale(raw["SOXX_chg"], -10.0, 5.0)))

    # ✅ 개선 2: 지정학 리스크 = 유가절대값(50%) + VIX(30%) + 유가변동성(20%)
    #   이유: 단순 유가 절대값만으론 전쟁 변동성·공포 심리 반영 안됨
    #   유가 변동성(방향 무관): 크게 움직이면 불확실성 높음
    oil_val    = raw["OIL"] or 75
    vix_val    = raw["VIX"] or 20
    oil_vol    = abs(raw["OIL_chg"] or 0)
    oil_abs_sc = scale(oil_val,  110.0, 65.0)
    vix_geo_sc = scale(vix_val,  35.0,  15.0)
    oil_vol_sc = scale(oil_vol,  15.0,  2.0)
    sc["chokepoint"] = int(round(
        oil_abs_sc * 0.5 + vix_geo_sc * 0.3 + oil_vol_sc * 0.2
    ))

    # ── 정책 축 ──────────────────────────────────────────
    tnx_val = raw["TNX"] or 4.5
    sc["cb"] = int(round(scale(tnx_val, 5.5, 3.0)))

    sc["fiscal"] = int(round(scale(raw["GOLD_chg"], 5.0, -2.0)))

    # ✅ 개선 3: 관세·제재 = 달러방향(40%) + 금방향(40%) + 유가절대값(20%)
    #   이유: 관세/제재 압박 → 달러 강세 + 금 상승 + 에너지 제재로 유가 고수준
    #   기존 달러+유가변화율 조합은 실제 무역압박과 무관했음
    dxy_c    = raw["DXY_chg"] or 0
    gold_c   = raw["GOLD_chg"] or 0
    dollar_sc = scale(dxy_c,    2.0,   -2.0)   # 달러 약세=좋음
    gold_sc   = scale(gold_c,   5.0,   -2.0)   # 금 안정=좋음
    oil_sanc  = scale(oil_val,  105.0,  65.0)  # 유가 낮을수록=제재 완화
    sc["tariff"] = int(round(
        dollar_sc * 0.4 + gold_sc * 0.4 + oil_sanc * 0.2
    ))

    ndx_c = raw["NDX_chg"] or 0
    spx_c = raw["SPX_chg"] or 0
    sc["reg"] = int(round(scale(ndx_c - spx_c, -3.0, 3.0)))

    # ── 심리 축 ──────────────────────────────────────────
    sc["vix"]       = int(round(scale(vix_val, 35.0, 15.0)))
    ewy_c           = raw["EWY_chg"] or 0
    usd_c           = raw["USDKRW_chg"] or 0
    sc["foreign"]   = int(round(scale(ewy_c - usd_c * 0.5, -5.0, 5.0)))
    sc["retail"]    = int(round(scale(raw["ARKK_chg"], 8.0, -3.0)))
    sc["narrative"] = int(round(scale(ndx_c, 8.0, -2.0)))

    # ── 상황 자동 감지 ──────────────────────────────────
    situation = "normal"
    if vix_val > 28 and (raw["OIL_chg"] or 0) > 5:
        situation = "war"
    elif (raw["TNX_chg"] or 0) > 0.8 or tnx_val > 5.0:
        situation = "policy"
    elif vix_val > 35:
        situation = "pandemic"
    elif ndx_c > 3 and vix_val < 20:
        situation = "tech"

    collected = sum(1 for k in ["VIX","OIL","TNX","NDX"] if raw.get(k) is not None)
    print(f"  수집 {collected}/4, 상황={situation}")
    print(f"  개선점수: oil={sc['oil']} chokepoint={sc['chokepoint']} tariff={sc['tariff']}")

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
