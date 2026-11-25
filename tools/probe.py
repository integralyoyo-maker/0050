import json, urllib.request
def post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0", "Referer": "https://mis.taifex.com.tw/futures/"})
    try:
        r = urllib.request.urlopen(req, timeout=20); return r.status, r.read().decode()
    except Exception as e:
        return "ERR", str(e)[:300]
for ep in ("getChartData1M", "getChartData", "getQuoteDetail"):
    for sid in ("TXFL6-M", "TXFL6-F"):
        st, body = post(f"https://mis.taifex.com.tw/futures/api/{ep}", {"SymbolID": sid, "MarketType": "1" if sid.endswith("M") else "0", "SymbolType": "F", "KindID": "1", "CID": "TXF"})
        print(f"[{ep}] {sid} -> {st} len={len(body)} :: {body[:700]}")
