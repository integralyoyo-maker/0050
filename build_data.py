"""抓取股價 → 計算指標/訊號/回測 → 輸出 docs/data/*.json 給網頁讀取。

用法：
  python build_data.py                 # 讀 watchlist.txt，抓 Yahoo Finance 資料
  python build_data.py --demo          # 產生「假資料」測試網頁（不連網，數字沒有任何意義）
  python build_data.py --period 5y     # 抓多久的資料（預設 5y，EMA200 需要至少一年以上）
"""
import argparse
import json
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import signals as S

ROOT = Path(__file__).parent
OUT = ROOT / "docs" / "data"
TZ = timezone(timedelta(hours=8))


def read_watchlist(path: Path):
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        items.append((parts[0], parts[1] if len(parts) > 1 else parts[0]))
    return items


def fetch_yahoo(symbol: str, period: str) -> pd.DataFrame:
    import time
    import yfinance as yf
    raw = None
    for attempt in range(3):  # Yahoo 偶爾會限流或暫時失敗，重試幾次
        try:
            raw = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=False)
        except Exception as e:
            print(f"[重試 {attempt + 1}/3] {symbol}: {e}", file=sys.stderr)
            raw = None
        if raw is not None and not raw.empty:
            break
        time.sleep(3 * (attempt + 1))
    if raw is None or raw.empty:
        raise RuntimeError(f"Yahoo Finance 沒有回傳 {symbol} 的資料（可能是網路連不上，或代號錯誤；上櫃股票要用 .TWO）")
    raw.index = pd.to_datetime(raw.index).tz_localize(None).normalize()
    df = pd.DataFrame({
        "open": raw["Open"], "high": raw["High"], "low": raw["Low"], "close": raw["Close"],
        "volume": raw["Volume"].fillna(0), "adj": raw["Adj Close"],
    }).dropna(subset=["open", "high", "low", "close"])
    return df[~df.index.duplicated(keep="last")]


def make_demo(symbol: str, days: int = 1300) -> pd.DataFrame:
    """隨機漫步假資料，只用來測試網頁與程式流程。"""
    import zlib
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


def build_one(symbol: str, name: str, df: pd.DataFrame, demo: bool) -> dict:
    df = df.copy()
    # 還原價（含除權息）供回測使用；顯示用原始價，與看盤軟體一致
    factor = (df["adj"] / df["close"]).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    df["bt_open"] = df["open"] * factor
    df["bt_close"] = df["adj"]

    df = S.add_indicators(df)
    df = S.add_vsa(df)

    start_idx = int(df["ema200"].notna().values.argmax()) if df["ema200"].notna().any() else 0
    if df["ema200"].notna().sum() < 60:
        raise RuntimeError(f"{symbol} 資料太短（{len(df)} 筆），EMA200 與回測不可靠")

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
        stats, trades, eq, bh = S.backtest(df, entry, exit_, start_idx=start_idx)
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
        "costs": {"fee": 0.001425, "tax": 0.003, "stop": 0.08},
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
    for old in OUT.glob("*.json"):
        old.unlink()

    index, failed = [], []
    for symbol, name in read_watchlist(Path(args.watchlist)):
        try:
            df = make_demo(symbol) if args.demo else fetch_yahoo(symbol, args.period)
            data = build_one(symbol, name, df, args.demo)
        except Exception as e:  # 單一檔失敗不影響其他檔
            failed.append((symbol, str(e)))
            print(f"[失敗] {symbol}: {e}", file=sys.stderr)
            continue
        fname = symbol.replace("^", "_").replace("&", "_").replace("=", "_") + ".json"
        (OUT / fname).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        index.append({"symbol": symbol, "name": name, "file": fname, **data["last"]})
        print(f"[完成] {symbol} {name}  {data['last']['date']}  收盤 {data['last']['close']}")

    (OUT / "index.json").write_text(
        json.dumps({"demo": args.demo, "items": index}, ensure_ascii=False, indent=1), encoding="utf-8")
    if failed and not index:
        sys.exit("全部標的都失敗，請檢查網路或代號。")


if __name__ == "__main__":
    main()
