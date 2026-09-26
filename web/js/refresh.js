/* 自动刷新面板（P3.2）：开关 / 节奏与下次时间 / 立即刷新全部 / 最近轮次。 */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const PHASE_NAMES = { hot: '热', focus: '聚焦', normal: '常规', night: '夜间', cold: '冷' };
  const TRIGGER_NAMES = { schedule: '定时', manual: '手动', test: '测试' };

  let watchTimer = null;

  function esc(t) {
    return String(t == null ? '' : t)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function setText(id, text) {
    const el = $(id);
    if (el) el.textContent = String(text == null ? '' : text);
  }

  function setMsg(text, kind) {
    const el = $('rfMsg');
    if (!el) return;
    el.className = 'set-msg' + (kind ? ' ' + kind : '');
    el.textContent = text || '';
  }

  function fmtPhase(st) {
    const phase = String((st && st.phase) || '');
    const name = PHASE_NAMES[phase] || phase || '—';
    const mins = Number((st && st.interval_minutes) || 0);
    return name + (mins > 0 ? '（每 ' + mins + ' 分钟）' : '');
  }

  function summaryText(r) {
    if (!r) return '已刷新';
    if (Number(r.total) === 0 && r.message) return String(r.message);
    return '共 ' + r.total + ' 个：检查成功 ' + r.checked + '，价格变化 ' + r.changed +
      '，新低 ' + r.new_low + '，失败 ' + r.failed;
  }

  function renderRuns(runs) {
    const box = $('rfRuns');
    if (!box) return;
    const list = runs || [];
    if (!list.length) {
      box.innerHTML = '<tr><td colspan="7" class="muted small" ' +
        'style="text-align:center;padding:14px">还没有跑过自动刷新（点「立即刷新全部」试试）</td></tr>';
      return;
    }
    box.innerHTML = list.map(function (r) {
      const when = String(r.finished_at || r.started_at || '').slice(0, 16);
      const trig = TRIGGER_NAMES[r.trigger] || r.trigger || '—';
      return '<tr>' +
        '<td>' + esc(when) + '</td>' +
        '<td>' + esc(trig) + '</td>' +
        '<td class="rf-num">' + esc(r.total) + '</td>' +
        '<td class="rf-num">' + esc(r.changed) + '</td>' +
        '<td class="rf-num">' + esc(r.new_low) + '</td>' +
        '<td class="rf-num">' + esc(r.failed) + '</td>' +
        '<td class="muted small"><span class="rf-msg-cell" title="' + esc(r.message || '') + '">' +
          esc(r.message || '') + '</span></td>' +
        '</tr>';
    }).join('');
  }

  function applyInfo(info) {
    if (!info || !info.ok) {
      setText('rfStateText', '读取失败');
      return false;
    }
    const st = info.status || {};
    const dot = $('rfDot');
    if (dot) dot.className = 'rf-dot ' + (st.busy ? 'warn' : (st.running ? 'on' : 'off'));

    let state = st.busy ? '正在刷新…'
      : (st.running ? (st.enabled ? '运行中' : '已暂停') : '调度器未启动');
    if (info.mock) state += ' · 模拟模式';
    setText('rfStateText', state);

    const toggle = $('rfEnabled');
    if (toggle && document.activeElement !== toggle) toggle.checked = !!st.enabled;
    setText('rfEnabledText', st.enabled ? '已开启' : '已暂停');
    setText('rfPhase', fmtPhase(st));
    setText('rfNext', st.next_at ? ('≈ ' + st.next_at) : '—');

    const hint = $('rfHint');
    if (hint) {
      let text = '';
      if (info.mock) {
        text = '模拟模式：不访问网络，生成的记录都带「模拟演示」备注。';
      } else if (!info.collectors_ready) {
        text = '真实接口将在 P3.3 接入；接入前可设置环境变量 PRICELENS_MOCK=1 体验自动刷新全流程。';
      } else if (!st.enabled) {
        text = '自动刷新已暂停：定时任务不会执行，点「立即刷新全部」仍可手动跑一轮。';
      }
      hint.textContent = text;
    }
    renderRuns(info.runs);
    return true;
  }

  async function load() {
    if (!window.PL || !PL.available()) return;
    try {
      const info = await PL.getRefreshInfo();
      applyInfo(info);
    } catch (e) {
      setText('rfStateText', '读取失败：' + e);
    }
  }

  function watchFinish(before, btn) {
    const deadline = Date.now() + 60000;
    clearInterval(watchTimer);
    watchTimer = setInterval(async function () {
      let info = null;
      try { info = await PL.getRefreshInfo(); } catch (e) { info = null; }
      const st = (info && info.status) || {};
      const last = st.last || null;
      if (last && String(last.finished_at || '') !== String(before || '')) {
        clearInterval(watchTimer); watchTimer = null;
        setMsg(summaryText(last), last.failed ? 'err' : 'ok');
        applyInfo(info);
        if (window.PLItems && window.PLItems.reload) window.PLItems.reload();
        if (window.PLApp && window.PLApp.refreshState) window.PLApp.refreshState();
        if (btn) btn.disabled = false;
        return;
      }
      if (Date.now() > deadline) {
        clearInterval(watchTimer); watchTimer = null;
        setMsg('刷新仍在进行，稍后可点「刷新」查看', '');
        if (btn) btn.disabled = false;
      }
    }, 1500);
  }

  async function doRefreshNow() {
    const btn = $('btnRefreshNow');
    if (btn) btn.disabled = true;
    setMsg('正在触发…', '');
    let before = '';
    try {
      const cur = await PL.getRefreshInfo();
      before = (cur && cur.status && cur.status.last && cur.status.last.finished_at) || '';
    } catch (e) { /* 忽略 */ }
    try {
      const res = await PL.refreshNow();
      if (!res || !res.ok) {
        setMsg((res && res.message) || '触发失败', 'err');
        if (btn) btn.disabled = false;
        return;
      }
      if (res.result) {
        setMsg(summaryText(res.result), res.result.failed ? 'err' : 'ok');
        await load();
        if (window.PLItems && window.PLItems.reload) window.PLItems.reload();
        if (btn) btn.disabled = false;
        return;
      }
      setMsg('已触发，正在刷新…', '');
      watchFinish(before, btn);
    } catch (e) {
      setMsg('触发失败：' + e, 'err');
      if (btn) btn.disabled = false;
    }
  }

  function wire() {
    const toggle = $('rfEnabled');
    if (toggle) {
      toggle.addEventListener('change', async function () {
        const on = toggle.checked;
        toggle.disabled = true;
        try {
          const res = await PL.setRefreshEnabled(on);
          if (!res || !res.ok) {
            setMsg((res && res.message) || '设置失败', 'err');
            toggle.checked = !on;
            return;
          }
          setMsg(res.message || '已更新', 'ok');
          await load();
        } catch (e) {
          setMsg('设置失败：' + e, 'err');
          toggle.checked = !on;
        } finally {
          toggle.disabled = false;
        }
      });
    }
    const btn = $('btnRefreshNow');
    if (btn) btn.addEventListener('click', doRefreshNow);
  }

  function init() {
    wire();
    PL.ready(function () {
      load();
      setInterval(function () { if (!document.hidden) load(); }, 15000);
      document.addEventListener('visibilitychange', function () {
        if (!document.hidden) setTimeout(load, 400);
      });
    });
  }

  window.PLRefresh = { reload: load };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();