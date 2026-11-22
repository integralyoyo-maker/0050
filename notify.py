"""讀 docs/data 的最新日線訊號，透過 LINE Messaging API 推播給自己。

用法：
  python notify.py            # 有新訊號才推播（需要環境變數 LINE_CHANNEL_ACCESS_TOKEN、LINE_USER_ID）
  python notify.py --dry-run  # 只印出訊息，不送、不記錄
  python notify.py --test     # 送一則測試訊息，確認 LINE 設定正確

規則（全部取「最新一根日 K」當天出現的訊號；同一檔同一天同一訊號只通知一次）：
  買入提示：反彈試單、順勢重進、VSA 吸籌／強需求、任一策略出現買進點
  賣出提示：回檔調節、順勢放空、VSA 出貨、任一策略出現賣出點
這些是技術訊號，不是投資建議。
"""
import argparse, json, os, sys, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "docs" / "data"
STATE = ROOT / "notify_state.json"
SITE = os.environ.get("SITE_URL", "https://integralyoyo-maker.github.io/0050/")

BUY_E = {"bounce_probe": "反彈試單", "trend_reentry": "順勢重進"}
SELL_E = {"pullback_sell": "回檔調節", "trend_short": "順勢放空"}
BUY_V = {"absorb": "VSA吸籌", "strong_demand": "VSA強需求"}
SELL_V = {"distribute": "VSA出貨"}


def collect():
    idx = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
    out = []
    for it in idx["items"]:
        try:
            d = json.loads((DATA / it["file"]).read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"略過 {it['symbol']}：{e}")
            continue
        if d.get("demo"):
            continue
        day = d["candles"][-1]["time"]
        buy, sell = [], []
        for s in d.get("esig", []):
            if s["time"] == day:
                if s["kind"] in BUY_E: buy.append(BUY_E[s["kind"]])
                if s["kind"] in SELL_E: sell.append(SELL_E[s["kind"]])
        for s in d.get("vsa", []):
            if s["time"] == day:
                if s["kind"] in BUY_V: buy.append(BUY_V[s["kind"]])
                if s["kind"] in SELL_V: sell.append(SELL_V[s["kind"]])
        for k, st in (d.get("strategies") or {}).items():
            for m in st["markers"]:
                if m["time"] == day:
                    (buy if m["side"] == "buy" else sell).append("策略：" + st["name"])
        out.append(dict(symbol=it["symbol"], name=it["name"], day=day, close=it["close"], pct=it["pct"],
                        buy=buy, sell=sell, stale=bool(it.get("stale"))))
    return out


def build_message(items, state, mark):
    lines = {"buy": [], "sell": []}
    for it in items:
        for side in ("buy", "sell"):
            new = []
            for label in it[side]:
                key = f"{it['symbol']}|{it['day']}|{side}|{label}"
                if key not in state:
                    new.append(label)
                    if mark: state[key] = 1
            if new:
                sym = it["symbol"].split(".")[0]
                warn = "（舊資料）" if it["stale"] else ""
                lines[side].append(f"• {sym} {it['name']}　收 {it['close']:.2f}（{it['pct']:+.2f}%，{it['day']}）{warn}\n   {'、'.join(new)}")
    if not lines["buy"] and not lines["sell"]:
        return None
    parts = ["📊 台股訊號通知"]
    if lines["buy"]: parts.append("🔴 可留意買入\n" + "\n".join(lines["buy"]))
    if lines["sell"]: parts.append("🟢 可留意賣出\n" + "\n".join(lines["sell"]))
    parts.append("以上是技術訊號，不是投資建議；訊號日的隔天才是實際可成交日。\n" + SITE)
    return "\n\n".join(parts)


def push(text):
    token, uid = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"), os.environ.get("LINE_USER_ID")
    if not token or not uid:
        print("::warning::未設定 LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID，沒有送出 LINE 通知")
        return False
    chunks = [text[i:i + 4800] for i in range(0, len(text), 4800)]
    for c in chunks:
        body = json.dumps({"to": uid, "messages": [{"type": "text", "text": c}]}).encode()
        req = urllib.request.Request("https://api.line.me/v2/bot/message/push", data=body,
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        try:
            urllib.request.urlopen(req, timeout=20).read()
        except urllib.error.HTTPError as e:
            print(f"::error::LINE 回應 {e.code}：{e.read().decode(errors='replace')[:300]}")
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    if a.test:
        sys.exit(0 if push("✅ 台股訊號網站的 LINE 通知設定成功。\n" + SITE) else 1)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    msg = build_message(collect(), state, mark=not a.dry_run)
    if not msg:
        print("今天沒有新的買賣訊號，不通知。"); return
    print(msg)
    if a.dry_run: return
    if push(msg):
        # 只保留最近 400 筆，避免檔案無限變大
        keys = list(state)[-400:]
        STATE.write_text(json.dumps({k: 1 for k in keys}, ensure_ascii=False, indent=0), encoding="utf-8")
        print("已送出。")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
