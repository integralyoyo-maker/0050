import json, sys, urllib.request, yfinance as yf

def tryy(sym, **kw):
    try:
        df = yf.Ticker(sym).history(**kw)
        print(f"[yf] {sym} {kw}: {len(df)} rows", "" if df.empty else f"| {df.index[-1]} close={df['Close'].iloc[-1]}")
    except Exception as e:
        print(f"[yf] {sym}: ERR {e}")

for s in ["^GSPC", "^IXIC", "^DJI", "^SOX", "^VIX", "ES=F", "NQ=F", "YM=F", "TSM", "NVDA", "^TWII", "TWN=F", "WTX&F", "TX=F", "TXF=F", "^TAIEX", "EWT"]:
    tryy(s, period="1d", interval="5m")

def post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    try:
        r = urllib.request.urlopen(req, timeout=20); return r.status, r.read().decode()[:1500]
    except Exception as e:
        return "ERR", str(e)[:300]

for mt in ("0", "1"):   # 0=日盤 1=夜盤
    print("[taifex]", mt, post("https://mis.taifex.com.tw/futures/api/getQuoteList",
        {"MarketType": mt, "SymbolType": "F", "KindID": "1", "CID": "TXF", "ExpireMonth": "", "RowSize": "全部", "PageNo": "", "SortColumn": "", "AscDesc": "A"}))

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        r = urllib.request.urlopen(req, timeout=20); return r.status, r.read().decode()[:800]
    except Exception as e:
        return "ERR", str(e)[:300]
print("[finmind fut]", get("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanFuturesDaily&data_id=TX&start_date=2026-11-20"))
print("[twse mis]", get("https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw&json=1&delay=0"))
