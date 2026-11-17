"""抓取股價 → 計算指標/訊號/回測 → 輸出 docs/data/*.json 給網頁讀取。

用法：
  python build_data.py                 # 讀 watchlist.txt，抓 Yahoo Finance 資料
  python build_data.py --demo          # 產生「假資料」測試網頁（不連網，數字沒有任何意義）
  python build_data.py --period 5y     # 抓多久的資料（預設 5y）

設計重點：
  * 某一檔抓失敗時，保留它「上一次成功」的資料並在網頁上標示過期，不會讓它從選單消失。
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
MIN_BARS = 40            # 少於這個交易日數就不分析
EMA_OK_BARS = 120        # EMA200 至少有這麼多筆有效值，才從 EMA200 起算回測


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


def _clean(raw: pd.DataFrame) -> pd.DataFrame:
    raw = raw.copy()
    raw.index = pd.to_datetime(raw.index).tz_localize(None).normalize()
    adj = raw["Adj Close"] if "Adj Close" in raw else raw["Close"]
    df = pd.DataFrame({
        "open": raw["Open"], "high": raw["High"], "low": raw["Low"], "close": raw["Close"],
        "volume": raw["Volume"].fillna(0), "adj": adj,
    }).dropna(subset=["open", "high", "low", "close"])
    df["adj"] = df["adj"].fillna(df["close"])
    return df[~df.index.duplicated(keep="last")]


def fetch_yahoo(symbol: str, period: str):
    """回傳 (DataFrame, 實際使用的代號)。.TW 查無資料時改試 .TWO（上櫃）。"""
    import yfinance as yf
    candidates = [symbol] + ([symbol[:-3] + ".TWO"] if symbol.endswith(".TW") else [])
    last_err = "Yahoo 沒有回傳資料"
    for sym in candidates:
        raised = False
        for attempt in range(3):          # Yahoo 偶爾限流或暫時失敗，重試
            try:
                raw = yf.Ticker(sym).history(period=period, interval="1d", auto_adjust=False)
            except Exception as e:
                raised, raw = True, None
                last_err = f"{type(e).__name__}: {e}"
                print(f"[重試 {attempt + 1}/3] {sym}: {last_err}", file=sys.stderr)
            if raw is not None and not raw.empty:
                # 把 Yahoo 原始的最後 3 筆印在紀錄裡，方便判斷「Yahoo 沒給」還是「程式濾掉」
                rows = []
                for i, r in raw.tail(3).iterrows():
                    vol = "NaN" if pd.isna(r["Volume"]) else f"{int(r['Volume'])}"
                    rows.append(f"{pd.Timestamp(i).strftime('%m-%d')} 收{r['Close']:.2f} 量{vol}")
                print(f"[Yahoo 原始最後 3 筆] {sym}: " + " | ".join(rows))
                return _clean(raw), sym
            if attempt < 2:
                time.sleep(4 * (attempt + 1))
        if raised:                         # 有例外＝網路/限流，不是代號問題，不必改試上櫃
            break
    raise RuntimeError(f"{symbol} 抓不到資料：{last_err}")


def make_demo(symbol: str, days: int = 1300) -> pd.DataFrame:
    """隨機漫步假資料，只用來測試網頁與程式流程。"""
    import zlib
    if re.fullmatch(r"\d{5}[A-Z]\.TWO?", symbol):   # 模擬新上市主動式 ETF（資料很短）
        days = 95
    rng = np.random.default_rng(zlib.crc32(symbol.encode()))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    ret = rng.normal(0.0004, 0.018, days)
    close = 100 * np.exp(np.cumsum(ret))
    open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.004, days))
    spread = np.abs(rng.normal(0.012, 0.006, days)) * close
    high = np.maximum(open_, close) + spread * rng.uniform(0.1, 0.9, days)
    low = np.minimum(open_, close) - spread * rng.uniform(0.1, 0.9, days)
    vol = (rng.lognormal(10, 0.5, days) * (1 + 3 * np.abs(ret) / 0.018)).astype(int) * 1000
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                       "volume": vol, "adj": close}, index=idx)
    return df.round(2)


def num(x):
    """NaN → None，其餘四捨五入，確保 JSON 合法。"""
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), 4)


def series_points(df, col):
    return [{"time": d.strftime("%Y-%m-%d"), "value": num(v)}
            for d, v in df[col].items() if num(v) is not None]


def tax_rate(symbol: str) -> float:
    """證交稅：ETF（代號 00 開頭）賣出 0.1%，一般股票 0.3%。債券 ETF 目前免稅，這裡沒有特別處理。"""
    return 0.001 if symbol.split(".")[0].startswith("00") else 0.003


def build_one(symbol: str, name: str, df: pd.DataFrame, demo: bool) -> dict:
    df = df.copy()
    n = len(df)
    costs = {"fee": 0.001425, "tax": tax_rate(symbol), "stop": 0.08}
    if n < MIN_BARS:
        raise RuntimeError(f"{symbol} 只有 {n} 筆資料（至少需要 {MIN_BARS} 筆）")

    # 還原價（含除權息）供回測使用；顯示用原始價，與看盤軟體一致
    factor = (df["adj"] / df["close"]).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    df["bt_open"] = df["open"] * factor
    df["bt_close"] = df["adj"]

    df = S.add_indicators(df)
    df = S.add_vsa(df)

    ema_bars = int(df["ema200"].notna().sum())
    notes = []
    if ema_bars >= EMA_OK_BARS:
        start_idx = int(df["ema200"].notna().values.argmax())
    else:
        start_idx = 29                       # 量能均線 30 日起算
        notes.append(
            f"這檔只有 {n} 個交易日的資料（約 {n / 245:.1f} 年），EMA200 只有 {ema_bars} 筆可用，"
            "「多頭回檔」策略幾乎不會出現訊號，各策略的回測樣本也極少，績效數字參考價值很低。")

    fmt = lambda d: d.strftime("%Y-%m-%d")
    candles = [{"time": fmt(d), "open": num(r.open), "high": num(r.high),
                "low": num(r.low), "close": num(r.close)} for d, r in df.iterrows()]
    volume = [{"time": fmt(d), "value": int(r.volume),
               "up": bool(r.close >= r.open)} for d, r in df.iterrows()]

    vsa = []
    for key in S.VSA_LABELS:
        col = f"vsa_{key}"
        vsa += [{"time": fmt(d), "kind": key} for d in df.index[df[col]]]

    gaps = [{**g, "time": fmt(g["time"])} for g in S.find_unfilled_gaps(df)]

    strategies = {}
    for key, meta in S.STRATEGIES.items():
        entry, exit_ = S.strategy_signals(df, key)
        stats, trades, eq, bh = S.backtest(df, entry, exit_, fee=costs["fee"], tax=costs["tax"],
                                           stop=costs["stop"], start_idx=start_idx)
        strategies[key] = {
            **meta,
            "stats": stats,
            "trades": [{k: v for k, v in t.items() if k not in ("entry_sig", "exit_sig")} for t in trades[-30:]],
            "equity": [{"time": fmt(d), "value": num(v)} for d, v in eq.items()],
            "buyhold": [{"time": fmt(d), "value": num(v)} for d, v in bh.items()],
            # 圖上只標「實際成交」的買賣（標在訊號日；成交在隔天開盤）
            "markers": (
                [{"time": t["entry_sig"], "side": "buy"} for t in trades]
                + [{"time": t["exit_sig"], "side": "sell"} for t in trades if t["exit_sig"]]
            ),
        }

    last, prev = df.iloc[-1], df.iloc[-2]
    return {
        "symbol": symbol, "name": name, "demo": demo,
        "updated": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
        "last": {"date": fmt(df.index[-1]), "close": num(last.close),
                 "change": num(last.close - prev.close),
                 "pct": num((last.close / prev.close - 1) * 100)},
        "backtest_start": fmt(df.index[start_idx]),
        "bars": n, "notes": notes,
        "costs": costs,
        "candles": candles, "volume": volume,
        "volma": series_points(df, "vol_ma30"),
        "lines": {k: series_points(df, k) for k in ("ma5", "ma20", "ma60", "ema200", "bb_up", "bb_mid", "bb_dn")},
        "vsa": vsa, "gaps": gaps, "strategies": strategies,
    }


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
            data = build_one(symbol, name, df, args.demo)
        except Exception as e:               # 單一檔失敗不影響其他檔
            msg = str(e).replace("\n", " ")[:300]
            failed.append((symbol, msg))
            print(f"::warning title=更新失敗 {symbol}::{msg}")
            prev = old.get(symbol)
            if prev and (OUT / prev["file"]).exists():
                index.append({**prev, "name": name, "stale": True, "error": msg})
                print(f"[沿用舊資料] {symbol} {name}  收盤日 {prev.get('date')}")
            else:
                print(f"[失敗且無舊資料] {symbol} {name}")
            continue

        fname = symbol.replace("^", "_").replace("&", "_").replace("=", "_") + ".json"
        (OUT / fname).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        index.append({"symbol": symbol, "name": name, "file": fname, "stale": False, **data["last"]})
        extra = f"（{symbol} 查無資料，改用 {used}）" if used != symbol else ""
        print(f"[完成] {symbol} {name}  最新收盤日 {data['last']['date']}  收盤 {data['last']['close']}  共 {data['bars']} 筆 {extra}")
        last_d = datetime.strptime(data["last"]["date"], "%Y-%m-%d").date()
        if not args.demo and last_d < expected:
            print(f"::warning title=Yahoo 尚無最新資料 {symbol}::最新只到 {last_d}，依日期應已有 {expected} 的收盤（若剛好休市可忽略）")
        age = (today - last_d).days
        if age > 5 and not args.demo:
            print(f"::warning title=資料偏舊 {symbol}::最新資料是 {data['last']['date']}，距今 {age} 天（連假屬正常）")

    keep = {i["file"] for i in index} | {"index.json"}
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
