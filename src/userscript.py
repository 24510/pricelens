# -*- coding: utf-8 -*-
"""一键记价用户脚本：生成内嵌本机令牌的 Tampermonkey 脚本。"""
from __future__ import annotations

from pathlib import Path

from const import APP_NAME, DIR_USERSCRIPT

SCRIPT_FILENAME = "pricelens.user.js"

_TEMPLATE = r"""// ==UserScript==
// @name         PriceLens 一键记价
// @namespace    pricelens.local
// @version      __VERSION__
// @description  在商品页一键把当前价格记录到本地 PriceLens（令牌已内嵌）
// @author       PriceLens
// @match        https://mobile.yangkeduo.com/*
// @match        https://*.yangkeduo.com/*
// @match        https://*.pinduoduo.com/*
// @match        https://item.jd.com/*
// @match        https://item.m.jd.com/*
// @match        https://item.taobao.com/*
// @match        https://detail.tmall.com/*
// @match        https://*.tmall.com/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @run-at       document-idle
// @noframes
// ==/UserScript==

(function () {
  'use strict';

  var TOKEN = '__TOKEN__';
  var PORT = __PORT__;
  var APP = '__APPNAME__';
  var BASE = 'http://127.0.0.1:' + PORT;

  var PLATFORM_NAMES = { pdd: '拼多多', jd: '京东', tb: '淘宝' };
  var AUTO_KEY = 'pl_auto_enabled';

  var current = null;
  var panel = null;
  var els = {};
  var dupGuard = { at: 0, key: '' };

  var autoEnabled = true;
  try { autoEnabled = localStorage.getItem(AUTO_KEY) !== '0'; } catch (e) { autoEnabled = true; }
  var autoGuard = { key: '', at: 0 };
  var autoTimer = null;
  var autoTry = 0;

  /* ---------- 识别商品 ---------- */

  function detectTarget() {
    var host = (location.hostname || '').toLowerCase();
    var platform = null;
    if (/(^|\.)yangkeduo\.com$/.test(host) || /(^|\.)pinduoduo\.com$/.test(host)) {
      platform = 'pdd';
    } else if (/(^|\.)jd\.com$/.test(host) || /(^|\.)jd\.hk$/.test(host)) {
      platform = 'jd';
    } else if (/(^|\.)taobao\.com$/.test(host) || /(^|\.)tmall\.com$/.test(host)) {
      platform = 'tb';
    }
    if (!platform) return null;

    var url = location.href;
    var m = null;
    var id = null;
    if (platform === 'pdd') {
      m = url.match(/[?&]goods_id=(\d+)/);
      if (m) id = m[1];
    } else if (platform === 'jd') {
      m = url.match(/\/(\d{6,})\.html/);
      if (m) id = m[1];
      if (!id) { m = url.match(/\/product\/(\d{6,})/); if (m) id = m[1]; }
    } else {
      m = url.match(/[?&](?:id|itemId|item_id)=(\d+)/);
      if (m) id = m[1];
    }
    if (!id) return null;
    return { platform: platform, item_id: id, url: url };
  }

  /* ---------- 取价 ---------- */

  function cleanText(t) {
    return String(t == null ? '' : t).replace(/\s+/g, ' ').trim();
  }

  function toNumber(t) {
    var m = String(t == null ? '' : t).match(/(\d+(?:\.\d{1,2})?)/);
    if (!m) return null;
    var v = parseFloat(m[1]);
    if (isNaN(v) || v <= 0 || v > 10000000) return null;
    return Math.round(v * 100) / 100;
  }

  function fromMeta() {
    var sel = ['meta[property="og:price:amount"]', 'meta[itemprop="price"]',
               'meta[property="product:price:amount"]'];
    for (var i = 0; i < sel.length; i++) {
      var el = document.querySelector(sel[i]);
      if (el) {
        var v = toNumber(el.getAttribute('content'));
        if (v) return { value: v, from: '页面元数据' };
      }
    }
    return null;
  }

  function fromJsonLd() {
    var nodes = document.querySelectorAll('script[type="application/ld+json"]');
    for (var i = 0; i < nodes.length; i++) {
      var data = null;
      try { data = JSON.parse(nodes[i].textContent || '{}'); } catch (e) { continue; }
      var list = Object.prototype.toString.call(data) === '[object Array]' ? data : [data];
      for (var j = 0; j < list.length; j++) {
        var offers = list[j] ? list[j].offers : null;
        if (!offers) continue;
        if (Object.prototype.toString.call(offers) !== '[object Array]') offers = [offers];
        for (var k = 0; k < offers.length; k++) {
          var cand = offers[k] || {};
          var v = toNumber(cand.price) ||
                  toNumber(cand.priceSpecification && cand.priceSpecification.price) ||
                  toNumber(cand.lowPrice);
          if (v) return { value: v, from: '结构化数据' };
        }
      }
    }
    return null;
  }

  var PRICE_SELECTORS = {
    pdd: ['[class*="goodsPrice"]', '[class*="price"] [class*="price"]', '.price'],
    jd: ['.p-price .price', '.summary-price .price', '#jd-price', '.price'],
    tb: ['#J_StrPriceModBox .tb-rmb-num', '#J_PromoPriceNum', '.tb-rmb-num',
         '#J_StrPrice .tb-rmb-num', '.tm-price']
  };

  function fromSelectors(platform) {
    var list = PRICE_SELECTORS[platform] || [];
    for (var i = 0; i < list.length; i++) {
      var nodes = document.querySelectorAll(list[i]);
      for (var j = 0; j < nodes.length; j++) {
        var el = nodes[j];
        if (!el || !cleanText(el.textContent)) continue;
        var v = toNumber(el.textContent);
        if (v) return { value: v, from: '页面价格元素' };
      }
    }
    return null;
  }

  function fromBody() {
    var text = (document.body && document.body.innerText) ? document.body.innerText : '';
    var m = text.match(/[¥￥]\s*(\d+(?:\.\d{1,2})?)/);
    if (m) {
      var v = toNumber(m[1]);
      if (v) return { value: v, from: '页面文本（请核对）' };
    }
    return null;
  }

  function extractPrice(platform) {
    return fromMeta() || fromJsonLd() || fromSelectors(platform) || fromBody() || null;
  }

  function extractTitle() {
    var og = document.querySelector('meta[property="og:title"]');
    var t = og ? og.getAttribute('content') : '';
    if (!t) t = document.title || '';
    t = cleanText(t).replace(/\s*[-_|]\s*(拼多多|京东|淘宝|天猫|手机版).*$/, '');
    return t.slice(0, 100);
  }

  /* ---------- 请求（GM 优先，fetch 兜底） ---------- */

  function pickGm() {
    if (typeof GM_xmlhttpRequest === 'function') return GM_xmlhttpRequest;
    if (typeof GM !== 'undefined' && GM && typeof GM.xmlHttpRequest === 'function') {
      return function (opts) { return GM.xmlHttpRequest(opts); };
    }
    return null;
  }

  function request(method, url, payload, cb) {
    var body = payload ? JSON.stringify(payload) : null;
    var headers = { 'Content-Type': 'application/json' };
    if (TOKEN) headers['X-PL-Token'] = TOKEN;

    var gm = pickGm();
    if (gm) {
      gm({
        method: method, url: url, headers: headers, data: body, timeout: 8000,
        onload: function (r) {
          var js = null;
          try { js = JSON.parse(r.responseText); } catch (e) { js = null; }
          cb(r.status, js);
        },
        onerror: function () { cb(0, null); },
        ontimeout: function () { cb(-1, null); }
      });
      return;
    }
    var opt = { method: method, headers: headers };
    if (body) opt.body = body;
    fetch(url, opt).then(function (r) {
      r.json().then(function (js) { cb(r.status, js); },
                   function () { cb(r.status, null); });
    }, function () { cb(0, null); });
  }

  /* ---------- 界面 ---------- */

  function styleOf(el, css) {
    for (var k in css) {
      if (Object.prototype.hasOwnProperty.call(css, k)) el.style[k] = css[k];
    }
    return el;
  }

  function setMsg(text, kind) {
    if (!els.msg) return;
    els.msg.textContent = text || '';
    els.msg.style.color = kind === 'ok' ? '#16a34a'
                        : (kind === 'err' ? '#dc2626' : '#475569');
  }

  function buildPanel() {
    var box = document.createElement('div');
    box.id = 'pricelens-panel';
    styleOf(box, {
      position: 'fixed', right: '18px', bottom: '18px', zIndex: '2147483000',
      width: '268px', background: '#ffffff', border: '1px solid #e5e7eb',
      borderRadius: '12px', boxShadow: '0 10px 30px rgba(15,23,42,.18)',
      fontFamily: 'Microsoft YaHei, Arial, sans-serif', fontSize: '12px',
      color: '#0f172a', overflow: 'hidden'
    });

    var head = document.createElement('div');
    styleOf(head, {
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '8px 10px', background: '#f8fafc', borderBottom: '1px solid #eef2f7'
    });
    var title = document.createElement('span');
    title.textContent = '📌 ' + APP + ' 一键记价';
    styleOf(title, { fontWeight: '600' });
    var minBtn = document.createElement('button');
    minBtn.type = 'button';
    minBtn.textContent = '—';
    styleOf(minBtn, { border: '0', background: 'transparent', cursor: 'pointer',
      fontSize: '14px', lineHeight: '1', color: '#64748b' });
    head.appendChild(title);
    head.appendChild(minBtn);

    var body = document.createElement('div');
    styleOf(body, { padding: '10px' });

    var status = document.createElement('div');
    styleOf(status, { marginBottom: '8px', color: '#64748b' });
    status.textContent = '连接中…';

    var row1 = document.createElement('div');
    styleOf(row1, { display: 'flex', gap: '6px', alignItems: 'center' });

    var priceInput = document.createElement('input');
    priceInput.type = 'text';
    priceInput.placeholder = '价格';
    styleOf(priceInput, { flex: '1', minWidth: '0', padding: '6px 8px',
      border: '1px solid #cbd5e1', borderRadius: '8px', fontSize: '13px' });

    var saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.textContent = '记录';
    styleOf(saveBtn, { border: '0', background: '#f97316', color: '#fff',
      padding: '7px 14px', borderRadius: '8px', cursor: 'pointer', fontSize: '13px',
      fontWeight: '600' });

    var pickBtn = document.createElement('button');
    pickBtn.type = 'button';
    pickBtn.textContent = '重取';
    styleOf(pickBtn, { border: '1px solid #cbd5e1', background: '#fff', color: '#475569',
      padding: '6px 8px', borderRadius: '8px', cursor: 'pointer', fontSize: '12px' });

    row1.appendChild(priceInput);
    row1.appendChild(saveBtn);
    row1.appendChild(pickBtn);

    var autoRow = document.createElement('label');
    styleOf(autoRow, { display: 'flex', alignItems: 'center', gap: '6px',
      marginTop: '8px', color: '#475569', cursor: 'pointer' });
    var autoChk = document.createElement('input');
    autoChk.type = 'checkbox';
    autoChk.checked = !!autoEnabled;
    styleOf(autoChk, { margin: '0', cursor: 'pointer' });
    var autoTxt = document.createElement('span');
    autoTxt.textContent = '自动记录（监控中商品 · 价格变化时）';
    autoRow.appendChild(autoChk);
    autoRow.appendChild(autoTxt);

    var noteInput = document.createElement('input');
    noteInput.type = 'text';
    noteInput.maxLength = 60;
    noteInput.placeholder = '备注（选填，如 大促价）';
    styleOf(noteInput, { width: '100%', boxSizing: 'border-box', marginTop: '6px',
      padding: '6px 8px', border: '1px solid #cbd5e1', borderRadius: '8px',
      fontSize: '12px' });

    var info = document.createElement('div');
    styleOf(info, { marginTop: '8px', color: '#94a3b8', lineHeight: '1.6' });

    var msg = document.createElement('div');
    styleOf(msg, { marginTop: '6px', lineHeight: '1.6', minHeight: '16px' });

    body.appendChild(status);
    body.appendChild(row1);
    body.appendChild(autoRow);
    body.appendChild(noteInput);
    body.appendChild(info);
    body.appendChild(msg);

    box.appendChild(head);
    box.appendChild(body);
    document.body.appendChild(box);

    els = { box: box, body: body, status: status, price: priceInput,
            note: noteInput, save: saveBtn, pick: pickBtn, info: info, msg: msg,
            autoChk: autoChk };

    minBtn.addEventListener('click', function () {
      var hidden = els.body.style.display === 'none';
      els.body.style.display = hidden ? 'block' : 'none';
      minBtn.textContent = hidden ? '—' : '＋';
    });
    saveBtn.addEventListener('click', submit);
    pickBtn.addEventListener('click', function () { fillPrice(true); });
    priceInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') submit();
    });
    autoChk.addEventListener('change', function () {
      autoEnabled = !!autoChk.checked;
      try { localStorage.setItem(AUTO_KEY, autoEnabled ? '1' : '0'); } catch (e) { }
      if (autoEnabled) scheduleAuto();
    });
    return box;
  }

  function fillPrice(force) {
    if (!current) return null;
    var got = extractPrice(current.platform);
    var t = '商品：' + (extractTitle() || '（未取到名称）');
    if (got) {
      if (force || !els.price.value) els.price.value = got.value.toFixed(2);
      els.info.textContent = t + '（取价：' + got.from + '）';
      return got;
    }
    els.info.textContent = t + '（未自动取到价格，请手动填写）';
    return null;
  }

  function checkConnection() {
    if (!els.status) return;
    els.status.textContent = '正在检测接口…';
    els.status.style.color = '#64748b';
    request('GET', BASE + '/api/ping', null, function (status, res) {
      if (status === 200 && res && res.ok) {
        els.status.textContent = '● 已连接 ' + BASE;
        els.status.style.color = '#16a34a';
      } else {
        els.status.textContent = '○ 未连接（请先启动 PriceLens）';
        els.status.style.color = '#dc2626';
      }
    });
  }

  /* ---------- 自动记录 ---------- */

  function scheduleAuto() {
    if (!autoEnabled || !current) return;
    if (autoTimer) { clearTimeout(autoTimer); autoTimer = null; }
    autoTry = 0;
    autoTimer = setTimeout(attemptAuto, 2500);
  }

  function attemptAuto() {
    autoTimer = null;
    if (!autoEnabled || !current) return;

    var got = extractPrice(current.platform);
    if (!got) {
      if (autoTry < 2) {
        autoTry += 1;
        autoTimer = setTimeout(attemptAuto, 2500);
      }
      return;
    }

    var key = current.platform + '/' + current.item_id + '/' + got.value;
    var now = Date.now();
    if (autoGuard.key === key && now - autoGuard.at < 60000) return;
    autoGuard.key = key;
    autoGuard.at = now;

    request('POST', BASE + '/api/report', {
      platform: current.platform,
      item_id: current.item_id,
      price: got.value,
      title: extractTitle(),
      url: location.href,
      mode: 'auto'
    }, function (status, res) {
      if (status === 401) {
        setMsg('令牌不匹配：请在 PriceLens 里重置令牌并重新安装脚本', 'err');
        return;
      }
      if (!res || !res.ok) return;

      if (res.skipped) {
        if (res.reason === 'unchanged') {
          setMsg('ℹ 价格未变化（¥' + Number(got.value).toFixed(2) + '），未记录', '');
        } else if (res.reason === 'unknown') {
          setMsg('ℹ 该商品尚未监控：点「记录」可加入监控', '');
        }
        return;
      }

      var line = '已自动记录 ¥' + Number(got.value).toFixed(2);
      if (res.stats && res.stats.min != null && res.stats.last != null &&
          Math.abs(Number(res.stats.min) - Number(res.stats.last)) < 0.005) {
        line += ' · 史低 ✓';
      }
      setMsg(line, 'ok');
    });
  }

  /* ---------- 手动记录 ---------- */

  function submit() {
    if (!current) { setMsg('当前页面无法识别商品', 'err'); return; }
    var v = toNumber(els.price.value.trim());
    if (!v) { setMsg('请填写有效价格', 'err'); els.price.focus(); return; }

    var key = current.platform + '/' + current.item_id + '/' + v;
    var now = Date.now();
    if (dupGuard.key === key && now - dupGuard.at < 5000) return;
    dupGuard.key = key;
    dupGuard.at = now;

    els.save.disabled = true;
    els.save.textContent = '记录中…';
    setMsg('正在发送…', '');

    request('POST', BASE + '/api/report', {
      platform: current.platform,
      item_id: current.item_id,
      price: v,
      title: extractTitle(),
      url: location.href,
      note: els.note.value.trim(),
      mode: 'manual'
    }, function (status, res) {
      els.save.disabled = false;
      els.save.textContent = '记录';
      if (status === 200 && res && res.ok) {
        var line = res.message || '已记录';
        if (res.stats && res.stats.last != null) {
          line += ' · 当前 ¥' + Number(res.stats.last).toFixed(2);
        }
        if (res.stats && res.stats.min != null && res.stats.last != null &&
            Math.abs(Number(res.stats.min) - Number(res.stats.last)) < 0.005) {
          line += ' · 史低 ✓';
        }
        setMsg(line, 'ok');
        els.note.value = '';
      } else if (status === 401) {
        setMsg('令牌不匹配：请在 PriceLens 里重置令牌并重新安装脚本', 'err');
      } else if (status === 0 || status === -1) {
        setMsg('连不上 PriceLens：请确认程序正在运行（端口 ' + PORT + '）', 'err');
      } else {
        setMsg((res && res.message) || ('记录失败（HTTP ' + status + '）'), 'err');
      }
    });
  }

  /* ---------- 启动 ---------- */

  function tick() {
    var t = detectTarget();
    if (!t) return;
    var changed = !current || t.item_id !== current.item_id ||
                  t.platform !== current.platform || !panel;
    if (!changed) return;
    current = t;
    if (!panel) panel = buildPanel();
    els.status.textContent = '商品：' + PLATFORM_NAMES[current.platform] +
                             ' ' + current.item_id;
    els.status.style.color = '#64748b';
    setMsg('', '');
    fillPrice(true);
    checkConnection();
    if (autoEnabled) scheduleAuto();
  }

  function init() {
    tick();
    setInterval(tick, 1500);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
"""


def build_script(token: str, port: int, version: str) -> str:
    """生成最终脚本内容（替换占位符）。"""
    js = _TEMPLATE
    js = js.replace("__TOKEN__", token or "")
    js = js.replace("__PORT__", str(int(port)))
    js = js.replace("__VERSION__", version or "0.1.0")
    js = js.replace("__APPNAME__", APP_NAME)
    return js


def write_script(data_root: Path, token: str, port: int, version: str) -> Path:
    """把脚本写入 <数据根>\\userscript\\pricelens.user.js。"""
    out_dir = Path(data_root) / DIR_USERSCRIPT
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / SCRIPT_FILENAME
    path.write_text(build_script(token, port, version),
                    encoding="utf-8", newline="\n")
    return path