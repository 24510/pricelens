/* 价格曲线：ECharts 阶梯折线 + 史低标记 + 均价线 + 时间范围切换。
   由 items.js 渲染详情时调用 window.PLChart.mount(prices)。 */
(function () {
  'use strict';

  const RANGES = [
    { key: '7',   label: '7天',  days: 7 },
    { key: '30',  label: '30天', days: 30 },
    { key: '90',  label: '90天', days: 90 },
    { key: 'all', label: '全部', days: 0 }
  ];
  const SOURCE_NAMES = { manual: '手动', script: '脚本', api: '自动' };

  let inst = null;
  let boxEl = null;
  let allPrices = [];
  let rangeKey = 'all';

  function esc(t) {
    return String(t == null ? '' : t)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function money(v) { return '¥' + Number(v).toFixed(2); }

  function dayOnly(ts) {
    const s = String(ts || '');
    return s.length >= 10 ? s.slice(0, 10) : s;
  }

  function shortTime(ts) {
    const s = String(ts || '');
    return s.length >= 16 ? (s.slice(5, 10) + ' ' + s.slice(11, 16)) : s;
  }

  /* 标签规则（按当前筛选后的记录逐条判断）：
     ① 全部在同一天          → 时:分（22:36）
     ② 跨天 + 纯日期补录     → 月-日（09-18）
     ③ 跨天 + 有具体时刻     → 月-日 时:分（09-25 22:36） */
  function buildLabels(data) {
    const days = {};
    data.forEach(function (p) { days[dayOnly(p.captured_at)] = 1; });
    const sameDay = Object.keys(days).length <= 1;

    return data.map(function (p) {
      const s = String(p.captured_at || '');
      if (s.length <= 10) return s.slice(5);                    // 只有日期
      if (sameDay) return s.slice(11, 16);                      // 时:分
      if (s.slice(11, 16) === '00:00') return s.slice(5, 10);   // 月-日
      return shortTime(s);                                      // 月-日 时:分
    });
  }

  function rangeConfig() {
    for (let i = 0; i < RANGES.length; i++) {
      if (RANGES[i].key === rangeKey) return RANGES[i];
    }
    return RANGES[RANGES.length - 1];
  }

  function filterByRange(list) {
    const cfg = rangeConfig();
    if (!cfg.days) return list.slice();
    const now = new Date();
    const limit = new Date(now.getTime() - cfg.days * 86400000);
    const p = function (n) { return String(n).padStart(2, '0'); };
    const limitStr = limit.getFullYear() + '-' + p(limit.getMonth() + 1) + '-' + p(limit.getDate());
    return list.filter(function (it) { return dayOnly(it.captured_at) >= limitStr; });
  }

  function renderRangeButtons() {
    const wrap = document.getElementById('chartRanges');
    if (!wrap) return;
    wrap.innerHTML = '';
    RANGES.forEach(function (r) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'rng' + (r.key === rangeKey ? ' active' : '');
      b.textContent = r.label;
      b.addEventListener('click', function () {
        rangeKey = r.key;
        renderRangeButtons();
        draw();
      });
      wrap.appendChild(b);
    });
  }

  function dispose() {
    if (inst) {
      try { inst.dispose(); } catch (e) { /* ignore */ }
      inst = null;
    }
  }

  function draw() {
    if (!boxEl) return;

    const data = filterByRange(allPrices).slice().sort(function (a, b) {
      const ka = String(a.captured_at || '');
      const kb = String(b.captured_at || '');
      if (ka === kb) return Number(a.id) - Number(b.id);
      return ka < kb ? -1 : 1;
    });

    if (!window.echarts) {
      dispose();
      boxEl.innerHTML = '<div class="chart-empty">图表组件缺失：web/vendor/echarts.min.js</div>';
      return;
    }

    if (!data.length) {
      dispose();
      boxEl.innerHTML = '<div class="chart-empty">' +
        (allPrices.length ? '所选时间范围内暂无记录' : '记录价格后，这里会显示走势曲线') +
        '</div>';
      return;
    }

    if (!inst) {
      boxEl.innerHTML = '';
      inst = window.echarts.init(boxEl);
    }

    const labels = buildLabels(data);
    const values = data.map(function (p) { return Number(p.price); });
    const lastIdx = values.length - 1;
    const minVal = Math.min.apply(null, values);

    const markData = [{ type: 'min', name: '史低' }];
    if (values.length > 1 && values[lastIdx] > minVal) {
      markData.push({
        coord: [lastIdx, values[lastIdx]],
        name: '当前',
        symbolSize: 34,
        itemStyle: { color: '#ea580c' },
        label: { formatter: '当前', fontSize: 10, color: '#fff' }
      });
    }

    inst.setOption({
      animationDuration: 320,
      grid: { left: 58, right: 22, top: 30, bottom: 34 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(15,23,42,.92)',
        borderWidth: 0,
        textStyle: { color: '#e2e8f0', fontSize: 12 },
        formatter: function (params) {
          if (!params || !params.length) return '';
          const it = data[params[0].dataIndex] || {};
          let s = '<b>' + esc(it.captured_at || '') + '</b><br/>价格：<b>' + money(it.price) + '</b>';
          if (it.note) s += '<br/>备注：' + esc(it.note);
          s += '<br/>来源：' + esc(SOURCE_NAMES[it.source] || it.source || '—');
          return s;
        }
      },
      xAxis: {
        type: 'category',
        data: labels,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#e5e7eb' } },
        axisTick: { show: false },
        axisLabel: { fontSize: 10, color: '#94a3b8', hideOverlap: true }
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: { fontSize: 10, color: '#94a3b8', formatter: '¥{value}' },
        splitLine: { lineStyle: { color: '#f1f5f9' } }
      },
      series: [{
        type: 'line',
        step: 'end',
        data: values,
        symbol: 'circle',
        symbolSize: 6,
        showSymbol: values.length <= 150,
        lineStyle: { width: 2, color: '#f97316' },
        itemStyle: { color: '#f97316', borderColor: '#fff', borderWidth: 1 },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(249,115,22,.20)' },
              { offset: 1, color: 'rgba(249,115,22,.02)' }
            ]
          }
        },
        markPoint: {
          symbol: 'pin',
          symbolSize: 46,
          itemStyle: { color: '#16a34a' },
          label: { color: '#fff', fontSize: 10, lineHeight: 12, formatter: '{b}\n{c}' },
          data: markData
        },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: '#94a3b8', type: 'dashed', width: 1 },
          label: { formatter: '均价', fontSize: 10, color: '#64748b', position: 'insideEndTop' },
          data: [{ type: 'average', name: '均价' }]
        }
      }]
    }, { notMerge: true });
  }

  function mount(prices) {
    allPrices = (prices || []).slice();
    boxEl = document.getElementById('pnlChart');
    dispose();
    renderRangeButtons();
    draw();
  }

  window.addEventListener('resize', function () {
    if (inst) { try { inst.resize(); } catch (e) { /* ignore */ } }
  });

  window.PLChart = { mount: mount, redraw: draw };
})();