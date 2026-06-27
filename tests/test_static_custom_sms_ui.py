import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CustomSmsStaticUiTests(unittest.TestCase):
    def test_custom_sms_pool_has_bulk_selection_and_reset_all_controls(self):
        html = (ROOT / "webui" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "webui" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="customSmsSelectAll"', html)
        self.assertIn('id="btnResetAllCustomSms"', html)
        self.assertIn('id="customSmsSelCount"', html)
        self.assertIn("custom-sms-check", js)
        self.assertIn("/api/settings/sms/custom/accounts/reset_all", js)

    def test_custom_sms_pool_is_data_tab_not_mail_sms_config(self):
        html = (ROOT / "webui" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "webui" / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "webui" / "static" / "style.css").read_text(encoding="utf-8")

        self.assertIn('data-tab="customsms"', html)
        self.assertIn('id="tab-customsms"', html)
        self.assertIn("customsms", js)
        self.assertIn("loadCustomSmsPool", js)

        custom_cfg_start = html.index('id="customSmsCfg"')
        custom_cfg_end = html.index('id="btnSaveSmsCfg"', custom_cfg_start)
        custom_cfg_html = html[custom_cfg_start:custom_cfg_end]
        self.assertNotIn('id="customSmsPoolTable"', custom_cfg_html)
        self.assertNotIn('id="customSmsPoolBody"', custom_cfg_html)

        self.assertIn(".mail-sms-split", css)
        self.assertIn("#customSmsPhoneText", css)
        self.assertIn("#importText", css)

    def test_custom_sms_pool_header_status_labels_and_table_scroll(self):
        html = (ROOT / "webui" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "webui" / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "webui" / "static" / "style.css").read_text(encoding="utf-8")

        custom_start = html.index('id="tab-customsms"')
        custom_end = html.index('id="tab-mailcfg"', custom_start)
        custom_html = html[custom_start:custom_end]

        self.assertNotIn("自定义接码手机号", custom_html)
        self.assertNotIn("<h2>手机号池</h2>", custom_html)
        self.assertNotIn('class="card-head"', custom_html)
        self.assertNotIn('customsms: ["手机号池", "自定义接码手机号状态与操作"]', js)
        self.assertIn('customsms: ["手机号池", ""]', js)
        self.assertIn('class="custom-sms-count-btn"', custom_html)
        self.assertIn('已选 (<span id="customSmsSelCount">0</span>)', custom_html)
        self.assertNotIn("hint inline-hint", custom_html)

        self.assertIn('available: "可用"', js)
        self.assertIn('in_use: "正在使用"', js)
        self.assertIn('done: "已完成"', js)
        self.assertIn('failed: "失败"', js)
        self.assertIn("_customSmsStatusLabel(status)", js)
        self.assertIn("可用 (${counts.available})", js)
        self.assertIn("正在使用 (${counts.in_use})", js)
        self.assertIn("已完成 (${counts.done})", js)
        self.assertIn("失败 (${counts.failed})", js)
        self.assertNotIn("available ${counts.available} / in_use", js)

        self.assertIn("#tab-customsms", css)
        self.assertIn(".content:has(#tab-customsms:not(.hidden))", css)
        self.assertIn("padding: 12px 20px 0;", css)
        self.assertIn(".content:has(#tab-customsms:not(.hidden)),", css)
        self.assertIn(".custom-sms-data-card .custom-sms-pool-wrap", css)
        self.assertIn("overflow-y: auto;", css)
        self.assertIn(".custom-sms-data-card th", css)

    def test_non_data_overview_tabs_hide_stats_bar(self):
        js = (ROOT / "webui" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('const HIDE_STATS_TABS = new Set(["customsms", "sessionlink", "mailcfg", "exportcfg"])', js)
        self.assertIn('$("#statsBar")?.classList.toggle("hidden", HIDE_STATS_TABS.has(tabName))', js)

    def test_business_session_link_tab_exists_in_business_nav(self):
        html = (ROOT / "webui" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "webui" / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "webui" / "static" / "style.css").read_text(encoding="utf-8")

        self.assertIn('<div class="nav-label">业务</div>', html)
        self.assertIn('data-tab="sessionlink"', html)
        self.assertIn("<span>链接生成</span>", html)
        self.assertIn('id="tab-sessionlink"', html)
        self.assertLess(html.index('<div class="nav-label">数据</div>'), html.index('<div class="nav-label">业务</div>'))
        self.assertLess(html.index('<div class="nav-label">业务</div>'), html.index('<div class="nav-label">配置</div>'))

        tab_start = html.index('id="tab-sessionlink"')
        tab_end = html.index('id="tab-mailcfg"', tab_start)
        tab_html = html[tab_start:tab_end]
        self.assertIn('class="card session-link-card"', tab_html)
        self.assertIn('id="sessionLinkStatus"', tab_html)

        self.assertIn('sessionlink: ["链接生成"', js)
        self.assertIn("ensureSessionLinkPolling", js)
        self.assertIn("#tab-sessionlink", css)
        self.assertIn(".session-link-card", css)

    def test_session_link_tab_is_account_workbench(self):
        html = (ROOT / "webui" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "webui" / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "webui" / "static" / "style.css").read_text(encoding="utf-8")

        tab_start = html.index('id="tab-sessionlink"')
        tab_end = html.index('id="tab-mailcfg"', tab_start)
        tab_html = html[tab_start:tab_end]

        for removed in (
            'id="sessionLinkInput"',
            'id="sessionLinkThreadCount"',
            'id="sessionLinkPaymentProxyPool"',
            'id="sessionLinkRunOnce"',
            'id="sessionLinkStart"',
            "生成一次",
            "开始循环直到生成",
        ):
            self.assertNotIn(removed, tab_html)

        for expected in (
            'id="sessionLinkMode"',
            'id="sessionLinkTargetAmount"',
            'id="sessionLinkDelaySeconds"',
            'id="sessionLinkStopAfter"',
            'id="sessionLinkRefresh"',
            'id="sessionLinkRunSelected"',
            'id="sessionLinkStop"',
            'id="sessionLinkResetSelected"',
            'id="sessionLinkDeleteSelected"',
            'id="sessionLinkAccountTable"',
            'id="sessionLinkSelectAll"',
            'id="sessionLinkSelCount"',
            'id="sessionLinkStatus"',
        ):
            self.assertIn(expected, tab_html)

        self.assertIn("账号", tab_html)
        self.assertIn("当前代理", tab_html)
        self.assertIn("尝试次数", tab_html)
        self.assertIn("撞链次数", tab_html)
        self.assertIn("链接生成状态机", tab_html)
        self.assertIn("最终生成的链接", tab_html)
        self.assertIn("日志", tab_html)

        toolbar_start = tab_html.index("session-link-toolbar")
        table_start = tab_html.index('id="sessionLinkAccountTable"')
        toolbar_html = tab_html[toolbar_start:table_start]
        self.assertLess(toolbar_html.index('id="sessionLinkMode"'), toolbar_html.index('id="sessionLinkRefresh"'))
        self.assertLess(toolbar_html.index('id="sessionLinkStopAfter"'), toolbar_html.index('id="sessionLinkRunSelected"'))

        self.assertIn("sessionlink: [\"链接生成\", \"账号级付款链接工作台\"]", js)
        self.assertIn("function loadSessionLinkAccounts", js)
        self.assertIn("let sessionLinkAccountsRequestSeq = 0", js)
        self.assertIn("const requestSeq = ++sessionLinkAccountsRequestSeq", js)
        self.assertIn("if (requestSeq !== sessionLinkAccountsRequestSeq) return", js)
        self.assertIn("function _selectedSessionLinkEmails", js)
        self.assertIn("function renderSessionLinkAccounts", js)
        self.assertIn("function _openSafeHttpUrl", js)
        self.assertIn('if (!["http:", "https:"].includes(parsed.protocol))', js)
        self.assertIn('_openSafeHttpUrl(openBtn.dataset.sessionLinkOpen)', js)
        self.assertNotIn('window.open(openBtn.dataset.sessionLinkOpen', js)
        self.assertIn('api("/api/session-link/accounts"', js)
        self.assertIn('api("/api/session-link/accounts/run-selected"', js)
        self.assertIn('api("/api/session-link/accounts/stop"', js)
        self.assertIn('api("/api/session-link/accounts/reset"', js)
        self.assertIn('api("/api/session-link/accounts/delete"', js)
        self.assertIn('/api/session-link/accounts/${encodeURIComponent(email)}/logs', js)
        self.assertIn('proxy_pool: $("#autoProxyPool").value.trim()', js)
        self.assertNotIn('api("/api/session-link/run-once"', js)
        self.assertNotIn('api("/api/session-link/start"', js)
        self.assertNotIn('api("/api/session-link/status"', js)
        self.assertNotIn("sessionLinkThreadCount", js)

        self.assertIn(".session-link-toolbar", css)
        self.assertIn(".toolbar.session-link-toolbar", css)
        self.assertIn(".session-link-mode-field", css)
        self.assertIn(".session-link-table-panel", css)
        self.assertIn(".session-link-status-chip", css)
        self.assertIn(".session-link-log-modal", css)
        self.assertIn(".session-link-log-modal .session-link-log-row", css)
        self.assertNotIn("\n.session-link-log-row", css)

    def test_data_import_contains_mail_sms_and_proxy_pool_panels(self):
        html = (ROOT / "webui" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "webui" / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "webui" / "static" / "style.css").read_text(encoding="utf-8")

        self.assertIn("<span>数据导入</span>", html)
        self.assertNotIn("<span>邮箱/接码</span>", html)
        self.assertNotIn('data-tab="proxypool"', html)
        self.assertNotIn('id="tab-proxypool"', html)
        self.assertIn('id="tab-mailcfg"', html)
        self.assertIn('id="autoProxyPool"', html)
        self.assertIn('mailcfg: ["数据导入", ""]', js)
        self.assertIn("function setDataImportView", js)
        self.assertIn("dataImportView", js)
        self.assertIn('dataImportView = "proxy"', js)
        self.assertIn(".data-import-shell", css)
        self.assertIn(".data-import-panel", css)

        mailcfg_start = html.index('id="tab-mailcfg"')
        mailcfg_end = html.index('id="tab-exportcfg"', mailcfg_start)
        mailcfg_html = html[mailcfg_start:mailcfg_end]
        self.assertIn('name="dataImportView" value="mail" checked', mailcfg_html)
        self.assertIn('name="dataImportView" value="sms"', mailcfg_html)
        self.assertIn('name="dataImportView" value="proxy"', mailcfg_html)
        self.assertIn('data-import-panel="mail"', mailcfg_html)
        self.assertIn('data-import-panel="sms"', mailcfg_html)
        self.assertIn('data-import-panel="proxy"', mailcfg_html)
        self.assertIn('id="mailSourceSelect"', mailcfg_html)
        self.assertIn('id="smsProviderSelect"', mailcfg_html)
        self.assertIn('id="autoProxyPool"', mailcfg_html)

        register_start = html.index('id="tab-register"')
        register_end = html.index('id="tab-pool"', register_start)
        register_html = html[register_start:register_end]
        self.assertNotIn('id="autoProxyPool"', register_html)

    def test_data_import_panels_are_trimmed_and_controls_are_compact(self):
        html = (ROOT / "webui" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "webui" / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "webui" / "static" / "style.css").read_text(encoding="utf-8")

        mailcfg_start = html.index('id="tab-mailcfg"')
        mailcfg_end = html.index('id="tab-exportcfg"', mailcfg_start)
        mailcfg_html = html[mailcfg_start:mailcfg_end]

        for removed in (
            "<h2>邮箱来源</h2>",
            "OTP 邮件通道",
            "批量导入接码号",
            "每行一个，4 段格式",
            "<h2>SMS 接码</h2>",
            "命中 add-phone",
            "手机验证通道",
            "每行一个手机号和接码 API",
            "+8613800138000",
            "<h3>自定义接码</h3>",
            "手机号----接码API",
            "<h2>代理池</h2>",
            "单个注册 + 自动跑号池共用",
            "每行一个代理",
            "保存于浏览器本地",
        ):
            self.assertNotIn(removed, mailcfg_html)

        self.assertIn('id="importText" rows="8" placeholder="email----password----client_id----refresh_token"', mailcfg_html)
        self.assertIn('type="radio" id="smsEnabled"', mailcfg_html)
        self.assertIn('<option value="custom" selected>自定义</option>', mailcfg_html)
        self.assertIn('<button id="btnCustomSmsImport" class="primary" type="button">导入</button>', mailcfg_html)
        outlook_start = mailcfg_html.index('id="outlookMailCfg"')
        outlook_end = mailcfg_html.index('id="cfTempCfg"', outlook_start)
        outlook_html = mailcfg_html[outlook_start:outlook_end]
        self.assertIn('id="mailSourceSelect"', outlook_html)
        self.assertLess(outlook_html.index('id="mailSourceSelect"'), outlook_html.index('id="importText"'))

        sms_row_start = mailcfg_html.index('class="sms-control-row"')
        sms_row_end = mailcfg_html.index('id="smsBowerCfg"', sms_row_start)
        sms_row_html = mailcfg_html[sms_row_start:sms_row_end]
        self.assertLess(sms_row_html.index('id="smsEnabled"'), sms_row_html.index('id="smsProviderSelect"'))
        self.assertLess(sms_row_html.index('id="smsProviderSelect"'), sms_row_html.index('id="smsCustomRegex"'))

        import_btn_pos = mailcfg_html.index('id="btnCustomSmsImport"')
        save_btn_pos = mailcfg_html.index('id="btnSaveSmsCfg"')
        self.assertLess(import_btn_pos, save_btn_pos)
        self.assertIn('id="btnCustomSmsImport" class="primary"', mailcfg_html)
        self.assertIn('id="btnImport" class="primary"', mailcfg_html)
        self.assertIn('class="btnSaveMailCfg primary"', mailcfg_html)

        self.assertIn(".mail-source-row", css)
        self.assertIn("justify-content: flex-start;", css)
        self.assertIn(".sms-control-row", css)
        self.assertIn(".sms-provider-select", css)
        self.assertIn("width: 150px;", css)
        self.assertIn(".custom-sms-regex-field", css)
        self.assertIn(".sms-enable-radio", css)
        self.assertIn("justify-content: center;", css)
        self.assertIn("border: 0;", css)
        self.assertIn("background: transparent;", css)
        self.assertIn("padding: 12px 20px 0;", css)
        self.assertIn(".data-import-panels > .data-import-panel", css)
        self.assertIn("padding: 20px 20px 0;", css)
        self.assertIn(".content:has(#tab-mailcfg:not(.hidden))", css)
        self.assertIn("padding-bottom: 0;", css)
        self.assertIn(".mail-config-card #outlookMailCfg,", css)
        self.assertIn(".sms-config-card #customSmsCfg", css)
        self.assertIn(".mail-config-card #outlookMailCfg .toolbar", css)
        self.assertIn(".sms-actions", css)
        self.assertIn("position: absolute;", css)
        self.assertIn("bottom: 0;", css)
        self.assertIn("height: 100%;", css)
        self.assertIn("padding-bottom: 56px;", css)
        self.assertNotIn("margin: auto 0 -20px;", css)
        self.assertNotIn("margin: 10px 0 -14px;", css)
        self.assertIn("min-height: 520px;", css)
        self.assertIn("min-height: 500px;", css)
        self.assertIn("min-height: 620px;", css)
        self.assertIn('$("#btnCustomSmsImport")?.classList.toggle("hidden", !isCustom)', js)
        self.assertIn('$(".custom-sms-regex-field")?.classList.toggle("hidden", !isCustom)', js)

    def test_registered_results_live_under_chatgpt_and_nav_is_run_records(self):
        html = (ROOT / "webui" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "webui" / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "webui" / "static" / "style.css").read_text(encoding="utf-8")

        self.assertIn("<span>运行记录</span>", html)
        self.assertIn('registered: ["运行记录"', js)
        self.assertIn("if (tabName === \"register\")", js)
        self.assertIn(".registered-card", css)

        register_start = html.index('id="tab-register"')
        register_end = html.index('id="tab-pool"', register_start)
        register_html = html[register_start:register_end]
        self.assertIn('id="regTable"', register_html)

        records_start = html.index('id="tab-registered"')
        records_end = html.index('id="tab-customsms"', records_start)
        records_html = html[records_start:records_end]
        self.assertIn('id="runTable"', records_html)
        self.assertNotIn('id="regTable"', records_html)

    def test_chatgpt_registered_table_imports_selected_accounts_to_session_link(self):
        html = (ROOT / "webui" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "webui" / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "webui" / "static" / "style.css").read_text(encoding="utf-8")

        register_start = html.index('id="tab-register"')
        register_end = html.index('id="tab-pool"', register_start)
        register_html = html[register_start:register_end]

        self.assertIn('id="btnImportToSessionLink"', register_html)
        self.assertLess(register_html.index('id="btnImportToSessionLink"'), register_html.index('id="btnDeleteSelectedReg"'))
        self.assertIn("<th>支付链接</th>", register_html)
        self.assertLess(register_html.index("<th>refresh_token</th>"), register_html.index("<th>支付链接</th>"))
        self.assertLess(register_html.index("<th>支付链接</th>"), register_html.index("<th>时间</th>"))

        refresh_start = js.index("async function refreshRegistered()")
        refresh_end = js.index('$("#btnRefreshReg")', refresh_start)
        refresh_js = js[refresh_start:refresh_end]
        self.assertIn("r.payment_link", refresh_js)
        self.assertIn("_registeredPaymentLinkHtml(r.payment_link)", refresh_js)
        self.assertIn("const email = escapeHtml(r.email)", refresh_js)
        self.assertNotIn('data-email="${r.email}"', refresh_js)
        self.assertNotIn("<td>${r.email}</td>", refresh_js)
        self.assertIn('data-email="${email}"', refresh_js)
        self.assertIn("<td>${email}</td>", refresh_js)
        self.assertIn("payment-link-cell", js)
        self.assertIn("data-session-link-open", js)
        self.assertIn("data-session-link-copy", js)

        import_start = js.index('$("#btnImportToSessionLink")')
        export_start = js.index("async function _manualExportSelected", import_start)
        import_js = js[import_start:export_start]
        self.assertIn('/api/session-link/accounts/import-registered', import_js)
        self.assertIn("JSON.stringify({ emails })", import_js)
        self.assertIn("_selectedRegEmails()", import_js)
        self.assertIn('$("#btnImportToSessionLink").disabled = true', import_js)
        self.assertIn("_updateSelCountReg()", import_js)
        self.assertNotIn('activateTab("sessionlink")', import_js)
        self.assertNotIn("activateTab('sessionlink')", import_js)

        self.assertIn(".payment-link-cell", css)

    def test_run_records_header_is_trimmed_and_table_scrolls_inside_card(self):
        html = (ROOT / "webui" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "webui" / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "webui" / "static" / "style.css").read_text(encoding="utf-8")

        self.assertNotIn("每条注册流程的执行历史", html)
        self.assertNotIn("每条注册流程的执行历史", js)
        self.assertNotIn("最近执行", html)

        records_start = html.index('id="tab-registered"')
        records_end = html.index('id="tab-customsms"', records_start)
        records_html = html[records_start:records_end]
        title_row_start = records_html.index('class="card-title-row"')
        title_row_end = records_html.index("</div>", title_row_start)
        title_row_html = records_html[title_row_start:title_row_end]
        self.assertIn("<h2>运行记录</h2>", title_row_html)
        self.assertIn('id="btnRefreshRuns"', title_row_html)
        self.assertLess(title_row_html.index("<h2>运行记录</h2>"), title_row_html.index('id="btnRefreshRuns"'))

        self.assertIn("#tab-registered", css)
        self.assertIn(".content:has(#tab-registered:not(.hidden))", css)
        self.assertIn(".run-record-card .table-panel", css)
        self.assertIn("overflow-y: auto;", css)
        self.assertIn(".run-record-card th", css)

    def test_chatgpt_explanatory_hint_rows_removed_and_auto_status_above_controls(self):
        html = (ROOT / "webui" / "static" / "index.html").read_text(encoding="utf-8")

        self.assertNotIn("留空邮箱会自动从号池领取下一个", html)
        self.assertNotIn("多 worker 并发从号池取 available 号注册", html)

        auto_status_pos = html.index('id="autoStatus"')
        auto_controls_pos = html.index('class="auto-control-grid"')
        self.assertLess(auto_status_pos, auto_controls_pos)

    def test_chatgpt_vertical_spacing_and_registered_card_header_trimmed(self):
        html = (ROOT / "webui" / "static" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "webui" / "static" / "style.css").read_text(encoding="utf-8")

        register_start = html.index('id="tab-register"')
        register_end = html.index('id="tab-pool"', register_start)
        register_html = html[register_start:register_end]
        self.assertIn('class="card registered-card"', register_html)
        self.assertNotIn("<h2>注册结果</h2>", register_html)
        self.assertNotIn("已保存凭证", register_html)

        self.assertIn("padding: 0 0 60px;", css)
        self.assertIn("margin-bottom: 0;", css)
        self.assertIn("margin-top: 10px;", css)

    def test_chatgpt_top_cards_are_edge_to_edge_and_compact_inline_fields(self):
        html = (ROOT / "webui" / "static" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "webui" / "static" / "style.css").read_text(encoding="utf-8")

        for text in (
            "留空 = 自动 claim 下一个 available",
            "直连留空；留空时使用数据页代理池",
            "同时跑几个注册流程",
            "每个 worker 跑完一个号的停顿",
            "代理列表已移动到“数据 / 代理池”",
        ):
            self.assertNotIn(text, html)

        self.assertIn("padding: 0 0 60px;", css)
        self.assertIn(".register-card .compact-form label", css)
        self.assertIn(".auto-card .auto-control-grid label", css)
        self.assertIn("grid-template-columns: 92px minmax(0, 1fr);", css)
        self.assertIn("grid-template-columns: 74px minmax(0, 1fr);", css)

    def test_auto_status_summary_and_registered_table_scroll_are_compact(self):
        html = (ROOT / "webui" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "webui" / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "webui" / "static" / "style.css").read_text(encoding="utf-8")

        auto_bar_start = html.index('class="auto-bar"')
        progress_start = html.index('class="progress"', auto_bar_start)
        auto_bar_html = html[auto_bar_start:progress_start]
        self.assertIn('id="autoBatchSummary"', auto_bar_html)
        self.assertIn('id="autoProgressText"', auto_bar_html)

        self.assertIn("const stateNote =", js)
        self.assertIn("auto-status-line", js)
        self.assertNotIn('<br><span class="auto-msg">${escapeHtml(s.last_message || "")}</span>', js)

        self.assertIn(".content:has(#tab-register:not(.hidden))", css)
        self.assertIn(".registered-card .table-panel", css)
        self.assertIn("overflow-y: auto;", css)
        self.assertIn(".registered-card th", css)

    def test_pool_toolbar_is_single_row_and_table_scrolls_inside_card(self):
        html = (ROOT / "webui" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "webui" / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "webui" / "static" / "style.css").read_text(encoding="utf-8")

        pool_start = html.index('id="tab-pool"')
        pool_end = html.index('id="tab-registered"', pool_start)
        pool_html = html[pool_start:pool_end]

        self.assertIn('class="card pool-card"', pool_html)
        self.assertNotIn("<h2>号池管理</h2>", pool_html)
        self.assertNotIn("导入、筛选、重置和删除 Outlook 接码号。", pool_html)
        self.assertNotIn('pool: ["号池管理"', js)
        self.assertIn('pool: ["号池"', js)
        self.assertEqual(pool_html.count('class="toolbar"'), 1)
        self.assertNotIn('class="toolbar compact"', pool_html)

        toolbar_start = pool_html.index('class="toolbar"')
        toolbar_end = pool_html.index('class="table-panel"', toolbar_start)
        toolbar_html = pool_html[toolbar_start:toolbar_end]
        for control_id in (
            "poolFilter",
            "btnRefreshPool",
            "btnResetFailed",
            "btnReleaseStale",
            "btnResetSelected",
            "btnDeleteSelected",
            "bulkDelStatus",
            "btnBulkDelStatus",
            "poolActionResult",
        ):
            self.assertIn(f'id="{control_id}"', toolbar_html)

        self.assertIn("#tab-pool", css)
        self.assertIn(".content:has(#tab-pool:not(.hidden))", css)
        self.assertIn(".pool-card > .toolbar:first-child", css)
        self.assertIn("flex-wrap: nowrap;", css)
        self.assertIn(".pool-card .table-panel", css)
        self.assertIn("overflow-y: auto;", css)
        self.assertIn(".pool-card th", css)


if __name__ == "__main__":
    unittest.main()
