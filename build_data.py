"""抓取股價 → 計算指標/訊號/回測 → 輸出 docs/data/*.json 給網頁讀取。

用法：
  python build_data.py                 # 讀 watchlist.txt，抓 Yahoo Finance 資料
  python build_data.py --demo          # 產生「假資料」測試網頁（不連網，數字沒有任何意義）
  python build_data.py --period 5y     # 日線抓多久（預設 5y）

每檔標的輸出四個週期的檔案：
  日線 {代號}.json（含三種策略的回測）、週線 .W.json、月線 .M.json（由日線重新取樣）、
  小時線 .H.json（另外向 Yahoo 抓約 1 年）。週/月/小時線只有圖表與 EMA 趨勢/DMI 訊號，沒有策略回測。

設計重點：
  * 某一檔抓失敗時，保留它「上一次成功」的資料並在網頁上標示過期，不會讓它從選單消失。
  * 小時線抓失敗不影響日線；失敗時沿用上一次的小時線檔案。
  * 失敗會用 GitHub Actions 的 ::warning:: 標註，全部失敗才讓工作失敗（GitHub 會寄信通知）。
  * 上市(.TW) 查無資料時自動改試上櫃(.TWO)。
  * 上市不到一年的新 ETF（EMA200 算不出來）照樣顯示，並在網頁提醒回測不可靠。
"""
import argparse
import json
import math
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import signals as S

ROOT = Path(__file__).parent
OUT = ROOT / "docs" / "data"
TZ = timezone(timedelta(hours=8))
MIN_BARS = {"D": 40, "H": 60, "W": 30, "M": 24}   # 各週期至少要有幾根 K 棒才分析
EMA_OK_BARS = 120        # 日線：EMA200 至少有這麼多筆有效值，才從 EMA200 起算回測
HOURLY_PERIOD = "1y"     # Yahoo 的小時線最多只提供約 730 天
EMIT_BARS = {"H": 700}   # 小時線只輸出最近 700 根（約 140 個交易日），其餘用來暖機指標
TF_NAME = {"H": "小時", "D": "日", "W": "週", "M": "月"}


def expected_last_close(now: datetime):
    """台北時間 15:00 後，應該已有當天收盤資料；15:00 前則是前一個平日。（不含國定假日）"""
    d = now.date()
    if now.hour < 15:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def read_watchlist(path: Path):
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        items.append((parts[0], parts[1] if len(parts) > 1 else parts[0]))
    return items


def _clean(raw: pd.DataFrame, intraday: bool = False) -> pd.DataFrame:
    raw = raw.copy()
    idx = pd.to_datetime(raw.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert("Asia/Taipei").tz_localize(None)   # 一律換成台北時間的「牆上時間」
    raw.index = idx if intraday else idx.normalize()
    adj = raw["Adj Close"] if "Adj Close" in raw else raw["Close"]
    df = pd.DataFrame({
        "open": raw["Open"], "high": raw["High"], "low": raw["Low"], "close": raw["Close"],
        "volume": raw["Volume"].fillna(0), "adj": adj,
    }).dropna(subset=["open", "high", "low", "close"])
    df["adj"] = df["adj"].fillna(df["close"])
    return df[~df.index.duplicated(keep="last")].sort_index()


def fetch_yahoo(symbol: str, period: str, interval: str = "1d", candidates=None):
    """回傳 (DataFrame, 實際使用的代號)。.TW 查無資料時改試 .TWO（上櫃）。"""
    import yfinance as yf
    intraday = interval != "1d"
    if candidates is None:
        candidates = [symbol] + ([symbol[:-3] + ".TWO"] if symbol.endswith(".TW") else [])
    last_err = "Yahoo 沒有回傳資料"
    for sym in candidates:
        raised = False
        for attempt in range(3):          # Yahoo 偶爾限流或暫時失敗，重試
            try:
                raw = yf.Ticker(sym).history(period=period, interval=interval, auto_adjust=False)
            except Exception as e:
                raised, raw = True, None
                last_err = f"{type(e).__name__}: {e}"
                print(f"[重試 {attempt + 1}/3] {sym} {interval}: {last_err}", file=sys.stderr)
            if raw is not None and not raw.empty:
                if not intraday:
                    # 把 Yahoo 原始的最後 3 筆印在紀錄裡，方便判斷「Yahoo 沒給」還是「程式濾掉」
                    rows = []
                    for i, r in raw.tail(3).iterrows():
                        vol = "NaN" if pd.isna(r["Volume"]) else f"{int(r['Volume'])}"
                        rows.append(f"{pd.Timestamp(i).strftime('%m-%d')} 收{r['Close']:.2f} 量{vol}")
                    print(f"[Yahoo 原始最後 3 筆] {sym}: " + " | ".join(rows))
                return _clean(raw, intraday), sym
            if attempt < 2:
                time.sleep(4 * (attempt + 1))
        if raised:                         # 有例外＝網路/限流，不是代號問題，不必改試上櫃
            break
    raise RuntimeError(f"{symbol} {interval} 抓不到資料：{last_err}")


def resample_ohlc(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """日線 → 週線(W)/月線(M)。K 棒的日期用該期間「最後一個交易日」，不會出現未來日期。"""
    key = df.index.to_period("W" if tf == "W" else "M")
    g = df.groupby(key)
    out = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
        "close": g["close"].last(), "volume": g["volume"].sum(), "adj": g["adj"].last(),
    })
    out.index = pd.DatetimeIndex(df.index.to_series().groupby(key).last().values)
    return out


def make_demo(symbol: str, days: int = 1300, hourly: bool = False) -> pd.DataFrame:
    """隨機漫步假資料，只用來測試網頁與程式流程。"""
    import zlib
    if not hourly and re.fullmatch(r"\d{5}[A-Z]\.TWO?", symbol):   # 模擬新上市主動式 ETF（資料很短）
        days = 95
    rng = np.random.default_rng(zlib.crc32((symbol + ("#H" if hourly else "")).encode()))
    if hourly:      # 台股每天 5 根小時線（09、10、11、12、13 點），約 240 個交易日
        day_idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=240)
        idx = pd.DatetimeIndex([d + pd.Timedelta(hours=h) for d in day_idx for h in (9, 10, 11, 12, 13)])
        sigma = 0.008
    else:
        idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
        sigma = 0.018
    n = len(idx)
    k = sigma / 0.018
    ret = rng.normal(0.0004, sigma, n)
    close = 100 * np.exp(np.cumsum(ret))
    open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.004 * k, n))
    spread = np.abs(rng.normal(0.012 * k, 0.006 * k, n)) * close
    high = np.maximum(open_, close) + spread * rng.uniform(0.1, 0.9, n)
    low = np.minimum(open_, close) - spread * rng.uniform(0.1, 0.9, n)
    vol = (rng.lognormal(10, 0.5, n) * (1 + 3 * np.abs(ret) / sigma)).astype(int) * 1000
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                       "volume": vol, "adj": close}, index=idx)
    return df.round(2)


def num(x):
    """NaN → None，其餘四捨五入，確保 JSON 合法。"""
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), 4)


def tkey(tf: str):
    """圖表用的時間：日/週/月用 'YYYY-MM-DD'；小時線用秒數（把台北時間當 UTC 算，圖上就會顯示台北時間）。"""
    if tf == "H":
        return lambda d: int((d - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1))
    return lambda d: d.strftime("%Y-%m-%d")


def series_points(df, col, tk):
    return [{"time": tk(d), "value": num(v)} for d, v in df[col].items() if num(v) is not None]


def tax_rate(symbol: str) -> float:
    """證交稅：ETF（代號 00 開頭）賣出 0.1%，一般股票 0.3%。債券 ETF 目前免稅，這裡沒有特別處理。"""
    return 0.001 if symbol.split(".")[0].startswith("00") else 0.003


def build_one(symbol: str, name: str, df: pd.DataFrame, demo: bool, tf: str = "D") -> dict:
    df = df.copy()
    n = len(df)
    costs = {"fee": 0.001425, "tax": tax_rate(symbol), "stop": 0.08}
    if n < MIN_BARS[tf]:
        raise RuntimeError(f"{symbol} {TF_NAME[tf]}線只有 {n} 筆資料（至少需要 {MIN_BARS[tf]} 筆）")

    if tf == "D":
        # 還原價（含除權息）供回測使用；顯示用原始價，與看盤軟體一致
        factor = (df["adj"] / df["close"]).replace([np.inf, -np.inf], np.nan).fillna(1.0)
        df["bt_open"] = df["open"] * factor
        df["bt_close"] = df["adj"]

    df = S.add_indicators(df)
    df = S.add_vsa(df)
    df = S.add_ema_trend(df)

    ema_bars = int(df["ema200"].notna().sum())
    notes = []
    start_idx = 0
    if tf == "D":
        if ema_bars >= EMA_OK_BARS:
            start_idx = int(df["ema200"].notna().values.argmax())
        else:
            start_idx = 29                       # 量能均線 30 日起算
            notes.append(
                f"這檔只有 {n} 個交易日的資料（約 {n / 245:.1f} 年），EMA200 只有 {ema_bars} 筆可用，"
                "「多頭回檔」策略幾乎不會出現訊號，各策略的回測樣本也極少，績效數字參考價值很低。")
    elif ema_bars == 0:
        notes.append(f"{TF_NAME[tf]}線只有 {n} 根 K 棒，EMA200 需要至少 200 根才算得出來，所以圖上沒有 EMA200；"
                     "EMA5～EMA60 與 DMI 不受影響。")

    if tf in EMIT_BARS and len(df) > EMIT_BARS[tf]:
        df = df.iloc[-EMIT_BARS[tf]:]        # 指標用完整資料暖機算完，只輸出最近這些根，控制檔案大小
        n = len(df)

    tk = tkey(tf)
    dfmt =(lambda d: d.strftime("%Y-%m-%d %H:%M")) if tf == "H" else (lambda d: d.strftime("%Y-%m-%d"))
    candles = [{"time": tk(d), "open": num(r.open), "high": num(r.high),
                "low": num(r.low), "close": num(r.close)} for d, r in df.iterrows()]
    volume = [{"time": tk(d), "value": int(r.volume),
               "up": bool(r.close >= r.open)} for d, r in df.iterrows()]

    vsa = []
    for key in S.VSA_LABELS:
        col = f"vsa_{key}"
        vsa += [{"time": tk(d), "kind": key} for d in df.index[df[col]]]

    esig = []
    for key in S.EMA_SIG_LABELS:
        esig += [{"time": tk(d), "kind": key} for d in df.index[df[f"es_{key}"]]]
    esig.sort(key=lambda s: s["time"])

    gaps = [{**g, "time": tk(g["time"])} for g in S.find_unfilled_gaps(df)]

    strategies = {}
    if tf == "D":
        for key, meta in S.STRATEGIES.items():
            entry, exit_ = S.strategy_signals(df, key)
            stats, trades, eq, bh = S.backtest(df, entry, exit_, fee=costs["fee"], tax=costs["tax"],
                                               stop=costs["stop"], start_idx=start_idx)
            strategies[key] = {
                **meta,
                "stats": stats,
                "trades": [{k: v for k, v in t.items() if k not in ("entry_sig", "exit_sig")} for t in trades[-30:]],
                "equity": [{"time": tk(d), "value": num(v)} for d, v in eq.items()],
                "buyhold": [{"time": tk(d), "value": num(v)} for d, v in bh.items()],
                # 圖上只標「實際成交」的買賣（標在訊號日；成交在隔天開盤）
                "markers": (
                    [{"time": t["entry_sig"], "side": "buy"} for t in trades]
                    + [{"time": t["exit_sig"], "side": "sell"} for t in trades if t["exit_sig"]]
                ),
            }

    last, prev = df.iloc[-1], df.iloc[-2]
    return {
        "symbol": symbol, "name": name, "demo": demo, "tf": tf,
        "updated": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
        "last": {"date": dfmt(df.index[-1]), "close": num(last.close),
                 "change": num(last.close - prev.close),
                 "pct": num((last.close / prev.close - 1) * 100)},
        "backtest_start": dfmt(df.index[start_idx]),
        "bars": n, "notes": notes,
        "costs": costs,
        "candles": candles, "volume": volume,
        "volma": series_points(df, "vol_ma30", tk),
        "lines": {k: series_points(df, k, tk) for k in
                  ("ma5", "ma20", "ma60", "ema5", "ema10", "ema30", "ema60", "ema200", "bb_up", "bb_mid", "bb_dn")},
        "dmi": {k: series_points(df, k, tk) for k in ("adx", "pdi", "mdi")},
        "regime": [{"time": tk(d), "s": s} for d, s in df["regime"].items()],
        "now": {"state": last["regime"] or None, "adx": num(last["adx"]),
                "pdi": num(last["pdi"]), "mdi": num(last["mdi"])},
        "esig": esig,
        "vsa": vsa, "gaps": gaps, "strategies": strategies,
    }


def write_json(path: Path, data: dict):
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watchlist", default=str(ROOT / "watchlist.txt"))
    ap.add_argument("--period", default="5y")
    ap.add_argument("--demo", action="store_true", help="用假資料測試（不連網）")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)

    # 讀上一次成功的索引，抓失敗時沿用舊資料
    old = {}
    idx_path = OUT / "index.json"
    if idx_path.exists() and not args.demo:
        try:
            prev_idx = json.loads(idx_path.read_text(encoding="utf-8"))
            if not prev_idx.get("demo"):
                old = {i["symbol"]: i for i in prev_idx.get("items", [])}
        except Exception:
            pass

    index, failed, first = [], [], True
    now = datetime.now(TZ)
    today = now.date()
    expected = expected_last_close(now)
    for symbol, name in read_watchlist(Path(args.watchlist)):
        if not args.demo and not first:
            time.sleep(1.5)                  # 別連續猛打 Yahoo，降低被限流的機率
        first = False
        try:
            df, used = (make_demo(symbol), symbol) if args.demo else fetch_yahoo(symbol, args.period)
            data = build_one(symbol, name, df, args.demo, "D")
        except Exception as e:               # 單一檔失敗不影響其他檔
            msg = str(e).replace("\n", " ")[:300]
            failed.append((symbol, msg))
            print(f"::warning title=更新失敗 {symbol}::{msg}")
            prev = old.get(symbol)
            if prev and (OUT / prev["file"]).exists():
                files = prev.get("files") or {"D": prev["file"]}
                index.append({**prev, "files": files, "name": name, "stale": True, "error": msg})
                print(f"[沿用舊資料] {symbol} {name}  收盤日 {prev.get('date')}")
            else:
                print(f"[失敗且無舊資料] {symbol} {name}")
            continue

        base = symbol.replace("^", "_").replace("&", "_").replace("=", "_")
        files = {"D": base + ".json"}
        write_json(OUT / files["D"], data)

        for tf in ("W", "M"):                # 週/月線由日線重新取樣，不必再抓資料
            try:
                d2 = build_one(symbol, name, resample_ohlc(df, tf), args.demo, tf)
            except Exception as e:
                print(f"[略過{TF_NAME[tf]}線] {symbol}: {e}")
                continue
            files[tf] = f"{base}.{tf}.json"
            write_json(OUT / files[tf], d2)

        try:                                  # 小時線：另外抓，失敗不影響日線
            if not args.demo:
                time.sleep(1.5)
            dfh = make_demo(symbol, hourly=True) if args.demo else fetch_yahoo(used, HOURLY_PERIOD, "1h", candidates=[used])[0]
            dh = build_one(symbol, name, dfh, args.demo, "H")
            files["H"] = f"{base}.H.json"
            write_json(OUT / files["H"], dh)
            print(f"[小時線] {symbol} 共 {dh['bars']} 根，最新 {dh['last']['date']}")
        except Exception as e:
            msg = str(e).replace("\n", " ")[:300]
            print(f"::warning title=小時線失敗 {symbol}::{msg}")
            hf = f"{base}.H.json"
            if (OUT / hf).exists():
                files["H"] = hf
                print(f"[小時線沿用舊檔] {symbol}")

        index.append({"symbol": symbol, "name": name, "file": files["D"], "files": files,
                      "stale": False, **data["last"]})
        extra = f"（{symbol} 查無資料，改用 {used}）" if used != symbol else ""
        print(f"[完成] {symbol} {name}  最新收盤日 {data['last']['date']}  收盤 {data['last']['close']}  共 {data['bars']} 筆 {extra}")
        last_d = datetime.strptime(data["last"]["date"], "%Y-%m-%d").date()
        if not args.demo and last_d < expected:
            print(f"::warning title=Yahoo 尚無最新資料 {symbol}::最新只到 {last_d}，依日期應已有 {expected} 的收盤（若剛好休市可忽略）")
        age = (today - last_d).days
        if age > 5 and not args.demo:
            print(f"::warning title=資料偏舊 {symbol}::最新資料是 {data['last']['date']}，距今 {age} 天（連假屬正常）")

    keep = {"index.json"}
    for i in index:
        keep |= set(i["files"].values())
    for f in OUT.glob("*.json"):            # 清掉已不在清單內的舊檔
        if f.name not in keep:
            f.unlink()

    idx_path.write_text(json.dumps(
        {"demo": args.demo, "built": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"), "items": index},
        ensure_ascii=False, indent=1), encoding="utf-8")

    ok = sum(1 for i in index if not i.get("stale"))
    print(f"\n成功 {ok} 檔、沿用舊資料 {len(index) - ok} 檔、失敗 {len(failed)} 檔")
    if failed and ok == 0:
        sys.exit("全部標的都更新失敗，請檢查網路、Yahoo 是否限流，或代號是否正確。")


if __name__ == "__main__":
    main()
