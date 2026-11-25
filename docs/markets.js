(() => {
  const UP = '#ef5350', DOWN = '#26a69a';
  const $ = (id) => document.getElementById(id);
  const OWNER = location.hostname.split('.')[0], REPO = location.pathname.split('/')[1] || '0050';
  const fmt = (x, d = 2) => x == null ? '—' : Number(x).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  const cls = (x) => x > 0 ? 'up' : x < 0 ? 'down' : 'flat';
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const sign = (x, d = 2) => (x > 0 ? '+' : '') + fmt(x, d);
  let DATA = null, TAB = 'us', SEL = null;
  const charts = {};

  function mk(id) {
    const el = $(id);
    const c = LightweightCharts.createChart(el, {
      width: el.clientWidth || 320, height: el.clientHeight || 340,
      layout: { background: { color: 'transparent' }, textColor: '#aab0bd', fontFamily: 'inherit' },
      grid: { vertLines: { color: '#232632' }, horzLines: { color: '#232632' } },
      rightPriceScale: { borderColor: '#2a2d38', minimumWidth: 64 },
      timeScale: { borderColor: '#2a2d38', timeVisible: true, secondsVisible: false, rightOffset: 3 },
    });
    const s = c.addCandlestickSeries({ upColor: UP, downColor: DOWN, wickUpColor: UP, wickDownColor: DOWN, borderVisible: false });
    return { c, s, line: null };
  }
  function draw(key, id, candles, base, title) {
    if (!charts[key]) charts[key] = mk(id);
    const ch = charts[key];
    ch.s.setData(candles.map((k) => ({ time: k[0], open: k[1], high: k[2], low: k[3], close: k[4] })));
    if (ch.line) { ch.s.removePriceLine(ch.line); ch.line = null; }
    if (base != null) ch.line = ch.s.createPriceLine({ price: base, color: '#8a90a0', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title });
    ch.c.applyOptions({ width: $(id).clientWidth });
    ch.c.timeScale().fitContent();
  }

  function renderUs() {
    const list = DATA.us || [];
    if (!list.length) { $('us-grid').innerHTML = '<div class="warn">這次沒有取得美股資料。</div>'; return; }
    if (!SEL || !list.find((x) => x.symbol === SEL)) SEL = list[0].symbol;
    $('us-grid').innerHTML = list.map((x) =>
      `<button class="tile ${x.symbol === SEL ? 'on' : ''}" data-s="${esc(x.symbol)}"><div class="n">${esc(x.name)}　${esc(x.symbol)}</div>` +
      `<div class="p ${cls(x.change)}">${fmt(x.last)}</div><div class="c ${cls(x.change)}">${sign(x.change)}　(${sign(x.pct)}%)</div><div class="t">${esc(x.time)}</div></button>`).join('');
    const x = list.find((y) => y.symbol === SEL);
    $('us-title').textContent = `${x.name}（${x.symbol}）`;
    $('us-sub').innerHTML = `<span class="${cls(x.change)}">${fmt(x.last)}　${sign(x.change)}（${sign(x.pct)}%）</span>　前收 ${fmt(x.prev)}　最後一筆 ${esc(x.time)}（台北）`;
    draw('us', 'us-chart', x.candles, x.prev, '前收');
  }

  function stat(k, v, c = '') { return `<div class="stat"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`; }
  function renderNight() {
    const t = DATA.tw;
    if (!t) { $('n-name').textContent = '—'; $('n-stats').innerHTML = '<div class="warn">這次沒有取得夜盤資料（可能是期交所介面暫時失敗）。</div>'; return; }
    const m = t.main;
    $('n-name').textContent = `${m.name}（成交量最大的契約）`;
    $('n-price').textContent = fmt(m.last, 0); $('n-price').className = 'big ' + cls(m.change);
    $('n-change').className = 'q-change ' + cls(m.change);
    $('n-change').textContent = `${m.change > 0 ? '▲' : m.change < 0 ? '▼' : ''} ${fmt(Math.abs(m.change), 0)}　(${sign(m.pct)}%)`;
    const tm = String(m.time || '').padStart(6, '0');
    $('n-time').textContent = `夜盤 ${t.hours}　·　最後成交 ${tm.slice(0, 2)}:${tm.slice(2, 4)}:${tm.slice(4, 6)}`;
    const basis = t.spot_close != null ? m.last - t.spot_close : null;
    $('n-stats').innerHTML = [stat('開盤', fmt(m.open, 0)), stat('最高', fmt(m.high, 0), 'up'), stat('最低', fmt(m.low, 0), 'down'),
      stat('夜盤成交量', fmt(m.volume, 0) + ' 口'), stat('日盤結算價', fmt(m.ref, 0)), stat('現貨收盤', fmt(t.spot_close)),
      stat('期貨－現貨', basis == null ? '—' : sign(basis, 0) + ' 點', cls(basis))].join('');
    $('n-table').querySelector('tbody').innerHTML = t.contracts.map((c) =>
      `<tr><td>${esc(c.name)}</td><td>${fmt(c.last, 0)}</td><td class="${cls(c.change)}">${sign(c.change, 0)}</td><td class="${cls(c.pct)}">${sign(c.pct)}%</td><td>${fmt(c.high, 0)}</td><td>${fmt(c.low, 0)}</td><td>${fmt(c.volume, 0)}</td></tr>`).join('');
    draw('night', 'n-chart', t.candles, m.ref, '日盤結算');
  }

  function render() {
    if (!DATA) return;
    const age = Math.round((Date.now() - new Date(DATA.updated.replace(' ', 'T') + ':00+08:00')) / 60000);
    $('updated').textContent = `報價檔更新時間：${DATA.updated}（台北，約 ${age} 分鐘前）`;
    const w = [];
    if (age > 20) w.push(`⚠ 報價檔已經 ${age} 分鐘沒有更新，可能是 GitHub 排程延遲；畫面上的價格不是最新的。`);
    (DATA.errors || []).forEach((e) => w.push('ℹ ' + esc(e)));
    $('msg').innerHTML = w.map((t) => `<div class="banner">${t}</div>`).join('');
    if (TAB === 'us') renderUs(); else renderNight();
  }

  async function load() {
    try {
      const r = await fetch(`https://raw.githubusercontent.com/${OWNER}/${REPO}/markets/markets.json?t=${Date.now()}`, { cache: 'no-store' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      DATA = await r.json();
    } catch (e) {
      if (!DATA) $('msg').innerHTML = `<div class="banner">還沒有報價資料（${esc(e.message)}）。第一次啟用請稍等排程跑過一次，或到 GitHub Actions 手動執行 “Update US / night-session markets”。</div>`;
      return;
    }
    render();
  }
  function setTab(t) {
    TAB = t;
    document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('on', b.dataset.t === t));
    $('us').hidden = t !== 'us'; $('night').hidden = t !== 'night';
    try { history.replaceState(null, '', '#' + t); } catch (_) { /* 忽略 */ }
    render();
  }
  $('tabs').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) setTab(b.dataset.t); });
  $('us-grid').addEventListener('click', (e) => { const b = e.target.closest('.tile'); if (b) { SEL = b.dataset.s; renderUs(); } });
  new ResizeObserver(() => Object.entries({ us: 'us-chart', night: 'n-chart' }).forEach(([k, id]) => {
    if (charts[k] && $(id).clientWidth) charts[k].c.applyOptions({ width: $(id).clientWidth });
  })).observe(document.body);
  setInterval(() => { if (!document.hidden) load(); }, 60000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
  window.__mk = () => DATA;
  if (location.hash === '#night') setTab('night');
  load();
})();
