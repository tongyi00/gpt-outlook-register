# ChatGPT 注册结果导入链接生成设计

日期：2026-06-27

## 目标

在 ChatGPT 注册结果表中增加“导入到链接生成”能力。链接生成页改为账号级表格工作台，以账号 email 作为唯一 ID，支持选中账号异步生成支付链接、查看每个账号日志、展示状态机、统计尝试次数和撞链次数，并把最终支付链接回写到 ChatGPT 注册结果表。

## 已确认约束

- 采用独立链接生成账号表，不把任务状态直接混入注册结果表。
- 账号 email 是链接生成队列表唯一 ID。重复导入同一账号不新增重复行。
- ChatGPT 注册结果导入成功后只在当前页提示，不自动跳转到“链接生成”页。
- 链接生成使用“数据导入”页的代理池，也就是现有 `autoProxyPool`。
- 代理检查不计入撞链次数。撞链次数只统计进入 `create_checkout -> stripe_init -> paypal_approve` 付款链路的次数。
- 当前代理不可用时，继续随机探测代理池里的其它代理，直到找到可用代理；整池不可用才进入等待重试。
- 后端线程池默认 `max_workers=10`，不在 UI 暴露线程数。
- 新增“停止次数”，默认 0 表示直至成功；非 0 时按撞链次数达到上限仍未成功则该账号进入 `failed`。

## 数据模型

新增 `session_link_accounts` 表，以 `email` 为主键：

- `email`
- `status`
- `attempts`
- `collision_count`
- `payment_mode`
- `target_amount`
- `stop_after`
- `proxy_used`
- `proxy_url_masked`
- `long_url`
- `error`
- `last_stage`
- `imported_at`
- `started_at`
- `finished_at`
- `updated_at`

新增 `session_link_logs` 表：

- `id`
- `email`
- `created_at`
- `kind`
- `stage`
- `message`

`registered` 表新增 `payment_link` 字段。链接生成成功后同时写入 `session_link_accounts.long_url` 和 `registered.payment_link`。ChatGPT 注册结果表新增“支付链接”列，直接展示该字段。

日志必须脱敏，不写完整 access token，不写完整代理密码。

## 状态机

状态使用机器友好的下划线命名，前端显示中文：

- `pending`
- `check_proxy`
- `create_checkout`
- `stripe_init`
- `paypal_approve`
- `retry_wait`
- `done`
- `failed`
- `stopped`
- `missing_token`

主流程：

```text
pending -> check_proxy -> create_checkout -> stripe_init -> paypal_approve -> done
```

失败重试：

```text
create_checkout/stripe_init/paypal_approve -> retry_wait -> check_proxy -> create_checkout
```

代理池全不可用：

```text
check_proxy -> retry_wait
```

缺少 access token：

```text
pending -> missing_token
```

手动停止：

```text
pending/check_proxy/retry_wait -> stopped
```

正在执行的 HTTP 阶段不能强杀线程，停止请求会设置 stop event；当前步骤返回后不再进入下一轮。

## 撞链次数和停止次数

`collision_count` 在准备进入 `create_checkout` 前加 1。一次撞链覆盖：

- `create_checkout`
- `stripe_init`
- PayPal 模式下的 `paypal_approve`

代理检查失败不增加 `collision_count`。

`stop_after = 0` 表示一直重试直到成功、缺 token、用户停止或账号被删除。`stop_after > 0` 时，如果 `collision_count >= stop_after` 且仍未成功，账号进入 `failed`，错误为“达到停止次数”。

## 后端 API

新增账号级 API：

- `POST /api/session-link/accounts/import-registered`
- `GET /api/session-link/accounts`
- `POST /api/session-link/accounts/run-selected`
- `POST /api/session-link/accounts/stop`
- `POST /api/session-link/accounts/reset`
- `POST /api/session-link/accounts/delete`
- `GET /api/session-link/accounts/{email}/logs`

保留现有 `/api/session-link/payment-modes`，用于支付模式下拉框。

`run-selected` 接收：

- `emails`
- `payment_mode`
- `target_amount`
- `delay_seconds`
- `stop_after`
- `payment_proxy_pool`

执行时后端从 `registered` 读取完整 `access_token`。前端不直接接触 token。

## 前端布局

ChatGPT 注册结果表：

- 工具栏新增 `导入到链接生成`。
- 复用现有勾选逻辑。
- 导入成功后显示导入数量、更新数量、缺 token 数量、跳过数量。
- 新增 `支付链接` 列：无链接显示 `-`；有链接显示复制和打开操作。

链接生成页：

顶部同一行放全局参数和操作：

- 支付模式
- 目标金额
- 失败间隔秒数
- 停止次数
- 刷新
- 执行选中
- 停止
- 重置选中
- 删除选中

中间是账号表格：

- 选择
- 账号
- 当前代理
- 尝试次数
- 撞链次数
- 状态
- 支付模式
- 目标金额
- 最终链接
- 错误
- 更新时间
- 日志

不再显示线程数控件，也不再保留底部操作条。

## 核心代码调整

`webui/session_link.py` 从 token-index 内存循环改为账号级任务控制器。控制器负责：

- 导入注册结果账号
- 代理池随机探测
- 线程池异步执行选中账号
- 状态和日志落库
- 成功后回写 `registered.payment_link`
- 停止事件协作式生效

`session_link_gen/core.py` 需要提供阶段回调，或者新增一个账号级生成函数，围绕现有函数边界更新状态：

- `opll_create_checkout()` 前后更新 `create_checkout`
- `opll_stripe_init()` 前后更新 `stripe_init`
- PayPal 模式下 `opll_stripe_create_paypal_method()`、`opll_stripe_confirm()`、`opll_redirect_url_after_confirm()` 和最终 approve URL 校验归入 `paypal_approve`

非 PayPal 模式不进入 `paypal_approve`，`stripe_init` 成功拿到 hosted link 后直接 `done`。

## 验证计划

- DB 迁移测试：新增表、`registered.payment_link` 字段、重复导入同 email 不产生重复行。
- 状态机测试：缺 token、代理全不可用、成功生成、失败重试、停止次数达到、手动停止。
- 撞链次数测试：代理检查失败不增加；每次进入 `create_checkout` 增加。
- API 测试：导入、列表、执行选中、停止、重置、删除、日志读取。
- 前端静态测试：按钮、字段、表格列、API 绑定、删除旧线程数控件。
- 语法检查：`python -m py_compile`、`node --check`。
- 单测：相关 `unittest` 和现有 test discover。
- 浏览器检查：桌面和移动无 console error、无横向溢出、表格内部滚动。

