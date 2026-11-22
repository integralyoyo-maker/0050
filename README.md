# 台股訊號與回測網站

K 線圖（MA、布林、EMA200）＋ VSA 量價訊號 ＋ 未補缺口 ＋ 三種買賣策略的歷史回測。
資料每天用 Python 抓一次、算好存成 JSON，網頁只負責顯示，所以可以免費放在 GitHub Pages。

## 1. 安裝與產生資料

```bash
pip install -r requirements.txt
python build_data.py            # 讀 watchlist.txt，從 Yahoo Finance 抓 5 年日線，輸出 docs/data/
```

- 想看版面但不想連網：`python build_data.py --demo`（假資料，網頁上會有黃色警告，數字毫無意義）。
- 改追蹤標的：編輯 `watchlist.txt`，每行 `Yahoo代號,顯示名稱`。上市 `.TW`、上櫃 `.TWO`、加權指數 `^TWII`。

## 2. 在本機看網頁

```bash
python -m http.server -d docs 8000
```

瀏覽器開 http://localhost:8000 。（不能直接雙擊 index.html，瀏覽器會擋讀取 JSON。）

## 3. 放上網並全自動更新（GitHub Pages + GitHub Actions，免費）

設定好之後，**不需要開電腦**：GitHub 的雲端伺服器每個交易日 15:00（台北）自動抓資料、重算、重新發布網站，你只要用 iPhone 打開網址。

一次性設定：

1. 註冊 GitHub 帳號，建立一個 **Public** 儲存庫（免費帳號的 Pages 需要公開儲存庫；網站與程式碼任何人知道網址都看得到，所以不要把任何密碼或金鑰放進程式裡）。
2. 把本資料夾的**全部內容（包含隱藏資料夾 `.github`）**上傳到儲存庫的 `main` 分支。
   - 不用先跑 `build_data.py`，資料會由雲端產生。
   - 用電腦最簡單（網頁上 Add file → Upload files，整個資料夾拖進去即可）。
   - 只有 iPhone 時，Safari 上傳多半不會保留資料夾結構（我沒有實測），建議用 iOS 的 Git 用戶端 App（例如 Working Copy，哪些功能要付費我不確定）來推送。
3. 儲存庫 Settings → Pages → **Build and deployment → Source 選 GitHub Actions**。
4. 到 Actions 分頁，選「更新資料並部署網站」→ Run workflow，手動跑第一次。成功後網址是 `https://你的帳號.github.io/儲存庫名稱/`。
5. iPhone Safari 開網址 → 分享按鈕 → **加入主畫面**，之後像 App 一樣點開。

注意事項：

- **Yahoo 對雲端 IP 可能限流**。我無法在這邊測試。如果 Actions 的紀錄（Actions → 點進該次執行 → 「抓資料、算訊號、回測」步驟）顯示抓不到資料，請回報錯誤訊息，備案是改用證交所官方資料。
- 排程失敗時，網站會保持上一次成功的版本，不會變成空白。若只有部分標的失敗，那幾檔會暫時從選單消失，錯誤會印在紀錄裡。
- GitHub 對公開儲存庫的規定：約 60 天沒有任何儲存庫活動，排程會被自動停用（以 GitHub 官方文件為準），到 Actions 頁面重新啟用即可。
- 排程不一定準時。GitHub 官方文件說明：高負載時 `schedule` 可能延遲，排隊中的工作甚至可能被丟棄，**整點是高負載時段**，建議錯開。所以流程檔把時間設在台北 16:23，並加一個 17:47 的備援排程。

## 3.5 「資料好像沒更新」怎麼查

1. 看網頁：頂端會寫「收盤日」與「網站資料產生於」。
   - 收盤日是上一個交易日、而且現在還沒開盤或才剛收盤 → 正常。
   - 網頁自己會判斷：台北 18:00 後或隔天，收盤日卻還是舊的，會跳出黃色警示（遇連假可忽略）。
   - 某檔抓失敗時，選單會標 ⚠舊資料，並顯示原因。
2. 看 GitHub：儲存庫 → Actions 分頁。
   - 完全沒有「schedule」觸發的紀錄 → 排程沒跑（被延遲/丟棄，或被停用）。
   - 有紀錄但紅色 ✗ → 點進去看哪個步驟失敗，最常見是 Yahoo 限流。
   - 綠色 ✓ 但資料還是舊的 → 把該次「Run data builder」步驟的輸出貼出來看。
3. 手動補跑：Actions → 該流程 → Run workflow。

## 4. 檔案說明

| 檔案 | 作用 |
|---|---|
| `build_data.py` | 抓資料、呼叫 signals.py、輸出 JSON |
| `signals.py` | 指標、VSA 訊號、缺口、策略、回測（要改規則就改這裡） |
| `docs/index.html` `app.js` `style.css` | 網頁（K 線圖用 Lightweight Charts 4.2.0，已內建離線版） |
| `watchlist.txt` | 追蹤清單 |
| `.github/workflows/update.yml` | 雲端排程：抓資料並部署網站 |

## 5. 三種策略（皆為做多、全倉、一次一筆）

- **布林通道均值回歸**：收盤由下軌之下站回下軌之上買；回到中線以上賣。
- **多頭回檔**：收盤在 EMA200 之上，RSI(14) 由 35 以下回升到 35 以上買；RSI>65 或跌破 EMA200 賣。
- **VSA 吸籌／出貨**：出現「吸籌」或「強烈需求」買；出現「出貨」賣。

回測規則：訊號日收盤判斷、**隔天開盤成交**；手續費 0.1425%（買賣各一次）、賣出證交稅 0.3%（ETF 為 0.1%，請在 `signals.py` 的 `backtest()` 調整）、
持有中收盤跌破進場價 8% 隔天開盤停損；計算用還原價（含除權息）。

## 6. 重要限制

- 回測**沒有計入**：滑價、漲跌停鎖死買不到/賣不掉、融資利息、零股/整股差異、實際手續費折讓。
- VSA 訊號是依概念寫的簡化定義（見 `add_vsa()`），不是任何商業軟體的原始公式；門檻（1.5 倍量、2 倍量等）可自行調整。
- 交易筆數太少時，勝率與報酬沒有統計意義；網頁會自動提醒。
- 即使回測漂亮，也可能只是對過去資料過度配適（調參數調到剛好好看）。建議把資料切成「前段調參、後段驗證」。
- 本工具僅供學習，不構成投資建議。

## 授權提醒

圖表使用 TradingView Lightweight Charts（Apache-2.0），圖上的 TradingView 標誌請保留。

## 新增功能（EMA 趨勢與查詢）
- 週期切換：小時／日／週／月（小時線 Yahoo 只提供約一年）。
- 「EMA 趨勢」模式：EMA 5/10/30/60/200、DMI(14) 副圖與盤整／過渡／趨勢背景色、四種訊號（順勢重進、回檔調節、順勢放空、反彈試單）。定義寫在 `signals.py` 的 `add_ema_trend`，是依常見概念自訂，並非他人程式的原始公式。
- 查詢任一股票：網頁直接向 FinMind 取日線與三大法人買賣超，在瀏覽器內計算指標（與 Python 結果已比對一致）；不含 VSA、缺口、回測。

## 自選清單與 LINE 通知
- 網頁上「管理我的自選清單」：貼上 GitHub 細粒度權杖（只授權本 repo 的 Contents 讀寫）後，可新增／移除，內容會寫入 `watchlist.txt`，推送後 Actions 自動重建。
- `notify.py`：每次更新資料後，對清單內每檔的「最新日 K」檢查買入／賣出訊號並用 LINE Messaging API 推播給自己（同一訊號只通知一次，記錄在 `notify_state.json`）。
- 需要的 GitHub Secrets：`LINE_CHANNEL_ACCESS_TOKEN`、`LINE_USER_ID`。手動執行 workflow 並勾選 `line_test` 可送測試訊息。
