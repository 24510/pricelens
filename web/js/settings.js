/* 密钥设置面板：自包含实现（顶栏按钮 + 弹窗 + 逻辑）。 */
(function () {
  'use strict';

  const NOTE = '淘宝：无需密钥，保持本地模式即可（P2 将通过浏览器脚本采集）。';

  let mask = null;
  let body = null;

  function esc(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function setMsg(text, cls) {
    const el = document.getElementById('keysMsg');
    if (!el) return;
    el.className = 'set-msg' + (cls ? ' ' + cls : '');
    el.textContent = text || '';
  }

  function buildPanel() {
    if (mask) return;
    mask = document.createElement('div');
    mask.className = 'modal-mask hidden';
    mask.innerHTML =
      '<div class="modal">' +
        '<div class="modal-head">' +
          '<h3>密钥设置 · 增强模式（可选）</h3>' +
          '<button class="modal-close" id="keysClose" title="关闭">✕</button>' +
        '</div>' +
        '<div class="modal-body">' +
          '<div class="set-note">' +
            '不填写也能完整使用：手动记价、价格明细、统计均不受影响。<br/>' +
            '填写后启用对应平台的官方 API 自动刷新（P3 阶段开放）。<br/>' +
            '密钥仅保存在本机 config.ini；界面只显示脱敏值，日志自动脱敏。' +
          '</div>' +
          '<div id="keysBody"><p class="set-note">载入中…</p></div>' +
          '<div class="set-msg" id="keysMsg"></div>' +
        '</div>' +
        '<div class="modal-foot">' +
          '<button class="btn" id="keysReload">重新载入</button>' +
          '<button class="btn" id="keysDone">关闭</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(mask);

    document.getElementById('keysClose').addEventListener('click', closePanel);
    document.getElementById('keysDone').addEventListener('click', closePanel);
    document.getElementById('keysReload').addEventListener('click', loadList);
    mask.addEventListener('click', function (e) { if (e.target === mask) closePanel(); });
    body = document.getElementById('keysBody');
  }

  function openPanel() {
    buildPanel();
    mask.classList.remove('hidden');
    setMsg('', '');
    loadList();
  }

  function closePanel() {
    if (mask) mask.classList.add('hidden');
  }

  function loadList() {
    if (!window.PL || !PL.available()) {
      body.innerHTML = '<p class="set-note">界面桥接尚未就绪，请稍后重试。</p>';
      return;
    }
    body.innerHTML = '<p class="set-note">载入中…</p>';
    PL.getPlatformSettings().then(function (res) {
      if (!res || !res.ok) {
        body.innerHTML = '<p class="set-note">载入失败：' +
          esc((res && res.message) || '未知错误') + '</p>';
        return;
      }
      render(res.platforms || []);
    }).catch(function (err) {
      body.innerHTML = '<p class="set-note">载入失败：' + esc(err) + '</p>';
    });
  }

  function render(platforms) {
    const parts = [];
    platforms.forEach(function (pf) {
      parts.push('<div class="pf-block" data-pf="' + esc(pf.id) + '">');
      parts.push('<h4>' + esc(pf.name) + '</h4>');
      (pf.fields || []).forEach(function (f) {
        const ph = f.filled ? ('已设置：' + f.masked + '（留空则保持不变）') : '未设置';
        parts.push(
          '<div class="pf-field">' +
            '<label>' + esc(f.label) + '</label>' +
            '<input data-key="' + esc(f.key) + '" autocomplete="off" spellcheck="false" ' +
              'placeholder="' + esc(ph) + '"/>' +
            '<span class="pf-status' + (f.filled ? ' ok' : '') + '">' +
              (f.filled ? '已设置' : '未设置') + '</span>' +
          '</div>');
      });
      parts.push(
        '<div class="pf-actions">' +
          '<button class="btn btn-sm btn-primary" data-save="' + esc(pf.id) + '">保存</button>' +
          '<button class="btn btn-sm" data-clear="' + esc(pf.id) + '">清空该平台</button>' +
        '</div>');
      parts.push('</div>');
    });
    parts.push('<p class="set-note">' + esc(NOTE) + '</p>');
    body.innerHTML = parts.join('');

    body.querySelectorAll('[data-save]').forEach(function (btn) {
      btn.addEventListener('click', function () { saveOne(btn.getAttribute('data-save')); });
    });
    body.querySelectorAll('[data-clear]').forEach(function (btn) {
      btn.addEventListener('click', function () { clearOne(btn.getAttribute('data-clear'), btn); });
    });
  }

  function collect(block) {
    const values = {};
    block.querySelectorAll('input[data-key]').forEach(function (inp) {
      const v = inp.value.trim();
      if (v) values[inp.getAttribute('data-key')] = v;
    });
    return values;
  }

  function saveOne(pfId) {
    const block = body.querySelector('.pf-block[data-pf="' + pfId + '"]');
    if (!block) return;
    const values = collect(block);
    if (!Object.keys(values).length) {
      setMsg('请先填写至少一项内容', 'err');
      return;
    }
    setMsg('保存中…', '');
    PL.savePlatformKeys(pfId, values).then(function (res) {
      if (!res || !res.ok) {
        setMsg('保存失败：' + esc((res && res.message) || '未知错误'), 'err');
        return;
      }
      if (res.reloaded) {
        setMsg('已保存，配置已生效，界面即将刷新…', 'ok');
        setTimeout(function () { location.reload(); }, 900);
      } else {
        setMsg('已保存。' + esc(res.message || '重启程序后生效'), 'ok');
        loadList();
      }
    }).catch(function (err) {
      setMsg('保存失败：' + esc(err), 'err');
    });
  }

  function clearOne(pfId, btn) {
    if (btn.getAttribute('data-armed') !== '1') {
      btn.setAttribute('data-armed', '1');
      const old = btn.textContent;
      btn.textContent = '再点一次确认清空';
      setTimeout(function () {
        btn.setAttribute('data-armed', '0');
        btn.textContent = old;
      }, 3000);
      return;
    }
    setMsg('清空中…', '');
    PL.clearPlatformKeys(pfId).then(function (res) {
      if (!res || !res.ok) {
        setMsg('清空失败：' + esc((res && res.message) || '未知错误'), 'err');
        return;
      }
      if (res.reloaded) {
        setMsg('已清空，回到本地模式，界面即将刷新…', 'ok');
        setTimeout(function () { location.reload(); }, 900);
      } else {
        setMsg('已清空。' + esc(res.message || '重启程序后生效'), 'ok');
        loadList();
      }
    }).catch(function (err) {
      setMsg('清空失败：' + esc(err), 'err');
    });
  }

  function init() {
    /* 按钮已写在 index.html 里：直接接线；若缺失则动态补一个 */
    const existing = document.getElementById('btnKeys');
    if (existing) {
      existing.addEventListener('click', openPanel);
      return;
    }
    const right = document.querySelector('.topbar-right');
    if (right) {
      const btn = document.createElement('button');
      btn.id = 'btnKeys';
      btn.className = 'btn btn-sm';
      btn.textContent = '🔑 密钥设置';
      btn.addEventListener('click', openPanel);
      right.insertBefore(btn, right.firstChild);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();