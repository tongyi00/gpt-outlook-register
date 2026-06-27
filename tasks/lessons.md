# Lessons

## 2026-06-27: FastAPI 路由函数名复查

- Failure mode: API 测试只直接调用 handler 函数，未检查 FastAPI route endpoint，导致 `/api/session-link/accounts/stop` 绑定的函数名与计划要求不一致。
- Detection signal: spec reviewer 对比任务文本时发现 account stop 路由实现为 `api_session_link_accounts_stop()`，而计划要求 `api_session_link_stop()`。
- Prevention rule: 新增或改名 FastAPI 路由时，测试同时断言 URL path 绑定到预期 endpoint，再通过 endpoint 调用验证控制器转发。

## 2026-06-27: innerHTML 表格动态字段转义

- Failure mode: 在 `refreshRegistered()` 的模板字符串里新增列时，只转义了新增的 payment link，忽略了同一行既有 `r.email` 仍直接进入文本节点和 `data-email` 属性。
- Detection signal: code quality review 以 XSS/escaping 为重点检查 Task 5 diff，指出 email 可破坏 HTML 属性或注入节点。
- Prevention rule: 修改 `innerHTML` 表格行时，同一模板内所有动态字段都要统一转义；测试至少断言关键字段通过 `escapeHtml()` 或 DOM API 写入。

## 2026-06-27: 前端轮询与危险链接

- Failure mode: 账号工作台列表轮询请求与删除/重置后的刷新请求可并发返回，旧响应可能覆盖新 UI；同时“打开链接”直接调用 `window.open()`，未限制 URL scheme。
- Detection signal: code quality review 构造旧轮询晚返回和恶意 `long_url` 场景，指出 stale UI 回滚和危险 scheme 打开风险。
- Prevention rule: 轮询列表渲染必须使用 request sequence 或 AbortController，只允许最新请求落 UI；用户可点击打开的 URL 统一经 http/https scheme 校验函数。

## 2026-06-27: 紧凑工具栏控件宽度

- Failure mode: 链接生成页工具栏复用了通用 `.toolbar`，字段宽度不足时长支付模式选择框会视觉上挤压后续字段。
- Detection signal: Playwright 截图肉眼检查发现桌面工具栏中“支付模式”和“目标金额”区域有重叠风险。
- Prevention rule: 横向工具栏中存在长选项 select 时，要给 label/field 设置稳定宽度，并用更高优先级规则覆盖通用 toolbar 的 margin/wrap。

## 2026-06-27: 撞链重试不能重复代理检查

- Failure mode: 账号链接生成循环把代理检查放在每次重试顶部，导致撞链失败后重新进入 `check_proxy` 并再次探测代理池。
- Detection signal: 最终复查对照用户要求“撞链只重复 create_checkout 到 paypal_approve”时，发现当前实现每轮都会调用 `pick_random_usable_proxy()`。
- Prevention rule: 对多阶段状态机需求，要给“不会重复发生”的阶段写负向回归测试，例如断言撞链重试时代理选择只调用一次。
