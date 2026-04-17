"""
Market Dashboard v5 - 전면 재설계
핵심 변경사항:
  - piecewise linear scale (비선형) 도입
  - 5일 + 20일 혼합으로 단기 노이즈 완화
  - 구조적 고유가 반영 ($85 중립 기준)
  - 공급망 축 VIX 의존 완전 제거 (축별 독립성)
  - 금 절대값 수준으로 불확실성 직접 반영
  - VIX 52주 범위 상대 위치 추가
  - 한국 외국인수급 3중 교차 (EWY+KOSPI+환율)
  - 데이터 실패 시 None 처리 (5점 혼용 제거)
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

# ─── 데이터 수집 ────────────────────────────────────────
def fetch(symbol, days="5d"):
    for base in ["query1", "query2"]:
        try:
            url = f"https://{base}.finance.yahoo.com/v8/finance/chart/{symbol}"
            r = requests.get(url, params={"interval":"1d","range":days},
                             headers=HEADERS, timeout=12)
            closes = r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            closes = [c for c in closes if c is not None]
            if len(closes) < 2:
                continue
            return closes
        except:
            continue
    return None

def get_data(symbol):
    """5일 + 20일 데이터 동시 수집"""
    c20 = fetch(symbol, "30d")  # 20일 계산용
    c5  = c20[-6:] if c20 and len(c20) >= 6 else fetch(symbol, "5d")
    if not c5 or len(c5) < 2:
        return None, None, None
    val   = round(c5[-1], 2)
    chg5  = round((c5[-1] - c5[0]) / c5[0] * 100, 2)
    chg20 = round((c20[-1] - c20[0]) / c20[0] * 100, 2) if c20 and len(c20) >= 20 else chg5
    return val, chg5, chg20

def get_52w(symbol):
    """52주 최고/최저"""
    try:
        closes = fetch(symbol, "1y")
        if not closes:
            return None, None
        return round(min(closes), 2), round(max(closes), 2)
    except:
        return None, None

# ─── 점수 계산 함수 ─────────────────────────────────────
def scale_pw(v, bad, mid, good):
    """Piecewise linear: bad=0, mid=5, good=10"""
    if v is None: return None
    if bad > good:  # 역방향 (낮을수록 위험)
        bad, good = good, bad
        if v <= bad: return 10.0
        if v >= good: return 0.0
        mid_rev = good - (mid - bad)
        if v >= mid_rev:
            return 5.0 * (good - v) / (good - mid_rev)
        else:
            return 5.0 + 5.0 * (mid_rev - v) / (mid_rev - bad)
    if v <= bad: return 0.0
    if v >= good: return 10.0
    if v <= mid:
        return 5.0 * (v - bad) / (mid - bad)
    else:
        return 5.0 + 5.0 * (v - mid) / (good - mid)

def scale_lin(v, bad, good):
    if v is None: return None
    return max(0.0, min(10.0, (v - bad) / (good - bad) * 10))

def blend(*pairs):
    """(score, weight) 쌍의 가중평균. None 제외."""
    s, w = 0, 0
    for score, weight in pairs:
        if score is not None:
            s += score * weight; w += weight
    return round(s / w, 1) if w > 0 else None

def to_int(v, fallback=None):
    if v is None: return fallback
    return int(round(max(0, min(10, v))))

# ─── 메인 수집 및 채점 ─────────────────────────────────
def collect():
    print("📡 v5 데이터 수집...")

    # 수집
    tnx_val,  tnx5,  tnx20  = get_data("^TNX")
    dxy_val,  dxy5,  dxy20  = get_data("DX-Y.NYB")
    hyg_val,  hyg5,  hyg20  = get_data("HYG")
    tlt_val,  tlt5,  tlt20  = get_data("TLT")
    oil_val,  oil5,  oil20  = get_data("CL=F")
    bdry_val, bdry5, _      = get_data("BDRY")
    soxx_val, soxx5, soxx20 = get_data("SOXX")
    cop_val,  cop5,  cop20  = get_data("HG=F")
    gold_val, gold5, gold20 = get_data("GC=F")
    vix_val,  vix5,  _      = get_data("^VIX")
    vix_lo, vix_hi          = get_52w("^VIX")
    spx_val,  spx5,  spx20  = get_data("^GSPC")
    ndx_val,  ndx5,  ndx20  = get_data("^IXIC")
    arkk_val, arkk5, _      = get_data("ARKK")
    ksp_val,  ksp5,  ksp20  = get_data("^KS11")
    krw_val,  krw5,  krw20  = get_data("USDKRW=X")
    ewy_val,  ewy5,  ewy20  = get_data("EWY")

    print(f"  VIX={vix_val} OIL={oil_val} TNX={tnx_val} NDX5={ndx5} KRW={krw_val}")

    SC = {}

    # ══ 💧 유동성 축 ══════════════════════════════════════
    # 금리방향: 절대수준(60%) + 5일방향(25%) + 20일추세(15%)
    SC["rate"] = to_int(blend(
        (scale_pw(tnx_val, 6.0, 4.5, 3.0),  0.60),
        (scale_lin(tnx5,    0.5, -0.3),       0.25),
        (scale_lin(tnx20,   1.0, -0.5),       0.15),
    ))
    # 달러강약: 5일+20일 동일 비중
    SC["dollar"] = to_int(blend(
        (scale_lin(dxy5,  3.0, -3.0), 0.5),
        (scale_lin(dxy20, 4.0, -4.0), 0.5),
    ))
    # 신용스프레드: HYG 5일+20일
    SC["credit"] = to_int(blend(
        (scale_lin(hyg5,  -2.0, 2.0), 0.5),
        (scale_lin(hyg20, -3.0, 3.0), 0.5),
    ))
    # FOMC톤: TLT 20일 중심 (정책은 중기 흐름)
    SC["fomc"] = to_int(blend(
        (scale_lin(tlt5,  -3.0, 3.0), 0.4),
        (scale_lin(tlt20, -5.0, 5.0), 0.6),
    ))

    # ══ ⚙️ 공급망 축 (VIX 완전 배제) ════════════════════
    # 유가방향: 절대수준(55%) + 5일(30%) + 20일(15%)
    # 구조적 고유가 반영: $60=안전, $85=중립, $110=위험
    SC["oil"] = to_int(blend(
        (scale_pw(oil_val, 110.0, 85.0, 60.0), 0.55),
        (scale_lin(oil5,    12.0, -8.0),        0.30),
        (scale_lin(oil20,   15.0,-10.0),        0.15),
    ))
    # 해운운임: BDRY(60%) + 유가수준(40%) — VIX 제거
    SC["freight"] = to_int(blend(
        (scale_lin(bdry5,  20.0, -5.0),         0.60),
        (scale_pw(oil_val, 110.0, 85.0, 60.0),  0.40),
    ))
    # 반도체수급: 5일(40%) + 20일(60%) — 중기 추세 중시
    SC["semi"] = to_int(blend(
        (scale_lin(soxx5,  -8.0, 8.0),  0.40),
        (scale_lin(soxx20,-12.0,15.0),  0.60),
    ))
    # 지정학: 유가절대값(50%) + 유가변동성(30%) + 구리방향(20%)
    SC["chokepoint"] = to_int(blend(
        (scale_pw(oil_val,         115.0, 85.0, 60.0), 0.50),
        (scale_lin(abs(oil5 or 0),  18.0,  1.0),       0.30),
        (scale_lin(cop5,            -5.0,  8.0),        0.20),
    ))

    # ══ ⚖️ 정책 축 ════════════════════════════════════════
    # 중앙은행: 금리절대값(65%) + TLT20일(35%)
    SC["cb"] = to_int(blend(
        (scale_pw(tnx_val, 6.0, 4.5, 3.0), 0.65),
        (scale_lin(tlt20, -5.0, 5.0),       0.35),
    ))
    # 재정·보조금: 금절대값(50%) + 금5일(25%) + 금20일(25%)
    # 금 $3000=안전, $4500=중립(구조적 고가), $6000=위험
    SC["fiscal"] = to_int(blend(
        (scale_pw(gold_val, 6000.0, 4500.0, 3000.0), 0.50),
        (scale_lin(gold5,    5.0, -3.0),              0.25),
        (scale_lin(gold20,   8.0, -5.0),              0.25),
    ))
    # 관세·제재: 달러(30%) + 금방향(30%) + 구리(25%) + 유가수준(15%)
    SC["tariff"] = to_int(blend(
        (scale_lin(dxy5,    3.0, -3.0),               0.30),
        (scale_lin(gold5,   5.0, -3.0),               0.30),
        (scale_lin(cop5,   -5.0,  8.0),               0.25),
        (scale_pw(oil_val, 110.0, 85.0, 65.0),        0.15),
    ))
    # 규제방향: 나스닥상대강도(50%) + 반도체20일(50%)
    SC["reg"] = to_int(blend(
        (scale_lin((ndx5 or 0)-(spx5 or 0), -3.0, 3.0), 0.50),
        (scale_lin(soxx20, -10.0, 15.0),                  0.50),
    ))

    # ══ 🧠 심리 축 ════════════════════════════════════════
    # VIX: 절대값(piecewise, 60%) + 52주 상대위치(40%)
    vix_abs = scale_pw(vix_val, 35.0, 20.0, 13.0)
    vix_rng = (vix_hi - vix_lo) if (vix_hi and vix_lo and vix_hi > vix_lo) else None
    vix_rel = (10.0*(1-(vix_val-vix_lo)/vix_rng)) if (vix_rng and vix_val) else None
    if vix_rel: vix_rel = max(0, min(10, vix_rel))
    SC["vix"] = to_int(blend(
        (vix_abs, 0.60), (vix_rel, 0.40)
    ))
    # 외국인수급: EWY(35%) + KOSPI(25%) + 환율방향(25%) + 환율수준(15%)
    SC["foreign"] = to_int(blend(
        (scale_lin(ewy5,   -5.0,  8.0),             0.35),
        (scale_lin(ksp5,   -5.0,  8.0),             0.25),
        (scale_lin(krw5,    2.0, -2.0),             0.25),
        (scale_pw(krw_val, 1600.0, 1400.0, 1200.0), 0.15),
    ))
    # 개인과열도: ARKK(40%) + 나스닥5일(35%) + 나스닥20일(25%)
    SC["retail"] = to_int(blend(
        (scale_lin(arkk5, 10.0, -2.0), 0.40),
        (scale_lin(ndx5,  10.0, -2.0), 0.35),
        (scale_lin(ndx20, 15.0, -3.0), 0.25),
    ))
    # 서사과열: 나스닥 5일+20일
    SC["narrative"] = to_int(blend(
        (scale_lin(ndx5,  10.0, -2.0), 0.50),
        (scale_lin(ndx20, 18.0, -3.0), 0.50),
    ))

    # None인 지표는 fallback=5
    for k in SC:
        if SC[k] is None: SC[k] = 5

    # 상황 자동 감지
    vix_v   = vix_val or 20
    oil_v   = oil_val or 75
    tnx_v   = tnx_val or 4.5
    ndx_v   = ndx5 or 0
    oil_v5  = oil5 or 0
    situation = "normal"
    if vix_v > 28 and oil_v5 > 5:    situation = "war"
    elif tnx_v > 5.0:                 situation = "policy"
    elif vix_v > 35:                  situation = "pandemic"
    elif ndx_v > 3 and vix_v < 20:   situation = "tech"

    collected = sum(1 for v in [vix_val, oil_val, tnx_val, ndx_val, krw_val] if v)
    print(f"  수집 {collected}/5, 상황={situation}")
    print(f"  rate={SC['rate']} oil={SC['oil']} choke={SC['chokepoint']} vix={SC['vix']} foreign={SC['foreign']}")

    return {
        "updated":   datetime.now().strftime("%Y-%m-%d %H:%M"),
        "situation": situation,
        "version":   "v5",
        "collected": collected,
        "scores":    SC,
        "raw": {
            "vix":        vix_val or 0,
            "vix_hi":     vix_hi or 0,
            "vix_lo":     vix_lo or 0,
            "spx_chg":    spx5 or 0,
            "ndx_chg":    ndx5 or 0,
            "ndx_chg20":  ndx20 or 0,
            "kospi_chg":  ksp5 or 0,
            "usdkrw":     krw_val or 0,
            "usdkrw_chg": krw5 or 0,
            "oil":        oil_val or 0,
            "oil_chg":    oil5 or 0,
            "oil_chg20":  oil20 or 0,
            "tnx":        tnx_val or 0,
            "tnx_chg":    tnx5 or 0,
            "dxy":        dxy_val or 0,
            "dxy_chg":    dxy5 or 0,
            "soxx_chg":   soxx5 or 0,
            "soxx_chg20": soxx20 or 0,
            "ewy_chg":    ewy5 or 0,
            "gold":       gold_val or 0,
            "gold_chg":   gold5 or 0,
            "copper_chg": cop5 or 0,
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
    for sym in ["^VIX","^GSPC","CL=F","^TNX","DX-Y.NYB","^KS11","USDKRW=X","HG=F","GC=F","SOXX"]:
        val, chg5, chg20 = get_data(sym)
        results[sym] = {"val": val, "chg5": chg5, "chg20": chg20}
    return jsonify(results)

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
