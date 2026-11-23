"""盤中報價：抓 docs/data/index.json 內每檔的最新日 K（含今日未收盤的那根），輸出 quotes.json。
由 .github/workflows/quotes.yml 每 5 分鐘執行，結果推到 quotes 分支，網頁直接讀取。
Yahoo 台股報價通常有約 20 分鐘延遲。
用法：python quotes.py 輸出資料夾
"""
import json, sys, datetime as dt
from pathlib import Path
import yfinance as yf

ROOT = Path(__file__).resolve().parent


def main(out: Path):
    idx = json.loads((ROOT / "docs" / "data" / "index.json").read_text(encoding="utf-8"))
    items, fails = {}, []
    for it in idx["items"]:
        sym = it["symbol"]
        try:
            df = yf.Ticker(sym).history(period="5d", interval="1d", auto_adjust=False)
            df = df.dropna(subset=["Close"])
            if len(df) < 2:
                raise ValueError("資料不足")
            a, b = df.iloc[-1], df.iloc[-2]
            ts = df.index[-1]
            items[sym] = dict(
                date=ts.strftime("%Y-%m-%d"), open=round(float(a.Open), 4), high=round(float(a.High), 4),
                low=round(float(a.Low), 4), close=round(float(a.Close), 4), volume=int(a.Volume),
                prev=round(float(b.Close), 4),
                change=round(float(a.Close - b.Close), 4), pct=round(float(a.Close / b.Close - 1) * 100, 4),
            )
        except Exception as e:  # noqa: BLE001
            fails.append(f"{sym}: {e}")
    if not items:
        print("::error::所有標的報價都抓不到：" + "; ".join(fails)); sys.exit(1)
    tz = dt.timezone(dt.timedelta(hours=8))
    now = dt.datetime.now(tz)
    out.mkdir(parents=True, exist_ok=True)
    (out / "quotes.json").write_text(json.dumps(dict(updated=now.strftime("%Y-%m-%d %H:%M"), items=items),
                                                ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for f in fails:
        print("::warning::" + f)
    print(f"完成 {len(items)} 檔，失敗 {len(fails)} 檔")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "quotes_out"))
