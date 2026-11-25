import json, urllib.request
req = urllib.request.Request("https://mis.taifex.com.tw/futures/api/getChartData1M", data=json.dumps({"SymbolID":"TXFL6-M","MarketType":"1","SymbolType":"F","KindID":"1","CID":"TXF"}).encode(), headers={"Content-Type":"application/json","User-Agent":"Mozilla/5.0","Referer":"https://mis.taifex.com.tw/futures/"})
j = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
d = j["RtData"]
print("KEYS", list(d.keys()))
for k, v in d.items():
    if isinstance(v, list):
        print("LIST", k, len(v), json.dumps(v[:2], ensure_ascii=False), json.dumps(v[-1:], ensure_ascii=False))
    elif isinstance(v, dict) and k != "Quote":
        print("DICT", k, json.dumps(v, ensure_ascii=False)[:300])
