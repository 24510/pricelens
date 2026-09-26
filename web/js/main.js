/* 主界面：状态刷新 / 数据目录 / 顶部卡片 / 平台表 / 状态栏 / 自动刷新。
   商品与价格交互在 items.js；采集通道在 capture.js。 */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);

  function esc(t) {
    return String(t == null ? '' : t)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function setText(id, text) {
    const el = $(id);
    if (el) el.textContent = String(text == null ? '' : text);
  }

  function setStatus(text) { setText('statusText', text); }

  function setChooserMsg(text, cls) {
    const el = $('chooserMsg');
    if (!el) return;
    el.className = 'msg' + (cls ? ' ' + cls : '');
    el.textContent = text || '';
  }

  function paintBadge(text, needChoose) {
    const el = $('modeBadge');
    if (!el) return;
    el.textContent = text || '';
    el.className = 'badge';
    if (needChoose) {
      el.style.background = '#e2e8f0';
      el.style.color = '#475569';
      return;
    }
    if (String(text).indexOf('增强') >= 0) {
      el.style.background = 'rgba(22,163,74,.12)';
      el.style.color = '#15803d';
    } else {
      el.style.background = 'rgba(249,115,22,.12)';
      el.style.color = '#c2410c';
    }
  }

  function renderPlatforms(list) {
    const tb = $('platforms');
    if (!tb) return;
    tb.innerHTML = '';
    (list || []).forEach(function (p) {
      const enhanced = p.mode === 'enhanced';
      const note = p.note || (enhanced ? '已配置密钥（自动刷新 P3 开放）'
                                        : '手动记价 / 浏览器脚本采集');
      const tr = document.createElement('tr');
      tr.innerHTML = '<td>' + esc(p.name) + '</td>' +
        '<td><span class="' + (enhanced ? 'mode-on' : 'mode-off') + '">' +
        (enhanced ? '增强' : '本地') + '</span></td>' +
        '<td class="muted small">' + esc(note) + '</td>';
      tb.appendChild(tr);
    });
  }

  function applyState(state) {
    if (!state) { setStatus('状态读取失败'); return; }
    const chooser = $('chooser'), dash = $('dashboard');

    if (state.need_choose) {
      if (chooser) chooser.classList.remove('hidden');
      if (dash) dash.classList.add('hidden');
      setText('appRoot', state.app_root || '');
      paintBadge('待选择数据目录', true);
      setStatus('等待选择数据目录…');
      return;
    }

    if (chooser) chooser.classList.add('hidden');
    if (dash) dash.classList.remove('hidden');

    const s = state.stats || {};
    setText('cardMode', state.mode_text || '—');
    setText('cardItems', s.items != null ? s.items : 0);
    setText('cardPrices', s.prices != null ? s.prices : 0);
    setText('cardPort', (state.api && state.api.running && state.api.port)
      ? state.api.port : (state.port != null ? state.port : '—'));
    setText('dataRoot', state.data_root || '—');
    setText('appRoot2', state.app_root || '—');
    setText('version', 'v' + (state.version || ''));
    paintBadge(state.mode_text || '', false);
    renderPlatforms(state.platforms);

    let line = (state.mode_text || '本地模式') + ' · 数据目录：' +
      (state.data_root || '') + (state.escape_mode ? '（逃生模式）' : '');
    const api = state.api || {};
    line += api.running ? (' · 采集接口 :' + api.port) : ' · 采集接口未运行';
    setStatus(line);
  }

  async function refreshState() {
    try {
      const st = await PL.state();
      applyState(st);
    } catch (e) {
      setStatus('状态读取失败：' + e);
    }
  }

  function refreshItems() {
    if (window.PLItems && typeof window.PLItems.reload === 'function') {
      window.PLItems.reload();
    }
    if (window.PLCapture && typeof window.PLCapture.reload === 'function') {
      window.PLCapture.reload();
    }
  }

  /* ---------- 自动刷新（免手点「刷新」） ---------- */

  let autoTimer = null;

  function canAutoRefresh() {
    if (document.hidden) return false;
    if (document.querySelector('.modal-mask')) return false;
    const ae = document.activeElement;
    if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.tagName === 'SELECT')) {
      return false;
    }
    const chooser = $('chooser');
    if (chooser && !chooser.classList.contains('hidden')) return false;
    return true;
  }

  function autoRefresh() {
    if (!canAutoRefresh()) return;
    refreshState();
    if (window.PLItems && typeof window.PLItems.reload === 'function') {
      window.PLItems.reload();
    }
  }

  function startAutoRefresh() {
    if (autoTimer) return;
    autoTimer = setInterval(autoRefresh, 20000);
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) setTimeout(autoRefresh, 400);
    });
    window.addEventListener('focus', function () { setTimeout(autoRefresh, 400); });
  }

  async function chooseDir(btn) {
    if (btn) btn.disabled = true;
    try {
      const res = await PL.chooseDir();
      if (!res || !res.ok) {
        setChooserMsg((res && res.message) || '已取消', 'err');
        return;
      }
      if (res.state) applyState(res.state);
      setChooserMsg(res.message || '已切换数据目录', 'ok');
      refreshItems();
    } catch (e) {
      setChooserMsg('切换失败：' + e, 'err');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function resetDir(btn) {
    if (btn) btn.disabled = true;
    try {
      const res = await PL.resetDir();
      if (!res || !res.ok) {
        setChooserMsg((res && res.message) || '恢复失败', 'err');
        return;
      }
      if (res.state) applyState(res.state);
      setChooserMsg('已恢复默认数据目录', 'ok');
      refreshItems();
    } catch (e) {
      setChooserMsg('恢复失败：' + e, 'err');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function wire() {
    const bc = $('btnChoose');    if (bc)  bc.addEventListener('click', function () { chooseDir(bc); });
    const br = $('btnRetry');     if (br)  br.addEventListener('click', function () { refreshState(); });
    const bcd = $('btnChangeDir'); if (bcd) bcd.addEventListener('click', function () { chooseDir(bcd); });
    const brd = $('btnResetDir'); if (brd) brd.addEventListener('click', function () { resetDir(brd); });
    document.querySelectorAll('[data-open]').forEach(function (b) {
      b.addEventListener('click', function () { PL.openPath(b.getAttribute('data-open')); });
    });
  }

  window.PLApp = {
    refreshState: refreshState,
    refreshItems: refreshItems,
    refreshAll: function () { refreshState(); refreshItems(); },
  };

  window.addEventListener('error', function (e) {
    const el = $('statusText');
    if (el && (el.textContent === '初始化中…' || !el.textContent)) {
      el.textContent = '界面脚本错误：' + (e.message || '未知');
    }
  });

  function init() {
    wire();
    PL.ready(function () {
      refreshState();
      refreshItems();
      startAutoRefresh();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();