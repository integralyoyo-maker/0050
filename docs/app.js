/* 台股訊號與回測：讀取 data/*.json 並用 Lightweight Charts 繪圖 */
(() => {
  const UP = '#ef5350', DOWN = '#26a69a';
  const DMI_H = 170;
  const $ = (id) => document.getElementById(id);

  const VSA_MAIN = {
    absorb:        { text: '吸籌',     color: '#ffd43b', shape: 'arrowUp',   pos: 'belowBar' },
    distribute:    { text: '出貨',     color: '#69db7c', shape: 'arrowDown', pos: 'aboveBar' },
    strong_demand: { text: '強需求',   color: '#ff6b6b', shape: 'circle',    pos: 'belowBar' },
  };
  const VSA_SUB = {
    no_supply:     { text: '無供給',   color: '#4dd0e1', shape: 'circle',    pos: 'belowBar' },
    no_demand:     { text: '無需求',   color: '#da77f2', shape: 'circle',    pos: 'aboveBar' },
  };
  // EMA 趨勢訊號：紅色向上＝偏多進場，綠色向下＝減碼/放空（台股慣例：紅漲綠跌）
  const ESIG = {
    trend_reentry: { text: '順勢重進', color: UP,        shape: 'arrowUp',   pos: 'belowBar' },
    bounce_probe:  { text: '反彈試單', color: '#ff9f43', shape: 'arrowUp',   pos: 'belowBar' },
    pullback_sell: { text: '回檔調節', color: DOWN,      shape: 'arrowDown', pos: 'aboveBar' },
    trend_short:   { text: '順勢放空', color: DOWN,      shape: 'arrowDown', pos: 'aboveBar' },
  };
  const REGIME = { r: ['盤整市', 'r'], x: ['過渡區', 'x'], t: ['趨勢市', 't'] };
  const BG = { r: 'rgba(59,130,246,.30)', x: 'rgba(168,85,247,.30)', t: 'rgba(240,160,60,.28)' };
  const WINDOW = { H: 150, D: 180, W: 120, M: 60 };   // 預設顯示最近幾根 K 棒
  const MODES = {
    std: { ma: true,  boll: true,  ema200: true,  vsa: true,  vsa2: false, gap: true,  strat: true,  emas: false, esig: false, dmi: false },
    ema: { ma: false, boll: false, ema200: false, vsa: false, vsa2: false, gap: false, strat: false, emas: true,  esig: true,  dmi: true },
  };

  let chart = null, candle, volSeries, volMaSeries, lineSeries = {};
  let dmiChart = null, bgS, adxS, pdiS, mdiS;
  let eqChart, eqS, eqB;
  let DATA = null, INDEX = null, ITEM = null, TF = 'D', loadSeq = 0;

  const fmt = (x, d = 2) => x == null ? '—' : Number(x).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  const pct = (x, d = 1) => x == null ? '—' : (x * 100).toFixed(d) + '%';
  const cls = (x) => x > 0 ? 'up' : x < 0 ? 'down' : 'flat';
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  // 圖表的時間可能是 'YYYY-MM-DD'、秒數（小時線，已換成台北時間）或 {year,month,day}
  function tstr(t) {
    if (t == null) return '';
    if (typeof t === 'string') return t;
    if (typeof t === 'number') return new Date(t * 1000).toISOString().slice(0, 16).replace('T', ' ');
    return `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}`;
  }

  function chartOptions(height) {
    return {
      height,
      layout: { background: { color: 'transparent' }, textColor: '#aab0bd', fontFamily: 'inherit' },
      grid: { vertLines: { color: '#232632' }, horzLines: { color: '#232632' } },
      rightPriceScale: { borderColor: '#2a2d38', minimumWidth: 64 },
      timeScale: { borderColor: '#2a2d38', rightOffset: 4 },
      crosshair: { mode: 0 },
    };
  }

  function makeMain(intraday) {
    const el = $('chart');
    chart = LightweightCharts.createChart(el, { ...chartOptions(el.clientHeight), width: el.clientWidth });
    chart.applyOptions({ timeScale: { timeVisible: intraday, secondsVisible: false } });
    candle = chart.addCandlestickSeries({
      upColor: UP, downColor: DOWN, wickUpColor: UP, wickDownColor: DOWN, borderVisible: false,
    });
    candle.priceScale().applyOptions({ scaleMargins: { top: 0.05, bottom: 0.27 } });

    volSeries = chart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'vol', lastValueVisible: false, priceLineVisible: false });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
    volMaSeries = chart.addLineSeries({ color: '#c9ccd6', lineWidth: 1, lineStyle: 2, priceScaleId: 'vol', lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });

    const L = (color, width = 1, style = 0) => chart.addLineSeries({
      color, lineWidth: width, lineStyle: style, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
    });
    lineSeries = {
      ma5: L('#f4c542'), ma20: L('#5aa9ff'), ma60: L('#b57bff'),
      bb_up: L('#8a90a0', 1, 2), bb_mid: L('#5aa9ff', 1), bb_dn: L('#8a90a0', 1, 2),
      ema5: L('#6ea8fe'), ema10: L('#ff9f43'), ema30: L('#b57bff'), ema60: L('#4cc38a'),
      ema200: L('#ffd43b', 2),
    };

    chart.subscribeCrosshairMove(updateLegend);
    chart.timeScale().subscribeVisibleLogicalRangeChange(syncDmi);
  }

  function makeDmi() {
    const el = $('dmi');
    dmiChart = LightweightCharts.createChart(el, {
      ...chartOptions(DMI_H),
      width: $('chart').clientWidth,
      handleScroll: false, handleScale: false,          // 只能拖曳上面的主圖，副圖跟著動
      crosshair: { vertLine: { visible: false, labelVisible: false }, horzLine: { visible: false, labelVisible: false } },
    });
    dmiChart.applyOptions({ timeScale: { visible: false } });
    // 背景色帶：用一組高度固定為 1 的長條畫滿整個副圖
    bgS = dmiChart.addHistogramSeries({
      priceScaleId: 'bg', lastValueVisible: false, priceLineVisible: false,
      autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 1 } }),
    });
    dmiChart.priceScale('bg').applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false });
    const L = (color, width = 1) => dmiChart.addLineSeries({
      color, lineWidth: width, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
    });
    pdiS = L(UP); mdiS = L(DOWN); adxS = L('#ffd43b', 2);
    [20, 25].forEach((p) => adxS.createPriceLine({ price: p, color: '#6b7183', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '' }));
  }

  function makeEq() {
    const eqEl = $('eq');
    eqChart = LightweightCharts.createChart(eqEl, { ...chartOptions(eqEl.clientHeight), width: eqEl.clientWidth });
    const pf = { type: 'custom', minMove: 0.001, formatter: (p) => ((p - 1) * 100).toFixed(0) + '%' };
    eqB = eqChart.addLineSeries({ color: '#9aa0ae', lineWidth: 1, priceFormat: pf, priceLineVisible: false });
    eqS = eqChart.addLineSeries({ color: '#5aa9ff', lineWidth: 2, priceFormat: pf, priceLineVisible: false });
  }

  function teardown() {
    [chart, dmiChart].forEach((c) => { if (c) { try { c.remove(); } catch (_) { /* 已移除 */ } } });
    chart = dmiChart = null;
  }

  function syncDmi(range) {
    if (!range || !dmiChart) return;
    try { dmiChart.timeScale().setVisibleLogicalRange(range); } catch (_) { /* 圖表剛重建 */ }
  }

  function updateLegend(param) {
    const lg = $('legend');
    if (!DATA || !chart) return;
    let c = null, t = null;
    if (param && param.time && param.seriesData) {
      c = param.seriesData.get(candle); t = param.time;
    }
    if (!c) { const last = DATA.candles[DATA.candles.length - 1]; c = last; t = last.time; }
    const sd = param && param.seriesData;
    const v = sd && sd.get(volSeries);
    const g = (k) => { const s = sd && sd.get(lineSeries[k]); return s && s.value != null ? fmt(s.value) : null; };
    const parts = [tstr(t), `開 ${fmt(c.open)}`, `高 ${fmt(c.high)}`, `低 ${fmt(c.low)}`, `收 ${fmt(c.close)}`];
    if (v) parts.push(`量 ${Math.round(v.value / 1000).toLocaleString()} 張`);
    const tg = toggles();
    if (tg.emas) {
      [['ema5', 'E5'], ['ema10', 'E10'], ['ema30', 'E30'], ['ema60', 'E60'], ['ema200', 'E200']].forEach(([k, n]) => {
        const x = g(k); if (x) parts.push(`${n} ${x}`);
      });
    } else {
      const e = g('ema200'); if (e) parts.push(`EMA200 ${e}`);
    }
    const u = g('bb_up'), d = g('bb_dn'); if (tg.boll && u && d) parts.push(`布林 ${d} ~ ${u}`);
    lg.textContent = parts.join('　');
  }

  function toggles() {
    const o = {};
    document.querySelectorAll('#toggles input').forEach((i) => (o[i.dataset.k] = i.checked));
    return o;
  }

  function applyOverlays() {
    if (!DATA || !chart) return;
    const t = toggles();
    ['ma5', 'ma20', 'ma60'].forEach((k) => lineSeries[k].applyOptions({ visible: t.ma }));
    ['bb_up', 'bb_mid', 'bb_dn'].forEach((k) => lineSeries[k].applyOptions({ visible: t.boll }));
    ['ema5', 'ema10', 'ema30', 'ema60'].forEach((k) => lineSeries[k].applyOptions({ visible: t.emas }));
    lineSeries.ema200.applyOptions(t.emas
      ? { visible: true, color: '#e6e8ee', lineWidth: 1 }
      : { visible: t.ema200, color: '#ffd43b', lineWidth: 2 });

    const m = [];
    (DATA.vsa || []).forEach((s) => {
      const d = VSA_MAIN[s.kind] && t.vsa ? VSA_MAIN[s.kind] : VSA_SUB[s.kind] && t.vsa2 ? VSA_SUB[s.kind] : null;
      if (d) m.push({ time: s.time, position: d.pos, color: d.color, shape: d.shape, text: d.text });
    });
    if (t.gap) {
      (DATA.gaps || []).forEach((g) => m.push({
        time: g.time, position: g.type === 'up' ? 'belowBar' : 'aboveBar',
        color: '#9aa0ae', shape: 'square', text: g.type === 'up' ? '未補↑' : '未補↓',
      }));
    }
    if (t.esig) {
      (DATA.esig || []).forEach((s) => {
        const d = ESIG[s.kind];
        if (d) m.push({ time: s.time, position: d.pos, color: d.color, shape: d.shape, text: d.text });
      });
    }
    const st = DATA.strategies && DATA.strategies[$('strategy').value];
    if (t.strat && st) {
      st.markers.forEach((s) => m.push(s.side === 'buy'
        ? { time: s.time, position: 'belowBar', color: UP, shape: 'arrowUp', text: '買' }
        : { time: s.time, position: 'aboveBar', color: DOWN, shape: 'arrowDown', text: '賣' }));
    }
    m.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
    candle.setMarkers(m);

    const showDmi = !!(t.dmi && DATA.dmi);
    $('dmi-wrap').hidden = !showDmi;
    if (showDmi && dmiChart) {
      dmiChart.applyOptions({ width: $('chart').clientWidth, height: DMI_H });
      syncDmi(chart.timeScale().getVisibleLogicalRange());
    }
    updateLegend(null);
  }

  function setMode(m) {
    Object.entries(MODES[m]).forEach(([k, v]) => {
      const i = document.querySelector(`#toggles input[data-k="${k}"]`);
      if (i && !i.disabled) i.checked = v;
    });
    document.querySelectorAll('#mode button').forEach((b) => b.classList.toggle('on', b.dataset.m === m));
    applyOverlays();
  }

  function stat(k, v, s = '', c = '') {
    return `<div class="stat"><div class="k">${k}</div><div class="v ${c}">${v}</div>${s ? `<div class="s">${s}</div>` : ''}</div>`;
  }

  function renderStrategy() {
    const st = DATA.strategies[$('strategy').value];
    const s = st.stats;
    $('s-title').textContent = `策略績效：${st.name}`;
    $('s-desc').textContent = st.desc;
    const c = DATA.costs;
    $('stats').innerHTML = [
      stat('策略總報酬', pct(s.total_return), `買進持有 ${pct(s.buyhold_return)}`, cls(s.total_return)),
      stat('年化報酬', pct(s.cagr), '', cls(s.cagr)),
      stat('最大回撤', pct(s.max_drawdown), `買進持有 ${pct(s.buyhold_max_drawdown)}`, 'down'),
      stat('交易筆數', s.trades, s.open_position ? '另有 1 筆持有中' : ''),
      stat('勝率', pct(s.win_rate, 0)),
      stat('平均每筆', pct(s.avg_ret, 2), `賺 ${pct(s.avg_win, 1)} ／ 賠 ${pct(s.avg_loss, 1)}`, cls(s.avg_ret)),
      stat('獲利因子', s.profit_factor == null ? '—' : s.profit_factor.toFixed(2), '總獲利 ÷ 總虧損'),
      stat('持股時間比', pct(s.exposure, 0)),
    ].join('');

    const w = [];
    if (s.trades < 20) w.push(`交易只有 ${s.trades} 筆，樣本太少，勝率與報酬幾乎沒有統計意義。`);
    if (s.total_return < s.buyhold_return) w.push('這個策略在此期間<b>輸給單純買進持有</b>。');
    w.push(`成本設定：手續費 ${(c.fee * 100).toFixed(4)}%（買賣各一次）、賣出證交稅 ${(c.tax * 100).toFixed(1)}%、停損 ${(c.stop * 100).toFixed(0)}%。回測區間 ${s.period ? s.period[0] + ' ~ ' + s.period[1] : '—'}。`);
    const wb = $('warn'); wb.hidden = false; wb.innerHTML = w.join('<br>');

    eqS.setData(st.equity); eqB.setData(st.buyhold);
    eqChart.timeScale().fitContent();

    const tb = $('trades').querySelector('tbody');
    tb.innerHTML = st.trades.slice().reverse().map((t) =>
      `<tr><td>${t.entry_date}</td><td>${t.exit_date || '持有中'}</td><td>${fmt(t.entry)}</td><td>${fmt(t.exit)}${t.open ? '*' : ''}</td>` +
      `<td class="${cls(t.ret)}">${pct(t.ret, 2)}</td><td>${t.bars}</td></tr>`).join('') ||
      '<tr><td colspan="6" style="text-align:center;color:#8d93a3">此區間沒有交易</td></tr>';
  }

  // 策略回測只有日線；其他週期把策略相關區塊收起來
  function renderStrategySection() {
    const has = !!(DATA.strategies && Object.keys(DATA.strategies).length);
    $('card-strategy').hidden = !has;
    $('card-trades').hidden = !has;
    $('strategy').hidden = !has;
    const si = document.querySelector('#toggles input[data-k="strat"]');
    si.disabled = !has;
    si.parentElement.style.opacity = has ? '' : '.4';
    if (!has) return;
    const sel = $('strategy');
    if (!sel.options.length) {
      sel.innerHTML = Object.entries(DATA.strategies).map(([k, v]) => `<option value="${k}">${v.name}</option>`).join('');
    }
    renderStrategy();
  }

  function renderGaps() {
    $('gaps').querySelector('tbody').innerHTML = (DATA.gaps || []).slice().reverse().map((g) =>
      `<tr><td>${tstr(g.time)}</td><td class="${g.type === 'up' ? 'up' : 'down'}">${g.type === 'up' ? '向上缺口' : '向下缺口'}</td>` +
      `<td>${fmt(g.bottom)} ~ ${fmt(g.top)}</td></tr>`).join('') ||
      '<tr><td colspan="3" style="text-align:center;color:#8d93a3">目前沒有未補缺口</td></tr>';
  }

  function renderRegime() {
    const el = $('regime');
    const nw = DATA.now;
    if (!nw || !nw.state) { el.hidden = true; return; }
    const [label, key] = REGIME[nw.state];
    const bias = nw.pdi > nw.mdi ? '多方佔優' : nw.pdi < nw.mdi ? '空方佔優' : '多空持平';
    const last = (DATA.esig || [])[(DATA.esig || []).length - 1];
    el.hidden = false;
    el.innerHTML = `<span class="tag ${key}">${label}</span>ADX ${fmt(nw.adx, 1)}　+DI ${fmt(nw.pdi, 1)}　−DI ${fmt(nw.mdi, 1)}（${bias}）` +
      (last ? `<div class="sub">最近一次 EMA 趨勢訊號：<b>${ESIG[last.kind].text}</b>（${tstr(last.time)}）</div>` : '');
  }

  function renderQuote() {
    const it = ITEM;
    $('q-name').textContent = `${it.symbol}　${it.name}`;
    const p = $('q-price');
    p.textContent = fmt(it.close); p.className = 'q-price ' + cls(it.change);
    const q = $('q-change');
    q.className = 'q-change ' + cls(it.change);
    q.textContent = `${it.change > 0 ? '▲' : it.change < 0 ? '▼' : ''} ${fmt(Math.abs(it.change))}　(${it.pct > 0 ? '+' : ''}${fmt(it.pct)}%)`;
    $('q-date').textContent = it.live ? `收盤日 ${it.date}　·　即時查詢` : `收盤日 ${it.date}　·　網站資料產生於 ${(INDEX && INDEX.built) || DATA.updated}`;
    $('updated').textContent = it.live
      ? `查詢時間：${DATA.updated}（台北）　資料來源：FinMind（交易所原始價，未還原權息）`
      : `目前這個週期的資料產生時間：${DATA.updated}（台北）　資料來源：Yahoo Finance（經 yfinance）`;
    $('demo-banner').hidden = !DATA.demo;
  }

  // 台北時間「理論上應該已經有的最新收盤日」：當天 18:00 前不要求有當天資料，週末往前推
  function expectedLastClose() {
    const f = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', hourCycle: 'h23',
    });
    const p = Object.fromEntries(f.formatToParts(new Date()).map((x) => [x.type, x.value]));
    const d = new Date(Date.UTC(+p.year, +p.month - 1, +p.day));
    if (+p.hour < 18) d.setUTCDate(d.getUTCDate() - 1);
    while (d.getUTCDay() === 0 || d.getUTCDay() === 6) d.setUTCDate(d.getUTCDate() - 1);
    return d.toISOString().slice(0, 10);
  }

  function renderNotices() {
    const out = [];
    if (ITEM.stale) {
      out.push(`⚠ 這檔最近一次更新<b>失敗</b>，顯示的是舊資料（收盤日 ${esc(ITEM.date)}）。` +
        (ITEM.error ? `<br>原因：${esc(ITEM.error)}` : ''));
    }
    const exp = expectedLastClose();
    if (!DATA.demo && ITEM.date < exp) {
      out.push(`⚠ 最新收盤日是 ${esc(ITEM.date)}，但依日期應該已有 ${exp} 的資料。` +
        '若剛好遇到休市日或連假可忽略；否則代表自動更新沒有成功，請到 GitHub 的 Actions 頁面查看。');
    }
    if (TF === 'H' && !DATA.demo && String(DATA.last.date).slice(0, 10) < ITEM.date) {
      out.push(`⚠ 小時線只更新到 ${esc(DATA.last.date)}，比日線舊；可能是小時線這次沒有抓到，先沿用上一次的資料。`);
    }
    (DATA.notes || []).forEach((t) => out.push('ℹ ' + esc(t)));
    $('notices').innerHTML = out.map((t) => `<div class="banner">${t}</div>`).join('');
  }


  // ------------------------------------------------------------------ 即時查詢（瀏覽器直接向 FinMind 取資料）
  const FM = 'https://api.finmindtrade.com/api/v4/data';
  let LIVE = null, INFO = null, chipsChart = null, chipsBar = null, chipsLine = null;

  async function fm(dataset, params) {
    const q = new URLSearchParams({ dataset, ...params });
    let r;
    try { r = await fetch(`${FM}?${q}`); } catch (e) { throw new Error('連不上 FinMind 資料服務（網路或瀏覽器限制）'); }
    let j = null;
    try { j = await r.json(); } catch (_) { /* 非 JSON */ }
    if (!r.ok || !j) throw new Error(`FinMind 回應異常（HTTP ${r.status}）`);
    if (j.status && j.status !== 200) throw new Error(`FinMind：${j.msg || j.status}（可能是流量上限，稍後再試）`);
    return j.data || [];
  }
  const ymd = (d) => d.toISOString().slice(0, 10);
  const yearsAgo = (n) => { const d = new Date(); d.setUTCFullYear(d.getUTCFullYear() - n); return ymd(d); };

  async function getInfo() {
    if (INFO) return INFO;
    const rows = await fm('TaiwanStockInfo', {});
    const m = new Map();
    rows.forEach((r) => { if (r.stock_id && !m.has(r.stock_id)) m.set(r.stock_id, r.stock_name || r.stock_id); });
    INFO = m;
    return m;
  }

  async function fetchDaily(code) {
    const rows = (await fm('TaiwanStockPrice', { data_id: code, start_date: yearsAgo(3) }))
      .filter((r) => r.close > 0 && r.max > 0)
      .map((r) => ({ date: r.date, open: +r.open || +r.close, high: +r.max, low: +r.min, close: +r.close, volume: +r.Trading_Volume || 0 }));
    rows.sort((a, b) => (a.date < b.date ? -1 : 1));
    return rows;
  }

  function resample(rows, tf) {
    if (tf === 'D') return rows;
    const key = (d) => {
      if (tf === 'M') return d.slice(0, 7);
      const t = new Date(d + 'T00:00:00Z'); const wd = (t.getUTCDay() + 6) % 7;   // 週一為一週起點
      t.setUTCDate(t.getUTCDate() - wd); return ymd(t);
    };
    const out = []; let cur = null, ck = null;
    rows.forEach((r) => {
      const k = key(r.date);
      if (k !== ck) { cur = { ...r }; out.push(cur); ck = k; }
      else { cur.high = Math.max(cur.high, r.high); cur.low = Math.min(cur.low, r.low); cur.close = r.close; cur.volume += r.volume; cur.date = r.date; }
    });
    return out;
  }

  // 與 signals.py 相同的定義（pandas 語意：ewm(adjust=False, min_periods=n)、Wilder RMA）
  const NaNs = (n) => new Array(n).fill(NaN);
  function emaS(v, n) {
    const o = NaNs(v.length); let y = null;
    for (let i = 0; i < v.length; i++) { y = y == null ? v[i] : y + (v[i] - y) * (2 / (n + 1)); if (i >= n - 1) o[i] = y; }
    return o;
  }
  function smaS(v, n) {
    const o = NaNs(v.length); let s = 0;
    for (let i = 0; i < v.length; i++) { s += v[i]; if (i >= n) s -= v[i - n]; if (i >= n - 1) o[i] = s / n; }
    return o;
  }
  function stdS(v, n) {
    const o = NaNs(v.length);
    for (let i = n - 1; i < v.length; i++) {
      let m = 0; for (let j = i - n + 1; j <= i; j++) m += v[j]; m /= n;
      let q = 0; for (let j = i - n + 1; j <= i; j++) q += (v[j] - m) ** 2;
      o[i] = Math.sqrt(q / n);
    }
    return o;
  }
  function rmaS(v, n) {
    const o = NaNs(v.length); const ok = [];
    for (let i = 0; i < v.length; i++) if (!Number.isNaN(v[i])) ok.push(i);
    if (ok.length < n) return o;
    const st = ok[n - 1]; let s = 0; for (let k = 0; k < n; k++) s += v[ok[k]];
    o[st] = s / n;
    for (let i = st + 1; i < v.length; i++) o[i] = Number.isNaN(v[i]) ? o[i - 1] : (o[i - 1] * (n - 1) + v[i]) / n;
    return o;
  }

  function buildLive(raw, tf) {
    const rows = resample(raw, tf);
    const n = rows.length;
    if (n < 30) throw new Error(`這檔的${{ D: '日', W: '週', M: '月' }[tf]}線只有 ${n} 根，資料太少無法計算指標`);
    const t = rows.map((r) => r.date);
    const o = rows.map((r) => r.open), h = rows.map((r) => r.high), l = rows.map((r) => r.low), c = rows.map((r) => r.close), vol = rows.map((r) => r.volume);
    const ma = { ma5: smaS(c, 5), ma20: smaS(c, 20), ma60: smaS(c, 60) };
    const mid = smaS(c, 20), sd = stdS(c, 20);
    const E = { ema5: emaS(c, 5), ema10: emaS(c, 10), ema30: emaS(c, 30), ema60: emaS(c, 60), ema200: emaS(c, 200) };
    const tr = c.map((_, i) => i === 0 ? NaN : Math.max(h[i] - l[i], Math.abs(h[i] - c[i - 1]), Math.abs(l[i] - c[i - 1])));
    const pdm = c.map((_, i) => { if (i === 0) return NaN; const u = h[i] - h[i - 1], d = l[i - 1] - l[i]; return u > d && u > 0 ? u : 0; });
    const mdm = c.map((_, i) => { if (i === 0) return NaN; const u = h[i] - h[i - 1], d = l[i - 1] - l[i]; return d > u && d > 0 ? d : 0; });
    const atr = rmaS(tr, 14), rp = rmaS(pdm, 14), rm = rmaS(mdm, 14);
    const pdi = atr.map((a, i) => 100 * rp[i] / a), mdi = atr.map((a, i) => 100 * rm[i] / a);
    const dx = pdi.map((p, i) => { const s = p + mdi[i]; return s === 0 ? NaN : 100 * Math.abs(p - mdi[i]) / s; });
    const adx = rmaS(dx, 14);
    const regime = adx.map((a) => Number.isNaN(a) ? '' : a >= 25 ? 't' : a >= 20 ? 'x' : 'r');

    const esig = []; let lastProbe = -1e9;
    for (let i = 1; i < n; i++) {
      const e10 = E.ema10[i], e30 = E.ema30[i], e60 = E.ema60[i];
      const p10 = E.ema10[i - 1], p30 = E.ema30[i - 1];
      if ([e10, e30, e60, p10, p30, adx[i]].some(Number.isNaN)) continue;
      const bull = e10 > e30 && e30 > e60, bear = e10 < e30 && e30 < e60, trending = adx[i] >= 20;
      const dn = c[i - 1] >= p10 && c[i] < e10, up = c[i - 1] <= p10 && c[i] > e10;
      if (bull && trending && pdi[i] > mdi[i] && up && c[i - 1] > p30) esig.push({ time: t[i], kind: 'trend_reentry' });
      if (bull && dn) esig.push({ time: t[i], kind: 'pullback_sell' });
      if (bear && trending && mdi[i] > pdi[i] && dn && c[i - 1] < p30) esig.push({ time: t[i], kind: 'trend_short' });
      if (bear && (e30 - c[i]) / atr[i] >= 3 && c[i] > o[i] && c[i - 1] < o[i - 1]) {
        if (i - lastProbe > 5) { esig.push({ time: t[i], kind: 'bounce_probe' }); lastProbe = i; }
      }
    }

    const pts = (arr) => arr.map((v, i) => Number.isNaN(v) ? null : { time: t[i], value: +v.toFixed(4) }).filter(Boolean);
    const last = rows[n - 1], prev = rows[n - 2];
    const lines = { ...Object.fromEntries(Object.entries(ma).map(([k, v]) => [k, pts(v)])),
      ...Object.fromEntries(Object.entries(E).map(([k, v]) => [k, pts(v)])),
      bb_mid: pts(mid), bb_up: pts(mid.map((m, i) => m + 2 * sd[i])), bb_dn: pts(mid.map((m, i) => m - 2 * sd[i])) };
    const notes = [];
    if (n < 200) notes.push(`只有 ${n} 根 K 棒，EMA200 需要至少 200 根，所以圖上沒有 EMA200。`);
    notes.push('即時查詢模式：價格為交易所原始價（未還原權息），不含 VSA、缺口與策略回測；這些只在自選清單內提供。');
    const cut = Math.max(0, n - 700);   // 只輸出最近 700 根，指標已用完整資料暖機
    const cutT = (a) => a.filter((x) => x.time >= t[cut]);
    return {
      symbol: LIVE_CODE(), tf, demo: false, updated: new Date().toLocaleString('sv-SE', { timeZone: 'Asia/Taipei' }).slice(0, 16),
      last: { date: last.date, close: last.close, change: last.close - prev.close, pct: (last.close / prev.close - 1) * 100 },
      bars: n, notes, costs: { fee: 0.001425, tax: 0.003, stop: 0.08 },
      candles: rows.slice(cut).map((r) => ({ time: r.date, open: r.open, high: r.high, low: r.low, close: r.close })),
      volume: rows.slice(cut).map((r) => ({ time: r.date, value: r.volume, up: r.close >= r.open })),
      volma: cutT(pts(smaS(vol, 30))),
      lines: Object.fromEntries(Object.entries(lines).map(([k, v]) => [k, cutT(v)])),
      dmi: { adx: cutT(pts(adx)), pdi: cutT(pts(pdi)), mdi: cutT(pts(mdi)) },
      regime: t.map((d, i) => ({ time: d, s: regime[i] })).slice(cut),
      now: { state: regime[n - 1] || null, adx: adx[n - 1], pdi: pdi[n - 1], mdi: mdi[n - 1] },
      esig: cutT(esig), vsa: [], gaps: null, strategies: {},
    };
  }
  const LIVE_CODE = () => (LIVE ? LIVE.symbol : '');

  // 法人籌碼：三大法人合計買賣超（張）
  function makeChips() {
    const el = $('chips');
    chipsChart = LightweightCharts.createChart(el, { ...chartOptions(el.clientHeight || 260), width: el.clientWidth || 300 });
    chipsBar = chipsChart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'left', lastValueVisible: false, priceLineVisible: false });
    chipsLine = chipsChart.addLineSeries({ color: '#ffffff', lineWidth: 2, priceScaleId: 'right', lastValueVisible: false, priceLineVisible: false });
    chipsChart.applyOptions({ leftPriceScale: { visible: false } });
  }

  async function loadChips(item, seq) {
    const card = $('card-chips'), err = $('chips-err');
    const code = (item.live ? item.symbol : item.symbol.split('.')[0]);
    if (!/^\d{4,6}[A-Z]?$/.test(code)) { card.hidden = true; return; }
    card.hidden = false; err.hidden = true;
    $('chips-sum').innerHTML = '<div class="hint">載入法人資料中…</div>';
    chipsBar.setData([]); chipsLine.setData([]);
    try {
      const rows = await fm('TaiwanStockInstitutionalInvestorsBuySell', { data_id: code, start_date: yearsAgo(1) });
      if (seq !== loadSeq) return;
      if (!rows.length) throw new Error('查無這檔的法人買賣超資料（部分 ETF 或新上市股票可能沒有）');
      const by = new Map(), who = { f: 0, t: 0, d: 0 };
      const days = [...new Set(rows.map((r) => r.date))].sort();
      rows.forEach((r) => {
        const net = (r.buy - r.sell) / 1000;
        by.set(r.date, (by.get(r.date) || 0) + net);
      });
      const last20 = new Set(days.slice(-20));
      rows.forEach((r) => {
        if (!last20.has(r.date)) return;
        const net = (r.buy - r.sell) / 1000;
        if (r.name === 'Foreign_Investor' || r.name === 'Foreign_Dealer_Self') who.f += net;
        else if (r.name === 'Investment_Trust') who.t += net; else who.d += net;
      });
      const shown = days.slice(-60); let cum = 0;
      const bars = [], line = [];
      shown.forEach((d) => { const v = by.get(d) || 0; cum += v; bars.push({ time: d, value: v, color: v >= 0 ? 'rgba(239,83,80,.75)' : 'rgba(38,166,154,.75)' }); line.push({ time: d, value: cum }); });
      const sum = (k) => shown.slice(-k).reduce((a, d) => a + (by.get(d) || 0), 0);
      const sg = (x) => (x > 0 ? '+' : '') + Math.round(x).toLocaleString() + ' 張';
      $('chips-sum').innerHTML = [
        stat('法人 5 日', sg(sum(5)), '', cls(sum(5))), stat('法人 20 日', sg(sum(20)), '', cls(sum(20))),
        stat('外資 20 日', sg(who.f), '', cls(who.f)), stat('投信 20 日', sg(who.t), '', cls(who.t)),
        stat('自營商 20 日', sg(who.d), '', cls(who.d)), stat('資料到', days[days.length - 1]),
      ].join('');
      chipsChart.applyOptions({ width: $('chips').clientWidth });
      chipsBar.setData(bars); chipsLine.setData(line);
      chipsChart.timeScale().fitContent();
    } catch (e) {
      if (seq !== loadSeq) return;
      $('chips-sum').innerHTML = ''; err.hidden = false; err.textContent = '法人資料載入失敗：' + e.message;
    }
  }


  // ------------------------------------------------------------------ 自選清單管理（透過 GitHub API 修改 watchlist.txt）
  const GH_OWNER = location.hostname.split('.')[0];
  const GH_REPO = location.pathname.split('/')[1] || '0050';
  const getTok = () => { try { return localStorage.getItem('ghtok') || ''; } catch (_) { return ''; } };
  const setTok = (v) => { try { v ? localStorage.setItem('ghtok', v) : localStorage.removeItem('ghtok'); } catch (_) { /* 無痕模式 */ } };

  async function ghFile() {
    const tok = getTok();
    if (!tok) throw new Error('尚未儲存 GitHub 權杖，請先在「管理我的自選清單」貼上權杖');
    const url = `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/contents/watchlist.txt`;
    const h = { Authorization: `Bearer ${tok}`, Accept: 'application/vnd.github+json' };
    const r = await fetch(url, { headers: h });
    if (r.status === 401 || r.status === 403 || r.status === 404) throw new Error(`GitHub 拒絕存取（${r.status}）：權杖錯誤、已過期，或沒有 0050 的 Contents 讀寫權限`);
    if (!r.ok) throw new Error('讀取 watchlist.txt 失敗（HTTP ' + r.status + '）');
    const j = await r.json();
    const bin = atob(j.content.replace(/\n/g, ''));
    const text = new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
    return { url, h, sha: j.sha, text };
  }
  async function ghSave(f, text, msg) {
    const bytes = new TextEncoder().encode(text);
    let bin = ''; bytes.forEach((b) => { bin += String.fromCharCode(b); });
    const r = await fetch(f.url, { method: 'PUT', headers: { ...f.h, 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, content: btoa(bin), sha: f.sha, branch: 'main' }) });
    if (r.status === 409 || r.status === 422) throw new Error('清單剛好被別處更新，請再按一次');
    if (!r.ok) throw new Error('寫入失敗（HTTP ' + r.status + '）：權杖需要 Contents 的 Read and write 權限');
  }
  const wlSyms = (text) => text.split(/\r?\n/).filter((l) => l.trim() && !l.trim().startsWith('#')).map((l) => l.split(',')[0].trim());

  async function wlAdd(item) {
    const sym = item.symbol + '.TW';            // 上櫃股程式會自動改試 .TWO
    const f = await ghFile();
    if (wlSyms(f.text).some((x) => x.split('.')[0] === item.symbol)) throw new Error(item.symbol + ' 已經在自選清單裡了');
    const nm = String(item.name).replace(/[,\r\n]/g, '');
    await ghSave(f, f.text.replace(/\s*$/, '\n') + `${sym},${nm}\n`, `加入自選 ${item.symbol} ${nm}`);
  }
  async function wlRemove(symbol) {
    const f = await ghFile();
    const lines = f.text.split(/\r?\n/).filter((l) => l.split(',')[0].trim() !== symbol);
    await ghSave(f, lines.join('\n').replace(/\s*$/, '\n'), `移除自選 ${symbol}`);
  }

  function renderManage() {
    $('wl').innerHTML = INDEX.items.map((i) =>
      `<div><span>${esc(i.symbol)}　${esc(i.name)}</span><button type="button" data-rm="${esc(i.symbol)}">✕</button></div>`).join('');
    $('tok-state').textContent = getTok() ? '✔ 已儲存權杖（在這支手機的瀏覽器）。' : '尚未儲存權杖：沒有權杖就無法新增／移除。';
  }
  function renderAddBtn() {
    const b = $('add-watch');
    const inList = ITEM.live && INDEX.items.some((i) => i.symbol.split('.')[0] === ITEM.symbol);
    b.hidden = !ITEM.live || inList;
  }

  // ------------------------------------------------------------------ 搜尋
  function setLookupMsg(html) { const m = $('lookup-msg'); m.hidden = !html; m.innerHTML = html || ''; }

  async function openLive(code, name) {
    const raw = await fetchDaily(code);
    if (!raw.length) throw new Error(`查無「${code}」的價格資料（代號錯誤、尚未上市，或這檔不在 FinMind 資料內）`);
    if (raw.length < 30) throw new Error(`「${code}」只有 ${raw.length} 筆日線，資料太少無法計算指標`);
    const a = raw[raw.length - 1], b = raw[raw.length - 2] || a;
    LIVE = { symbol: code, name: name || code, live: true, rows: raw, files: { D: 1, W: 1, M: 1 },
      close: a.close, change: a.close - b.close, pct: (a.close / b.close - 1) * 100, date: a.date };
    ITEM = LIVE; TF = 'D';
    const sel = $('symbol');
    let opt = sel.querySelector('option[value="live"]');
    if (!opt) { opt = document.createElement('option'); opt.value = 'live'; sel.prepend(opt); }
    opt.textContent = `🔎 ${code}　${LIVE.name}（查詢）`;
    sel.value = 'live';
    await load();
  }

  async function lookup(q) {
    q = q.trim().toUpperCase();
    if (!q) return;
    setLookupMsg('');
    const hit = INDEX.items.findIndex((i) => i.symbol.split('.')[0].toUpperCase() === q || i.name.toUpperCase() === q);
    if (hit >= 0) { $('symbol').value = String(hit); ITEM = INDEX.items[hit]; await load(); return; }
    if (/^\d{4,6}[A-Z]?$/.test(q)) {
      let name = q;
      try { name = (await getInfo()).get(q) || q; } catch (_) { /* 名稱查不到就用代號 */ }
      await openLive(q, name);
      return;
    }
    const info = await getInfo();
    const ms = [...info].filter(([id, nm]) => /^\d{4,6}[A-Z]?$/.test(id) && nm.toUpperCase().includes(q)).slice(0, 8);
    if (!ms.length) { setLookupMsg(`找不到名稱含「${esc(q)}」的股票，請改輸入代號。`); return; }
    if (ms.length === 1) { await openLive(ms[0][0], ms[0][1]); return; }
    setLookupMsg('找到多檔，請點選：<br>' + ms.map(([id, nm]) => `<button type="button" data-code="${esc(id)}" data-name="${esc(nm)}">${esc(id)} ${esc(nm)}</button>`).join(''));
  }

  async function load() {
    const my = ++loadSeq;
    const files = ITEM.files || { D: ITEM.file };
    if (!files[TF]) TF = 'D';
    document.querySelectorAll('#tf button').forEach((b) => {
      b.disabled = !files[b.dataset.tf];
      b.classList.toggle('on', b.dataset.tf === TF);
    });
    let json;
    if (ITEM.live) {
      json = buildLive(ITEM.rows, TF);
    } else {
      const r = await fetch('data/' + files[TF] + '?t=' + Date.now());
      if (!r.ok) throw new Error('讀不到 ' + files[TF]);
      json = await r.json();
    }
    if (my !== loadSeq) return;          // 期間又切換了標的或週期，放棄這次的結果
    DATA = json;

    teardown();
    makeMain(TF === 'H');
    makeDmi();

    candle.setData(DATA.candles);
    volSeries.setData(DATA.volume.map((v) => ({ time: v.time, value: v.value, color: v.up ? 'rgba(239,83,80,.55)' : 'rgba(38,166,154,.55)' })));
    volMaSeries.setData(DATA.volma || []);
    Object.keys(lineSeries).forEach((k) => lineSeries[k].setData((DATA.lines && DATA.lines[k]) || []));
    const dm = DATA.dmi || {};
    bgS.setData((DATA.regime || []).map((x) => ({ time: x.time, value: 1, color: BG[x.s] || 'rgba(0,0,0,0)' })));
    adxS.setData(dm.adx || []); pdiS.setData(dm.pdi || []); mdiS.setData(dm.mdi || []);

    const n = DATA.candles.length;
    const range = { from: Math.max(0, n - WINDOW[TF]), to: n + 4 };
    chart.timeScale().setVisibleLogicalRange(range);
    syncDmi(range);

    renderQuote(); renderNotices(); renderRegime(); renderGaps(); renderStrategySection(); applyOverlays();
    $('card-gaps').hidden = !DATA.gaps;
    loadChips(ITEM, my); renderAddBtn();
  }

  async function main() {
    try {
      const r = await fetch('data/index.json?t=' + Date.now());
      if (!r.ok) throw new Error('找不到 data/index.json');
      INDEX = await r.json();
      if (!INDEX.items.length) throw new Error('index.json 裡沒有任何標的');
    } catch (e) {
      document.querySelector('.quote').innerHTML =
        `<div class="warn">無法載入資料：${e.message}。<br>1) 先執行 <code>python build_data.py</code> 產生 docs/data；<br>2) 不能直接雙擊 index.html，請在專案資料夾執行 <code>python -m http.server -d docs 8000</code> 再開 http://localhost:8000</div>`;
      return;
    }
    makeEq(); makeChips(); renderManage();
    new ResizeObserver(() => {
      const el = $('chart'), e2 = $('eq');
      if (chart && el.clientWidth) {
        chart.applyOptions({ width: el.clientWidth, height: el.clientHeight });
        if (dmiChart) dmiChart.applyOptions({ width: el.clientWidth });
      }
      const e3 = $('chips');
      if (chipsChart && e3.clientWidth) chipsChart.applyOptions({ width: e3.clientWidth, height: e3.clientHeight });
      if (eqChart && e2.clientWidth) eqChart.applyOptions({ width: e2.clientWidth, height: e2.clientHeight });
    }).observe(document.body);

    $('symbol').innerHTML = INDEX.items.map((i, k) =>
      `<option value="${k}">${esc(i.symbol)}　${esc(i.name)}${i.stale ? '　⚠舊資料' : ''}</option>`).join('');
    ITEM = INDEX.items[0];

    $('symbol').addEventListener('change', (e) => {
      ITEM = e.target.value === 'live' ? LIVE : INDEX.items[+e.target.value];
      if (!ITEM.live) TF = TF === 'H' && !(ITEM.files && ITEM.files.H) ? 'D' : TF;
      load().catch((x) => alert(x.message));
    });
    $('tok-save').addEventListener('click', () => { const v = $('tok').value.trim(); if (v) { setTok(v); $('tok').value = ''; renderManage(); } });
    $('tok-clear').addEventListener('click', () => { setTok(''); renderManage(); });
    $('add-watch').addEventListener('click', async (e) => {
      const b = e.target; b.disabled = true; const t0 = b.textContent; b.textContent = '寫入中…';
      try { await wlAdd(ITEM); setLookupMsg(`✔ 已加入 ${esc(ITEM.symbol)}。約 2～3 分鐘後（網站重新建置完成）重新整理，就會出現在選單，並納入 LINE 通知。`); b.hidden = true; }
      catch (x) { setLookupMsg('⚠ ' + esc(x.message)); if (!getTok()) $('manage').open = true; }
      finally { b.disabled = false; b.textContent = t0; }
    });
    $('wl').addEventListener('click', async (e) => {
      const b = e.target.closest('button[data-rm]'); if (!b) return;
      if (!confirm(`從自選清單移除 ${b.dataset.rm}？`)) return;
      try { await wlRemove(b.dataset.rm); b.closest('div').remove(); setLookupMsg(`✔ 已移除 ${esc(b.dataset.rm)}，約 2～3 分鐘後選單更新。`); }
      catch (x) { setLookupMsg('⚠ ' + esc(x.message)); }
    });
    $('lookup').addEventListener('submit', async (e) => {
      e.preventDefault();
      const b = e.target.querySelector('button'); b.disabled = true; b.textContent = '查詢中…';
      try { await lookup($('code').value); $('code').blur(); }
      catch (x) { setLookupMsg('⚠ ' + esc(x.message)); }
      finally { b.disabled = false; b.textContent = '查詢'; }
    });
    $('lookup-msg').addEventListener('click', async (e) => {
      const b = e.target.closest('button[data-code]'); if (!b) return;
      setLookupMsg('查詢中…');
      try { await openLive(b.dataset.code, b.dataset.name); setLookupMsg(''); } catch (x) { setLookupMsg('⚠ ' + esc(x.message)); }
    });
    $('strategy').addEventListener('change', () => { renderStrategy(); applyOverlays(); });
    $('tf').addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b || b.disabled || b.dataset.tf === TF) return;
      TF = b.dataset.tf;
      load().catch((x) => alert(x.message));
    });
    $('mode').addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (b) setMode(b.dataset.m);
    });
    document.querySelectorAll('#toggles input').forEach((i) => i.addEventListener('change', () => {
      document.querySelectorAll('#mode button').forEach((b) => b.classList.remove('on'));   // 手動調整後不再算任何一個預設模式
      applyOverlays();
    }));

    await load();
  }

  window.__lt = () => DATA;   // 除錯／測試用
  main();
})();
