/* 与 Python 通信的薄封装（含就绪检测兜底） */
(function () {
  const isReady = () => !!(window.pywebview && window.pywebview.api);

  const ready = (fn) => {
    if (isReady()) { fn(); return; }
    let done = false;
    const run = () => { if (!done) { done = true; fn(); } };
    window.addEventListener('pywebviewready', run);
    let n = 0;
    const timer = setInterval(() => {
      n += 1;
      if (isReady()) { clearInterval(timer); run(); }
      else if (n > 100) { clearInterval(timer); }
    }, 200);
  };

  window.PL = {
    ready,
    available: isReady,

    async ping()      { return window.pywebview.api.ping(); },
    async state()     { return window.pywebview.api.get_state(); },
    async chooseDir() { return window.pywebview.api.choose_data_dir(); },
    async resetDir()  { return window.pywebview.api.reset_data_dir(); },
    async openPath(k) { return window.pywebview.api.open_path(k); },
    async openUrl(u)  { return window.pywebview.api.open_url(u); },

    /* 平台密钥（settings.js 使用） */
    async getPlatformSettings() { return window.pywebview.api.get_platform_settings(); },
    async savePlatformKeys(pf, values) { return window.pywebview.api.save_platform_settings(pf, values); },
    async clearPlatformKeys(pf) { return window.pywebview.api.clear_platform_settings(pf); },

    /* 商品与价格（items.js 使用） */
    async parseLink(text) { return window.pywebview.api.parse_link(text); },
    async listItems() { return window.pywebview.api.list_items(); },
    async addItem(payload) { return window.pywebview.api.add_item(payload); },
    async updateItem(pk, payload) { return window.pywebview.api.update_item(pk, payload); },
    async deleteItem(pk) { return window.pywebview.api.delete_item(pk); },
    async getItemDetail(pk) { return window.pywebview.api.get_item_detail(pk); },
    async addPrice(pk, price, dateStr, note) { return window.pywebview.api.add_price(pk, price, dateStr, note); },
    async deletePrice(pid) { return window.pywebview.api.delete_price(pid); },

    /* 导出（items.js 使用） */
    async exportCsv() { return window.pywebview.api.export_csv(); },

    /* 采集通道（capture.js 使用） */
    async getCaptureInfo() { return window.pywebview.api.get_capture_info(); },
    async generateUserscript() { return window.pywebview.api.generate_userscript(); },
    async testCaptureApi() { return window.pywebview.api.test_capture_api(); },
    async rotateToken() { return window.pywebview.api.rotate_local_token(); },
  };
})();