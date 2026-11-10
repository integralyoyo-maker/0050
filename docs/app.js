/* 台股訊號與回測：讀取 data/*.json 並用 Lightweight Charts 繪圖 */
(() => {
  const UP = '#ef5350', DOWN = '#26a69a';
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

  let chart, candle, volSeries, volMaSeries, lineSeries = {}, eqChart, eqS, eqB;
  let DATA = null, INDEX = null;

  const fmt = (x, d = 2) => x == null ? '—' : Number(x).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  const pct = (x, d = 1) => x == null ? '—' : (x * 100).toFixed(d) + '%';
  const cls = (x) => x > 0 ? 'up' : x < 0 ? 'down' : 'flat';

  function chartOptions(height) {
    return {
      height,
      layout: { background: { color: 'transparent' }, textColor: '#aab0bd', fontFamily: 'inherit' },
      grid: { vertLines: { color: '#232632' }, horzLines: { color: '#232632' } },
      rightPriceScale: { borderColor: '#2a2d38' },
      timeScale: { borderColor: '#2a2d38', rightOffset: 4 },
      crosshair: { mode: 0 },
    };
  }

  function initCharts() {
    const el = $('chart');
    chart = LightweightCharts.createChart(el, { ...chartOptions(el.clientHeight), width: el.clientWidth });
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
      ema200: L('#ffd43b', 2),
    };

    chart.subscribeCrosshairMove(updateLegend);

    const eqEl = $('eq');
    eqChart = LightweightCharts.createChart(eqEl, { ...chartOptions(eqEl.clientHeight), width: eqEl.clientWidth });
    const pf = { type: 'custom', minMove: 0.001, formatter: (p) => ((p - 1) * 100).toFixed(0) + '%' };
    eqB = eqChart.addLineSeries({ color: '#9aa0ae', lineWidth: 1, priceFormat: pf, priceLineVisible: false });
    eqS = eqChart.addLineSeries({ color: '#5aa9ff', lineWidth: 2, priceFormat: pf, priceLineVisible: false });

    new ResizeObserver(() => {
      chart.applyOptions({ width: el.clientWidth, height: el.clientHeight });
      eqChart.applyOptions({ width: eqEl.clientWidth, height: eqEl.clientHeight });
    }).observe(document.body);
  }

  function updateLegend(param) {
    const lg = $('legend');
    if (!DATA) return;
    let c = null, t = null;
    if (param && param.time && param.seriesData) {
      c = param.seriesData.get(candle); t = param.time;
    }
    if (!c) { const last = DATA.candles[DATA.candles.length - 1]; c = last; t = last.time; }
    const v = param && param.seriesData && param.seriesData.get(volSeries);
    const g = (k) => { const s = param && param.seriesData && param.seriesData.get(lineSeries[k]); return s ? fmt(s.value) : null; };
    const parts = [
      `${typeof t === 'string' ? t : ''}`,
      `開 ${fmt(c.open)}`, `高 ${fmt(c.high)}`, `低 ${fmt(c.low)}`, `收 ${fmt(c.close)}`,
    ];
    if (v) parts.push(`量 ${Math.round(v.value / 1000).toLocaleString()} 張`);
    const e = g('ema200'); if (e) parts.push(`EMA200 ${e}`);
    const u = g('bb_up'), d = g('bb_dn'); if (u && d) parts.push(`布林 ${d} ~ ${u}`);
    lg.textContent = parts.join('　');
  }

  function toggles() {
    const o = {};
    document.querySelectorAll('#toggles input').forEach((i) => (o[i.dataset.k] = i.checked));
    return o;
  }

  function applyOverlays() {
    if (!DATA) return;
    const t = toggles();
    ['ma5', 'ma20', 'ma60'].forEach((k) => lineSeries[k].applyOptions({ visible: t.ma }));
    ['bb_up', 'bb_mid', 'bb_dn'].forEach((k) => lineSeries[k].applyOptions({ visible: t.boll }));
    lineSeries.ema200.applyOptions({ visible: t.ema200 });

    const m = [];
    DATA.vsa.forEach((s) => {
      const d = VSA_MAIN[s.kind] && t.vsa ? VSA_MAIN[s.kind] : VSA_SUB[s.kind] && t.vsa2 ? VSA_SUB[s.kind] : null;
      if (d) m.push({ time: s.time, position: d.pos, color: d.color, shape: d.shape, text: d.text });
    });
    if (t.gap) {
      DATA.gaps.forEach((g) => m.push({
        time: g.time, position: g.type === 'up' ? 'belowBar' : 'aboveBar',
        color: '#9aa0ae', shape: 'square', text: g.type === 'up' ? '未補↑' : '未補↓',
      }));
    }
    if (t.strat) {
      const st = DATA.strategies[$('strategy').value];
      st.markers.forEach((s) => m.push(s.side === 'buy'
        ? { time: s.time, position: 'belowBar', color: UP, shape: 'arrowUp', text: '買' }
        : { time: s.time, position: 'aboveBar', color: DOWN, shape: 'arrowDown', text: '賣' }));
    }
    m.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
    candle.setMarkers(m);
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

  function renderGaps() {
    $('gaps').querySelector('tbody').innerHTML = DATA.gaps.slice().reverse().map((g) =>
      `<tr><td>${g.time}</td><td class="${g.type === 'up' ? 'up' : 'down'}">${g.type === 'up' ? '向上缺口' : '向下缺口'}</td>` +
      `<td>${fmt(g.bottom)} ~ ${fmt(g.top)}</td></tr>`).join('') ||
      '<tr><td colspan="3" style="text-align:center;color:#8d93a3">目前沒有未補缺口</td></tr>';
  }

  function renderQuote() {
    const l = DATA.last;
    $('q-name').textContent = `${DATA.symbol}　${DATA.name}`;
    const p = $('q-price');
    p.textContent = fmt(l.close); p.className = 'q-price ' + cls(l.change);
    const q = $('q-change');
    q.className = 'q-change ' + cls(l.change);
    q.textContent = `${l.change > 0 ? '▲' : l.change < 0 ? '▼' : ''} ${fmt(Math.abs(l.change))}　(${l.pct > 0 ? '+' : ''}${fmt(l.pct)}%)`;
    $('q-date').textContent = `收盤日 ${l.date}`;
    $('updated').textContent = `資料更新時間：${DATA.updated}（台北）　資料來源：Yahoo Finance（經 yfinance）`;
    $('demo-banner').hidden = !DATA.demo;
  }

  async function loadSymbol(file) {
    const r = await fetch('data/' + file + '?t=' + Date.now());
    if (!r.ok) throw new Error('讀不到 ' + file);
    DATA = await r.json();

    const sel = $('strategy');
    if (!sel.options.length) {
      sel.innerHTML = Object.entries(DATA.strategies).map(([k, v]) => `<option value="${k}">${v.name}</option>`).join('');
    }

    candle.setData(DATA.candles);
    volSeries.setData(DATA.volume.map((v) => ({ time: v.time, value: v.value, color: v.up ? 'rgba(239,83,80,.55)' : 'rgba(38,166,154,.55)' })));
    volMaSeries.setData(DATA.volma);
    Object.keys(lineSeries).forEach((k) => lineSeries[k].setData(DATA.lines[k] || []));

    // 預設顯示最近約 180 根 K 棒
    const n = DATA.candles.length;
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 180), to: n + 4 });

    renderQuote(); renderGaps(); renderStrategy(); applyOverlays(); updateLegend(null);
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
    initCharts();

    $('symbol').innerHTML = INDEX.items.map((i) => `<option value="${i.file}">${i.symbol}　${i.name}</option>`).join('');
    const sel = $('strategy');
    await loadSymbol(INDEX.items[0].file);

    $('symbol').addEventListener('change', (e) => loadSymbol(e.target.value).catch((x) => alert(x.message)));
    sel.addEventListener('change', () => { renderStrategy(); applyOverlays(); });
    document.querySelectorAll('#toggles input').forEach((i) => i.addEventListener('change', applyOverlays));
  }

  main();
})();
