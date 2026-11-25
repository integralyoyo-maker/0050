"""美股與台指期夜盤報價 → markets.json（由 .github/workflows/markets.yml 約每 5 分鐘執行）。

資料來源：
- 美股指數／期貨／個股／匯率：Yahoo Finance（經 yfinance，5 分鐘 K）。
- 台指期夜盤：期交所 MIS 網站使用的公開 JSON 介面（mis.taifex.com.tw），夜盤時段 15:00～次日 05:00。
用法：python markets.py 輸出資料夾
"""
import json, sys, urllib.request, datetime as dt
from pathlib import Path

TZ = dt.timezone(dt.timedelta(hours=8))
US = [
    ("^GSPC", "標普500"), ("^IXIC", "那斯達克"), ("^DJI", "道瓊工業"), ("^SOX", "費城半導體"), ("^VIX", "VIX 恐慌指數"),
    ("ES=F", "標普500期貨"), ("NQ=F", "那斯達克期貨"), ("YM=F", "道瓊期貨"),
    ("TSM", "台積電 ADR"), ("NVDA", "輝達"), ("AAPL", "蘋果"), ("MSFT", "微軟"), ("EWT", "台灣 ETF（EWT）"), ("TWD=X", "美元／台幣"),
]
MIS = "https://mis.taifex.com.tw/futures/api/"


def num(x):
    try:
        v = float(x)
        return v
    except (TypeError, ValueError):
        return None


def taifex(path, payload):
    req = urllib.request.Request(MIS + path, data=json.dumps(payload).encode(), headers={
        "Content-Type": "application/json", "User-Agent": "Mozilla/5.0", "Referer": "https://mis.taifex.com.tw/futures/"})
    j = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
    if j.get("RtCode") != "0":
        raise RuntimeError(f"期交所回應 {j.get('RtCode')} {j.get('RtMsg')}")
    return j["RtData"]


def us_one(sym, name):
    import yfinance as yf
    t = yf.Ticker(sym)
    h = t.history(period="5d", interval="5m", auto_adjust=False).dropna(subset=["Close"])
    if h.empty:
        raise ValueError("沒有 5 分鐘資料")
    if sym.endswith("=F") or sym.endswith("=X"):          # 近乎 24 小時交易：取最近 24 小時
        h = h[h.index > h.index[-1] - dt.timedelta(hours=24)]
    else:                                                  # 取最近一個交易日
        h = h[[d == h.index[-1].date() for d in h.index.date]]
    prev = None
    try:
        prev = num(t.fast_info["previous_close"])
    except Exception:  # noqa: BLE001
        pass
    if not prev:
        dd = t.history(period="10d", interval="1d", auto_adjust=False).dropna(subset=["Close"])
        prev = float(dd["Close"].iloc[-2]) if len(dd) >= 2 else float(h["Open"].iloc[0])
    loc = h.index.tz_convert(TZ).tz_localize(None)         # 轉成台北時間顯示
    ts = [int((x - dt.datetime(1970, 1, 1)).total_seconds()) for x in loc]
    last = float(h["Close"].iloc[-1])
    return dict(symbol=sym, name=name, last=round(last, 4), prev=round(prev, 4), change=round(last - prev, 4),
                pct=round((last / prev - 1) * 100, 3), time=loc[-1].strftime("%m-%d %H:%M"),
                candles=[[t_, round(float(o), 4), round(float(hh), 4), round(float(l), 4), round(float(c), 4)]
                         for t_, o, hh, l, c in zip(ts, h["Open"], h["High"], h["Low"], h["Close"])])


def night():
    """台指期夜盤：近月（成交量最大）契約的報價、各月份契約表、5 分鐘 K。"""
    pl = {"MarketType": "1", "SymbolType": "F", "KindID": "1", "CID": "TXF", "ExpireMonth": "", "RowSize": "全部",
          "PageNo": "", "SortColumn": "", "AscDesc": "A"}
    q = taifex("getQuoteList", pl)["QuoteList"]
    spot = next((x for x in q if x["SymbolID"].endswith("-P") or x["SymbolID"].endswith("-S")), None)
    cons = []
    for x in q:
        if x is spot or num(x.get("CLastPrice")) is None:
            continue
        cons.append(dict(id=x["SymbolID"], name=x["DispCName"], last=num(x["CLastPrice"]), ref=num(x["CRefPrice"]),
                         change=num(x["CDiff"]), pct=num(x["CDiffRate"]), open=num(x["COpenPrice"]), high=num(x["CHighPrice"]),
                         low=num(x["CLowPrice"]), volume=int(num(x["CTotalVolume"]) or 0), time=x["CTime"]))
    if not cons:
        raise RuntimeError("夜盤目前沒有成交的契約")
    main = max(cons, key=lambda c: c["volume"])
    d = taifex("getChartData1M", dict(pl, SymbolID=main["id"]))
    start = dt.datetime.strptime(d["Quote"].get("CDate") or q[0]["CDate"], "%Y%m%d")
    buckets, day, prev_t = {}, 0, None
    for tk in d.get("Ticks", []):
        hhmmss = int(tk[0])
        if prev_t is not None and hhmmss < prev_t - 100000:     # 跨午夜
            day += 1
        prev_t = hhmmss
        hh, mm = hhmmss // 10000, (hhmmss // 100) % 100
        when = start + dt.timedelta(days=day, hours=hh, minutes=(mm // 5) * 5)
        o, h_, l_, c, v = (num(tk[i]) for i in (1, 2, 3, 4, 5))
        if None in (o, h_, l_, c):
            continue
        k = int((when - dt.datetime(1970, 1, 1)).total_seconds())
        b = buckets.get(k)
        if b is None:
            buckets[k] = [k, o, h_, l_, c, v or 0]
        else:
            b[2], b[3], b[4], b[5] = max(b[2], h_), min(b[3], l_), c, b[5] + (v or 0)
    return dict(session="night", hours="15:00–次日 05:00", main=main, contracts=cons,
                spot_close=num(spot["CRefPrice"]) if spot else None, candles=[buckets[k] for k in sorted(buckets)])


def main(out: Path):
    res = dict(updated=dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M"), us=[], tw=None, errors=[])
    for sym, name in US:
        try:
            res["us"].append(us_one(sym, name))
        except Exception as e:  # noqa: BLE001
            res["errors"].append(f"{sym}: {type(e).__name__}: {e}"[:200])
    try:
        res["tw"] = night()
    except Exception as e:  # noqa: BLE001
        res["errors"].append(f"台指期夜盤: {type(e).__name__}: {e}"[:200])
    for e in res["errors"]:
        print("::warning::" + e)
    if not res["us"] and not res["tw"]:
        print("::error::美股與夜盤都抓不到"); sys.exit(1)
    out.mkdir(parents=True, exist_ok=True)
    (out / "markets.json").write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"完成：美股 {len(res['us'])}/{len(US)}，夜盤 {'OK' if res['tw'] else '失敗'}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "markets_out"))
