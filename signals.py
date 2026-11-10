"""指標、VSA 量價訊號、未補缺口、策略與回測。

所有訊號都只用「當天收盤時已知」的資料計算；
回測一律「訊號日收盤判斷 → 隔天開盤成交」，避免偷看未來。
"""
import numpy as np
import pandas as pd

# ---------------------------------------------------------------- 指標
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    for n in (5, 20, 60):
        df[f"ma{n}"] = c.rolling(n).mean()
    df["ema200"] = c.ewm(span=200, adjust=False, min_periods=200).mean()

    mid = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    df["bb_mid"], df["bb_up"], df["bb_dn"] = mid, mid + 2 * sd, mid - 2 * sd

    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    al = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    df["rsi"] = 100 - 100 / (1 + ag / al)

    df["vol_ma30"] = df["volume"].rolling(30).mean()
    df["spread"] = df["high"] - df["low"]
    df["spread_ma20"] = df["spread"].rolling(20).mean()
    return df


# ---------------------------------------------------------------- VSA（簡化版）
VSA_LABELS = {
    "absorb": "吸籌",
    "distribute": "出貨",
    "strong_demand": "強烈需求",
    "no_supply": "無供給",
    "no_demand": "無需求",
}


def add_vsa(df: pd.DataFrame) -> pd.DataFrame:
    """這是我依 VSA 概念寫的簡化定義，不是任何網站的原始公式。"""
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    rng = (h - l).replace(0, np.nan)
    pos = (c - l) / rng                       # 收盤在當日區間的位置 0~1
    has_vol = df["vol_ma30"] > 0
    vol_hi = has_vol & (v > 1.5 * df["vol_ma30"])
    vol_vhi = has_vol & (v > 2.0 * df["vol_ma30"])
    down, up = c < c.shift(), c > c.shift()
    narrow = df["spread"] < 0.8 * df["spread_ma20"]
    lowvol = (v < v.shift(1)) & (v < v.shift(2))
    near_low = l <= df["bb_dn"] * 1.01
    near_high = h >= df["bb_up"] * 0.99

    # 吸籌：低檔爆量，下跌但收在區間上半
    df["vsa_absorb"] = vol_hi & down & (pos >= 0.5) & near_low
    # 出貨：高檔爆量，上漲但收在區間下半
    df["vsa_distribute"] = vol_hi & up & (pos <= 0.5) & near_high
    # 強烈需求：超大量、寬幅上漲、收在區間上緣
    df["vsa_strong_demand"] = vol_vhi & up & (pos >= 0.7) & (df["spread"] > df["spread_ma20"])
    # 無供給：下跌、窄幅、量縮（賣壓枯竭）
    df["vsa_no_supply"] = down & narrow & lowvol & has_vol
    # 無需求：上漲、窄幅、量縮（買盤乏力）
    df["vsa_no_demand"] = up & narrow & lowvol & has_vol
    for k in [c for c in df.columns if c.startswith("vsa_")]:
        df[k] = df[k].fillna(False).astype(bool)
    return df


# ---------------------------------------------------------------- 未補缺口
def find_unfilled_gaps(df: pd.DataFrame, keep: int = 10):
    """向上缺口：今低 > 昨高；向下缺口：今高 < 昨低。之後價格回到缺口另一端才算「已補」。"""
    h, l = df["high"].values, df["low"].values
    idx = df.index
    out = []
    for i in range(1, len(df)):
        if l[i] > h[i - 1]:
            bottom, top = h[i - 1], l[i]
            if not np.any(l[i + 1:] <= bottom):
                out.append({"time": idx[i], "type": "up", "top": float(top), "bottom": float(bottom)})
        elif h[i] < l[i - 1]:
            top, bottom = l[i - 1], h[i]
            if not np.any(h[i + 1:] >= top):
                out.append({"time": idx[i], "type": "down", "top": float(top), "bottom": float(bottom)})
    return out[-keep:]


# ---------------------------------------------------------------- 策略
def _cross_up(a, b):
    return (a.shift() <= b.shift()) & (a > b)


STRATEGIES = {
    "boll": {
        "name": "布林通道均值回歸",
        "desc": "買：收盤由布林下軌之下站回下軌之上。賣：收盤回到中線以上，或虧損達停損。屬於逆勢抄底，趨勢下跌時容易連續停損。",
    },
    "trend_pullback": {
        "name": "多頭回檔（EMA200 + RSI）",
        "desc": "買：收盤在 EMA200 之上，且 RSI(14) 由 35 以下回升到 35 以上。賣：RSI 升破 65、收盤跌破 EMA200，或虧損達停損。只做長期多頭裡的回檔。",
    },
    "vsa": {
        "name": "VSA 吸籌／出貨",
        "desc": "買：出現「吸籌」或「強烈需求」。賣：出現「出貨」，或虧損達停損。訊號稀少，樣本數通常偏低，統計參考價值有限。",
    },
}


def strategy_signals(df: pd.DataFrame, key: str):
    """回傳 (entry, exit) 兩個布林 Series；停損在回測引擎處理。"""
    c = df["close"]
    if key == "boll":
        entry = (c.shift() < df["bb_dn"].shift()) & (c > df["bb_dn"])
        exit_ = c >= df["bb_mid"]
    elif key == "trend_pullback":
        entry = (c > df["ema200"]) & (df["rsi"].shift() < 35) & (df["rsi"] >= 35)
        exit_ = (df["rsi"] > 65) | (c < df["ema200"])
    elif key == "vsa":
        entry = df["vsa_absorb"] | df["vsa_strong_demand"]
        exit_ = df["vsa_distribute"]
    else:
        raise KeyError(key)
    return entry.fillna(False), exit_.fillna(False)


# ---------------------------------------------------------------- 回測
def backtest(df: pd.DataFrame, entry: pd.Series, exit_: pd.Series,
             fee: float = 0.001425, tax: float = 0.003, stop: float = 0.08,
             start_idx: int = 0):
    """做多、全倉、一次一筆。

    - 訊號日 i 收盤判斷，i+1 開盤成交。
    - 買進手續費 fee；賣出手續費 fee + 證交稅 tax（股票 0.3%；ETF 0.1%，請自行調整）。
    - 持有中若收盤 <= 進場價*(1-stop)，隔天開盤出場。
    - 用還原價（bt_open / bt_close）計算，已含除權息影響。
    """
    o, c = df["bt_open"].values, df["bt_close"].values
    dates = df.index
    n = len(df)
    en, ex = entry.values, exit_.values

    cash, shares, entry_px, entry_i = 1.0, 0.0, 0.0, -1
    pending_buy = pending_sell = False
    equity = np.full(n, np.nan)
    trades = []
    held_days = 0

    for i in range(start_idx, n):
        if pending_buy and shares == 0:
            shares = cash / (o[i] * (1 + fee))
            cash, entry_px, entry_i = 0.0, o[i], i
        if pending_sell and shares > 0:
            cash = shares * o[i] * (1 - fee - tax)
            trades.append({
                "entry_date": str(dates[entry_i].date()), "exit_date": str(dates[i].date()),
                "entry": float(entry_px), "exit": float(o[i]),
                "ret": float(o[i] * (1 - fee - tax) / (entry_px * (1 + fee)) - 1),
                "bars": int(i - entry_i), "open": False,
                "entry_sig": str(dates[max(entry_i - 1, 0)].date()),
                "exit_sig": str(dates[max(i - 1, 0)].date()),
            })
            shares = 0.0
        pending_buy = pending_sell = False

        if shares > 0:
            held_days += 1
            if c[i] <= entry_px * (1 - stop) or ex[i]:
                pending_sell = True
        elif en[i] and i + 1 < n:
            pending_buy = True

        equity[i] = cash if shares == 0 else shares * c[i]

    if shares > 0:  # 尚未出場的持倉
        trades.append({
            "entry_date": str(dates[entry_i].date()), "exit_date": None,
            "entry": float(entry_px), "exit": float(c[-1]),
            "ret": float(c[-1] / entry_px - 1), "bars": int(n - 1 - entry_i), "open": True,
            "entry_sig": str(dates[max(entry_i - 1, 0)].date()), "exit_sig": None,
        })

    eq = pd.Series(equity, index=dates).dropna()
    closed = [t for t in trades if not t["open"]]
    rets = np.array([t["ret"] for t in closed]) if closed else np.array([])
    wins, losses = rets[rets > 0], rets[rets <= 0]
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9) if len(eq) > 1 else 1e-9
    total = float(eq.iloc[-1] / eq.iloc[0] - 1) if len(eq) else 0.0
    dd = float((eq / eq.cummax() - 1).min()) if len(eq) else 0.0
    bh_series = pd.Series(c[start_idx:] / c[start_idx], index=dates[start_idx:])
    bh_dd = float((bh_series / bh_series.cummax() - 1).min())

    stats = {
        "trades": len(closed),
        "win_rate": float((rets > 0).mean()) if len(rets) else None,
        "avg_ret": float(rets.mean()) if len(rets) else None,
        "avg_win": float(wins.mean()) if len(wins) else None,
        "avg_loss": float(losses.mean()) if len(losses) else None,
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else None,
        "total_return": total,
        "cagr": float((1 + total) ** (1 / years) - 1) if total > -1 else -1.0,
        "max_drawdown": dd,
        "exposure": float(held_days / max(len(eq), 1)),
        "buyhold_return": float(bh_series.iloc[-1] - 1),
        "buyhold_max_drawdown": bh_dd,
        "period": [str(eq.index[0].date()), str(eq.index[-1].date())] if len(eq) else None,
        "open_position": any(t["open"] for t in trades),
    }
    return stats, trades, eq, bh_series
