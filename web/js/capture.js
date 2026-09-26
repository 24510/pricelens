/* 采集通道面板：状态显示 / 一键安装 / 生成脚本 / 自检 / 重置令牌。
   顺带接管「监控商品」右上角的「刷新」按钮。 */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);

  function setMsg(text, kind) {
    const el = $('capMsg');
    if (!el) return;
    el.className = 'set-msg' + (kind ? ' ' + kind : '');
    el.textContent = text || '';
  }

  function setStatus(text, kind) {
    const el = $('capStatus');
    if (!el) return;
    el.textContent = text || '';
    el.style.color = kind === 'ok' ? '#16a34a'
                   : (kind === 'err' ? '#dc2626' : '#64748b');
  }

  async function reload() {
    if (!window.PL || !PL.available()) return;
    try {
      const info = await PL.getCaptureInfo();
      if (!info || !info.ok) {
        setStatus((info && info.message) || '读取失败', 'err');
        return;
      }
      const urlEl = $('capUrl');
      const tokenEl = $('capToken');
      const scriptEl = $('capScript');
      if (urlEl) urlEl.textContent = info.running ? info.url : '未运行';
      if (tokenEl) tokenEl.textContent = info.token_masked || '（未生成）';
      if (scriptEl) {
        scriptEl.textContent = info.script_path +
          (info.script_exists ? '' : '（尚未生成）');
      }
      const installBtn = $('btnCapInstall');
      if (installBtn) {
        installBtn.disabled = !info.running;
        installBtn.title = info.running
          ? ('在浏览器中打开安装页：http://127.0.0.1:' + info.port + '/pricelens.user.js')
          : '采集接口未运行，无法安装';
      }
      if (info.running) {
        setStatus('接口运行中 :' + info.port, 'ok');
        const msgEl = $('capMsg');
        if (msgEl && msgEl.className.indexOf('err') >= 0) setMsg('', '');
      } else {
        setStatus('接口未运行', 'err');
        setMsg(info.error || '采集接口未运行，请重启程序', 'err');
      }
    } catch (e) {
      setStatus('读取失败：' + e, 'err');
    }
  }

  async function doInstall() {
    setMsg('正在打开浏览器安装页…', '');
    try {
      const info = await PL.getCaptureInfo();
      if (!info || !info.ok || !info.running) {
        setMsg('采集接口未运行，无法安装', 'err');
        reload();
        return;
      }
      const url = 'http://127.0.0.1:' + info.port + '/pricelens.user.js';
      const r = await PL.openUrl(url);
      if (r && r.ok) {
        setMsg('已打开浏览器安装页：在页面上点「安装」或「重新安装」即可。' +
               '没弹出时请手动访问：' + url, 'ok');
      } else {
        setMsg('打开浏览器失败，请手动访问：' + url, 'err');
      }
    } catch (e) {
      setMsg('打开失败：' + e, 'err');
    }
  }

  async function doGenerate() {
    const btn = $('btnCapGen');
    if (btn) btn.disabled = true;
    setMsg('生成中…', '');
    try {
      const r = await PL.generateUserscript();
      if (!r || !r.ok) { setMsg((r && r.message) || '生成失败', 'err'); return; }
      setMsg('已生成：' + r.path + '（' + (r.size || 0) + ' 字节）；' +
             '点「一键安装 / 更新脚本」装到浏览器', 'ok');
      reload();
    } catch (e) {
      setMsg('生成失败：' + e, 'err');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function doTest() {
    const btn = $('btnCapTest');
    if (btn) btn.disabled = true;
    setMsg('自检中…', '');
    try {
      const r = await PL.testCaptureApi();
      setMsg((r && r.message) || '自检无响应', (r && r.ok) ? 'ok' : 'err');
    } catch (e) {
      setMsg('自检失败：' + e, 'err');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function doRotate(btn) {
    if (btn.getAttribute('data-armed') !== '1') {
      btn.setAttribute('data-armed', '1');
      const old = btn.textContent;
      btn.textContent = '再点一次确认重置';
      setTimeout(function () {
        btn.setAttribute('data-armed', '0');
        btn.textContent = old;
      }, 3000);
      return;
    }
    btn.setAttribute('data-armed', '0');
    setMsg('重置中…', '');
    try {
      const r = await PL.rotateToken();
      setMsg((r && r.message) || '', (r && r.ok) ? 'ok' : 'err');
      reload();
    } catch (e) {
      setMsg('重置失败：' + e, 'err');
    }
  }

  function wireRefreshButton() {
    const rb = $('btnRefreshItems');
    if (!rb) return;
    rb.addEventListener('click', function () {
      if (window.PLItems && typeof window.PLItems.reload === 'function') {
        window.PLItems.reload();
      }
      if (window.PLApp && typeof window.PLApp.refreshState === 'function') {
        window.PLApp.refreshState();
      }
    });
  }

  function init() {
    const ins = $('btnCapInstall');
    if (ins) ins.addEventListener('click', doInstall);
    const gen = $('btnCapGen');
    if (gen) gen.addEventListener('click', doGenerate);
    const open = $('btnCapOpen');
    if (open) open.addEventListener('click', function () { PL.openPath('userscript'); });
    const test = $('btnCapTest');
    if (test) test.addEventListener('click', doTest);
    const rot = $('btnCapRotate');
    if (rot) rot.addEventListener('click', function () { doRotate(rot); });
    wireRefreshButton();
    reload();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.PLCapture = { reload: reload };
})();