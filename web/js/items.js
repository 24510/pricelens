/* 商品与价格：列表 / 详情 / 添加 / 编辑 / 记价 / 删除 / 导出。 */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);

  const PLATFORM_NAMES = { pdd: '拼多多', jd: '京东', tb: '淘宝' };
  const SOURCE_NAMES = { manual: '手动', script: '脚本', api: '自动' };

  let items = [];
  let selectedPk = null;
  let aiState = { platform: null, itemId: null, url: '' };

  /* ---------- 工具 ---------- */

  function esc(t) {
    return String(t == null ? '' : t)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function fmtPrice(v) {
    if (v === null || v === undefined || v === '') return '—';
    return '¥' + Number(v).toFixed(2);
  }

  function fmtDate(ts) { return ts ? String(ts).slice(0, 10) : '—'; }

  function todayStr() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
  }

  function setHint(t) { const el = $('listHint'); if (el) el.textContent = t || ''; }

  function refreshAllStats() {
    if (window.PLApp && typeof window.PLApp.refreshState === 'function') {
      window.PLApp.refreshState();
    }
  }

  function askConfirm(title, text) {
    return new Promise(function (resolve) {
      const mask = document.createElement('div');
      mask.className = 'modal-mask';
      mask.innerHTML =
        '<div class="modal modal-sm">' +
          '<div class="modal-head"><h3>' + esc(title) + '</h3></div>' +
          '<div class="modal-body"><p class="confirm-text">' + esc(text) + '</p></div>' +
          '<div class="modal-foot">' +
            '<button class="btn" data-act="no">取消</button>' +
            '<button class="btn btn-danger" data-act="yes">确认删除</button>' +
          '</div>' +
        '</div>';
      document.body.appendChild(mask);
      mask.addEventListener('click', function (e) {
        const act = e.target && e.target.getAttribute && e.target.getAttribute('data-act');
        if (act === 'yes') { mask.remove(); resolve(true); }
        else if (act === 'no' || e.target === mask) { mask.remove(); resolve(false); }
      });
    });
  }

  /* ---------- 列表 ---------- */

  function sortItems() {
    items.sort(function (a, b) {
      const ka = String(a.last_at || a.created_at || '');
      const kb = String(b.last_at || b.created_at || '');
      if (ka === kb) return Number(b.id) - Number(a.id);
      return ka < kb ? 1 : -1;
    });
  }

  function renderList() {
    const box = $('itemList');
    if (!box) return;

    if (!items.length) {
      box.innerHTML = '<div class="list-empty">还没有监控的商品<br/>' +
        '<span class="muted small">点右上角「＋ 添加商品」开始</span></div>';
      setHint('');
      return;
    }

    setHint(items.length + ' 个商品');
    box.innerHTML = '';
    items.forEach(function (it) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'item-card' + (Number(it.id) === Number(selectedPk) ? ' active' : '');
      btn.innerHTML =
        '<div class="item-title">' + esc(it.title || '未命名商品') + '</div>' +
        '<div class="item-sub">' +
          '<span class="chip chip-' + esc(it.platform) + '">' +
            esc(PLATFORM_NAMES[it.platform] || it.platform) + '</span>' +
          '<span class="item-price">' + fmtPrice(it.last_price) + '</span>' +
          '<span class="item-count">' + (it.price_count || 0) + ' 条</span>' +
        '</div>';
      btn.addEventListener('click', function () { selectItem(it.id); });
      box.appendChild(btn);
    });
  }

  /* ---------- 详情 ---------- */

  function statBox(label, value, sub, cls) {
    return '<div class="stat">' +
      '<div class="stat-label">' + esc(label) + '</div>' +
      '<div class="stat-value' + (cls ? ' ' + cls : '') + '">' + value + '</div>' +
      '<div class="stat-sub">' + (sub ? esc(sub) : '&nbsp;') + '</div>' +
      '</div>';
  }

  function msg(text, kind) {
    const el = $('detailMsg');
    if (!el) return;
    el.className = 'set-msg' + (kind ? ' ' + kind : '');
    el.textContent = text || '';
  }

  function renderDetail(detail) {
    const box = $('itemDetail');
    if (!box) return;

    if (!detail || !detail.item) {
      box.innerHTML = '<div class="detail-empty">从左侧选择一个商品查看详情</div>';
      return;
    }

    const it = detail.item;
    const st = detail.stats || {};
    const prices = detail.prices || [];
    const minPrice = (st.count > 0 && st.min !== null && st.min !== undefined)
      ? Number(st.min) : null;

    let rows = '';
    if (!prices.length) {
      rows = '<tr><td colspan="5" class="muted small" ' +
        'style="text-align:center;padding:14px">还没有价格记录，用上面的表单记一条吧</td></tr>';
    } else {
      prices.forEach(function (p) {
        const isLow = (minPrice !== null && Number(p.price) === minPrice);
        rows += '<tr>' +
          '<td>' + fmtDate(p.captured_at) + '</td>' +
          '<td class="num">' + fmtPrice(p.price) +
            (isLow ? ' <span class="tag-low">史低</span>' : '') + '</td>' +
          '<td>' + esc(SOURCE_NAMES[p.source] || p.source || '—') + '</td>' +
          '<td class="muted">' + esc(p.note || '') + '</td>' +
          '<td class="row-act"><button class="btn btn-mini btn-danger" data-del="' +
            esc(p.id) + '">删除</button></td>' +
          '</tr>';
      });
    }

    box.innerHTML =
      '<div class="detail-head">' +
        '<div class="detail-title-row">' +
          '<h3>' + esc(it.title || '未命名商品') + '</h3>' +
          '<div class="detail-actions">' +
            (it.url ? '<button class="btn btn-sm" id="btnOpenUrl">打开商品页</button>' : '') +
            '<button class="btn btn-sm" id="btnEditItem">编辑</button>' +
            '<button class="btn btn-sm btn-danger" id="btnDelItem">删除商品</button>' +
          '</div>' +
        '</div>' +
        '<div class="detail-sub">' +
          '<span class="chip chip-' + esc(it.platform) + '">' +
            esc(PLATFORM_NAMES[it.platform] || it.platform) + '</span>' +
          '<code>ID ' + esc(it.item_id) + '</code>' +
          (it.shop ? '<span class="muted small">' + esc(it.shop) + '</span>' : '') +
          (it.note ? '<span class="muted small">备注：' + esc(it.note) + '</span>' : '') +
        '</div>' +
      '</div>' +
      '<div class="stat-row">' +
        statBox('最近价', fmtPrice(st.last), st.last_at ? fmtDate(st.last_at) : '') +
        statBox('最低价', fmtPrice(st.min), '', 'low') +
        statBox('最高价', fmtPrice(st.max), '', 'high') +
        statBox('平均价', (st.avg === null || st.avg === undefined)
          ? '—' : ('¥' + Number(st.avg).toFixed(2)), '') +
        statBox('记录数', String(st.count || 0), '') +
      '</div>' +
      '<div class="chart-box">' +
        '<div class="chart-head">' +
          '<span class="chart-title">价格走势</span>' +
          '<span class="chart-ranges" id="chartRanges"></span>' +
        '</div>' +
        '<div id="pnlChart" class="chart-canvas"></div>' +
      '</div>' +
      '<div class="price-form">' +
        '<div class="pf-item"><label>价格</label>' +
          '<input id="pfPrice" type="number" step="0.01" min="0.01" placeholder="如 129.00"/></div>' +
        '<div class="pf-item"><label>日期</label>' +
          '<input id="pfDate" type="date" value="' + todayStr() + '"/></div>' +
        '<div class="pf-item grow"><label>备注</label>' +
          '<input id="pfNote" type="text" maxlength="60" placeholder="选填，如 大促价"/></div>' +
        '<button class="btn btn-primary" id="btnAddPrice">记录价格</button>' +
      '</div>' +
      '<table class="tbl price-tbl">' +
        '<thead><tr><th>日期</th><th>价格</th><th>来源</th><th>备注</th><th></th></tr></thead>' +
        '<tbody>' + rows + '</tbody>' +
      '</table>' +
      '<div class="set-msg" id="detailMsg"></div>';

    /* 价格曲线 */
    if (window.PLChart && typeof window.PLChart.mount === 'function') {
      try { window.PLChart.mount(prices); } catch (e) { /* 图表失败不影响其他功能 */ }
    }

    const btnAdd = $('btnAddPrice');
    if (btnAdd) btnAdd.addEventListener('click', function () { addPrice(it.id); });
    const btnDel = $('btnDelItem');
    if (btnDel) btnDel.addEventListener('click', function () { removeItem(it); });
    const btnEdit = $('btnEditItem');
    if (btnEdit) btnEdit.addEventListener('click', function () { openEditModal(it); });
    const btnOpen = $('btnOpenUrl');
    if (btnOpen) btnOpen.addEventListener('click', function () { PL.openUrl(it.url); });
    const priceEl = $('pfPrice');
    if (priceEl) {
      priceEl.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') addPrice(it.id);
      });
    }
    const noteEl = $('pfNote');
    if (noteEl) {
      noteEl.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') addPrice(it.id);
      });
    }
    box.querySelectorAll('[data-del]').forEach(function (b) {
      b.addEventListener('click', function () { removePrice(b.getAttribute('data-del')); });
    });
  }

  /* ---------- 数据加载 ---------- */

  async function reload() {
    if (!window.PL || !PL.available()) return;
    try {
      const res = await PL.listItems();
      if (!res || !res.ok) { renderList(); setHint('读取失败'); return; }
      items = res.items || [];
      if (selectedPk && !items.some(function (it) {
        return Number(it.id) === Number(selectedPk);
      })) {
        selectedPk = null;
      }
      sortItems();
      renderList();
      if (selectedPk) await loadDetail(selectedPk);
      else renderDetail(null);
    } catch (e) {
      setHint('读取失败：' + e);
    }
  }

  async function loadDetail(pk) {
    try {
      const res = await PL.getItemDetail(pk);
      if (!res || !res.ok) { renderDetail(null); return; }
      renderDetail(res);
    } catch (e) {
      renderDetail(null);
    }
  }

  function selectItem(pk) {
    selectedPk = pk;
    renderList();
    loadDetail(pk);
  }

  function applyDetail(detail) {
    renderDetail(detail);
    const st = detail.stats || {};
    const it = items.filter(function (x) {
      return Number(x.id) === Number(selectedPk);
    })[0];
    if (it) {
      it.last_price = st.last;
      it.last_at = st.last_at;
      it.price_count = st.count;
    }
    sortItems();
    renderList();
  }

  /* ---------- 记价 / 删除 ---------- */

  async function addPrice(pk) {
    const priceEl = $('pfPrice');
    const dateEl = $('pfDate');
    const noteEl = $('pfNote');
    const price = priceEl ? priceEl.value.trim() : '';
    const dateStr = dateEl ? dateEl.value.trim() : '';
    const note = noteEl ? noteEl.value.trim() : '';

    if (!price) { msg('请先填写价格', 'err'); if (priceEl) priceEl.focus(); return; }

    const btn = $('btnAddPrice');
    if (btn) btn.disabled = true;

    try {
      const res = await PL.addPrice(pk, price, dateStr, note);
      if (!res || !res.ok) { msg((res && res.message) || '保存失败', 'err'); return; }
      if (res.detail && Number(res.detail.item.id) === Number(selectedPk)) {
        applyDetail(res.detail);
      }
      msg('已记录 ' + fmtPrice(price), 'ok');
      refreshAllStats();
    } catch (e) {
      msg('保存失败：' + e, 'err');
    } finally {
      const b = $('btnAddPrice');
      if (b) b.disabled = false;
    }
  }

  async function removePrice(pid) {
    const ok = await askConfirm('删除价格记录', '确定删除这条价格记录吗？此操作不可恢复。');
    if (!ok) return;
    try {
      const res = await PL.deletePrice(pid);
      if (!res || !res.ok) { msg((res && res.message) || '删除失败', 'err'); return; }
      if (res.detail) applyDetail(res.detail);
      msg('已删除该条记录', 'ok');
      refreshAllStats();
    } catch (e) {
      msg('删除失败：' + e, 'err');
    }
  }

  async function removeItem(it) {
    const ok = await askConfirm('删除商品',
      '删除「' + (it.title || '未命名商品') + '」？该商品的 ' + (it.price_count || 0) +
      ' 条价格记录也会一起删除，且不可恢复。');
    if (!ok) return;
    try {
      const res = await PL.deleteItem(it.id);
      if (!res || !res.ok) { msg((res && res.message) || '删除失败', 'err'); return; }
      selectedPk = null;
      await reload();
      refreshAllStats();
    } catch (e) {
      msg('删除失败：' + e, 'err');
    }
  }

  /* ---------- 编辑商品 ---------- */

  function setEdMsg(mask, text, kind) {
    const el = mask.querySelector('#edMsg');
    if (!el) return;
    el.className = 'set-msg' + (kind ? ' ' + kind : '');
    el.textContent = text || '';
  }

  function openEditModal(it) {
    const mask = document.createElement('div');
    mask.className = 'modal-mask';
    mask.innerHTML =
      '<div class="modal modal-sm">' +
        '<div class="modal-head">' +
          '<h3>编辑商品</h3>' +
          '<button class="modal-close" id="edClose" title="关闭">✕</button>' +
        '</div>' +
        '<div class="modal-body">' +
          '<div class="pf-field"><label>商品名称</label>' +
            '<input id="edTitle" maxlength="200"/></div>' +
          '<div class="pf-field"><label>店铺</label>' +
            '<input id="edShop" maxlength="100" placeholder="选填"/></div>' +
          '<div class="pf-field"><label>备注</label>' +
            '<input id="edNote" maxlength="200" placeholder="选填，如 送长辈"/></div>' +
          '<div class="set-msg" id="edMsg"></div>' +
        '</div>' +
        '<div class="modal-foot">' +
          '<button class="btn" id="edCancel">取消</button>' +
          '<button class="btn btn-primary" id="edSave">保存</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(mask);

    mask.querySelector('#edTitle').value = it.title || '';
    mask.querySelector('#edShop').value = it.shop || '';
    mask.querySelector('#edNote').value = it.note || '';

    const close = function () { mask.remove(); };
    mask.querySelector('#edClose').addEventListener('click', close);
    mask.querySelector('#edCancel').addEventListener('click', close);
    mask.addEventListener('click', function (e) { if (e.target === mask) close(); });

    const titleEl = mask.querySelector('#edTitle');
    titleEl.focus();

    mask.querySelector('#edSave').addEventListener('click', async function () {
      const title = titleEl.value.trim();
      if (!title) {
        setEdMsg(mask, '商品名称不能为空', 'err');
        titleEl.focus();
        return;
      }
      const btn = mask.querySelector('#edSave');
      btn.disabled = true;
      setEdMsg(mask, '保存中…', '');
      try {
        const res = await PL.updateItem(it.id, {
          title: title,
          shop: mask.querySelector('#edShop').value.trim(),
          note: mask.querySelector('#edNote').value.trim(),
        });
        if (!res || !res.ok) {
          setEdMsg(mask, (res && res.message) || '保存失败', 'err');
          return;
        }
        mask.remove();
        await reload();
        msg('已保存商品信息', 'ok');
      } catch (e) {
        setEdMsg(mask, '保存失败：' + e, 'err');
      } finally {
        btn.disabled = false;
      }
    });

    titleEl.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') mask.querySelector('#edSave').click();
    });
  }

  /* ---------- 导出 CSV ---------- */

  function setExportMsg(text, kind) {
    const el = $('exportMsg');
    if (!el) return;
    el.className = 'export-msg' + (kind ? ' ' + kind : '');
    el.textContent = text || '';
    el.title = text || '';
  }

  async function doExport() {
    const btn = $('btnExport');
    if (btn) btn.disabled = true;
    setExportMsg('导出中…', '');
    try {
      const res = await PL.exportCsv();
      if (!res || !res.ok) {
        setExportMsg((res && res.message) || '导出失败', 'err');
        return;
      }
      let text = '已导出 ' + res.count + ' 条 → ' + res.path;
      if (res.fallback) text += '（未弹出保存框，已放入 exports 文件夹）';
      setExportMsg(text, 'ok');
    } catch (e) {
      setExportMsg('导出失败：' + e, 'err');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  /* ---------- 添加商品弹窗 ---------- */

  function aiMsg(mask, text, kind) {
    const el = mask.querySelector('#aiMsg');
    if (!el) return;
    el.className = 'set-msg' + (kind ? ' ' + kind : '');
    el.textContent = text || '';
  }

  async function doParse(text, mask) {
    aiState = { platform: null, itemId: null, url: '' };
    const box = mask.querySelector('#aiDetect');
    if (!box) return;

    if (!text || !text.trim()) {
      box.className = 'ai-detect';
      box.textContent = '粘贴商品链接后自动识别平台与商品 ID';
      return;
    }

    box.className = 'ai-detect';
    box.textContent = '识别中…';

    try {
      const res = await PL.parseLink(text.trim());
      if (res && res.ok) {
        aiState = { platform: res.platform, itemId: res.item_id, url: res.url };
        box.className = 'ai-detect ok';
        box.innerHTML = '✅ 已识别：<b>' + esc(res.platform_name) + '</b> · 商品 ID ' +
          '<code>' + esc(res.item_id) + '</code>';
        const pf = mask.querySelector('#aiPlatform');
        if (pf) pf.value = res.platform;
        const ii = mask.querySelector('#aiItemId');
        if (ii) ii.value = res.item_id;
      } else {
        box.className = 'ai-detect err';
        box.textContent = '⚠ ' + ((res && res.message) || '未能识别，请检查链接');
      }
    } catch (e) {
      box.className = 'ai-detect err';
      box.textContent = '⚠ 识别失败：' + e;
    }
  }

  async function submitAdd(mask) {
    const titleEl = mask.querySelector('#aiTitle');
    const shopEl = mask.querySelector('#aiShop');
    const mIdEl = mask.querySelector('#aiItemId');
    const mPfEl = mask.querySelector('#aiPlatform');

    let platform = aiState.platform;
    let itemId = aiState.itemId;
    let url = aiState.url;

    const manualId = (mIdEl && mIdEl.value || '').replace(/\D/g, '');
    if (manualId) {
      platform = mPfEl ? mPfEl.value : platform;
      itemId = manualId;
      url = '';
    }

    if (!platform || !itemId) {
      aiMsg(mask, '请先粘贴可识别的商品链接，或展开「手动指定」填写平台与商品 ID', 'err');
      return;
    }
    const title = (titleEl && titleEl.value || '').trim();
    if (!title) {
      aiMsg(mask, '请填写商品名称', 'err');
      if (titleEl) titleEl.focus();
      return;
    }

    const saveBtn = mask.querySelector('#aiSave');
    if (saveBtn) saveBtn.disabled = true;
    aiMsg(mask, '保存中…');

    try {
      const res = await PL.addItem({
        platform: platform,
        item_id: itemId,
        url: url,
        title: title,
        shop: (shopEl && shopEl.value || '').trim(),
      });
      if (!res || !res.ok) {
        aiMsg(mask, (res && res.message) || '保存失败', 'err');
        return;
      }
      mask.remove();
      selectedPk = res.pk;
      await reload();
      msg(res.created ? '已添加，可以开始记价了' : '该商品已在列表中，已为你选中', 'ok');
      refreshAllStats();
    } catch (e) {
      aiMsg(mask, '保存失败：' + e, 'err');
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  function openAddModal() {
    aiState = { platform: null, itemId: null, url: '' };

    const mask = document.createElement('div');
    mask.className = 'modal-mask';
    mask.innerHTML =
      '<div class="modal">' +
        '<div class="modal-head">' +
          '<h3>添加商品</h3>' +
          '<button class="modal-close" id="aiClose" title="关闭">✕</button>' +
        '</div>' +
        '<div class="modal-body">' +
          '<div class="pf-field"><label>商品链接</label>' +
            '<input id="aiUrl" autocomplete="off" spellcheck="false" ' +
              'placeholder="粘贴链接，自动识别平台与商品 ID"/></div>' +
          '<div class="ai-detect" id="aiDetect">粘贴商品链接后自动识别平台与商品 ID</div>' +
          '<div class="pf-field"><label>商品名称</label>' +
            '<input id="aiTitle" maxlength="200" placeholder="如 某牌空气炸锅 5L"/></div>' +
          '<div class="pf-field"><label>店铺（选填）</label>' +
            '<input id="aiShop" maxlength="100" placeholder="如 某某旗舰店"/></div>' +
          '<div class="ai-manual">' +
            '<a href="#" id="aiManualToggle">识别不了？手动指定平台与 ID</a>' +
            '<div id="aiManual" class="hidden">' +
              '<div class="pf-field"><label>平台</label>' +
                '<select id="aiPlatform">' +
                  '<option value="pdd">拼多多</option>' +
                  '<option value="jd">京东</option>' +
                  '<option value="tb">淘宝</option>' +
                '</select></div>' +
              '<div class="pf-field"><label>商品 ID</label>' +
                '<input id="aiItemId" inputmode="numeric" ' +
                  'placeholder="纯数字，如 100012043978"/></div>' +
            '</div>' +
          '</div>' +
          '<div class="set-msg" id="aiMsg"></div>' +
        '</div>' +
        '<div class="modal-foot">' +
          '<button class="btn" id="aiCancel">取消</button>' +
          '<button class="btn btn-primary" id="aiSave">保存</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(mask);

    const close = function () { mask.remove(); };
    mask.querySelector('#aiClose').addEventListener('click', close);
    mask.querySelector('#aiCancel').addEventListener('click', close);
    mask.addEventListener('click', function (e) { if (e.target === mask) close(); });

    const urlEl = mask.querySelector('#aiUrl');
    let timer = null;
    urlEl.addEventListener('input', function () {
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () { doParse(urlEl.value, mask); }, 320);
    });
    urlEl.focus();

    mask.querySelector('#aiManualToggle').addEventListener('click', function (e) {
      e.preventDefault();
      const blk = mask.querySelector('#aiManual');
      const turnOn = blk.classList.contains('hidden');
      blk.classList.toggle('hidden', !turnOn);
      e.target.textContent = turnOn ? '收起手动指定' : '识别不了？手动指定平台与 ID';
    });

    mask.querySelector('#aiSave').addEventListener('click', function () { submitAdd(mask); });
  }

  /* ---------- 入口 ---------- */

  function init() {
    const btn = $('btnAddItem');
    if (btn) btn.addEventListener('click', openAddModal);
    const ex = $('btnExport');
    if (ex) ex.addEventListener('click', doExport);
    renderList();
    renderDetail(null);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.PLItems = { reload: reload };
})();