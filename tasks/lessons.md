## 2026-06-26

- 失败模式：前端配置页重构时遗留旧表单和重复 ID，容易导致绑定失效或元素冲突。
- 发现信号：需要反复用 `rg` 检查 DOM 引用，且首次补丁容易命中失败。
- 预防规则：先收敛页面结构，再改脚本绑定；任何配置页重构都先做 ID 清单，再一次性替换旧块。

- 失败模式：按“隐藏一个分支”去改 UI 时，误把同级的 SmsBower 高级配置一起删掉。
- 发现信号：用户明确指出“只删自定义接码三个输入”，而页面里其他 SmsBower 项也消失了。
- 预防规则：分支显隐只动目标容器内部节点；先对照原始结构补回完整块，再删目标字段，避免连带删除。

- 失败模式：自动批量控制条的文案和控件布局被拆开，导致用户看到“全自动批量”标题占位。
- 发现信号：用户要求只保留“冷却: 3秒”和“自动跑号池”同一行。
- 预防规则：修改同一行布局时只动当前容器内的直接子元素，先删文案再调整顺序，不额外新增包装层。

- 失败模式：单个注册和自动跑号池复用了同一个“代理池”界面，但请求参数没统一，导致单个注册不会吃代理池。
- 发现信号：用户直接问“我放在代理池的代理，在注册的时候会自动使用吗？”。
- 预防规则：同源 UI 字段要在两个入口都透传，后端统一做最终选择，避免前端/后端分叉。

- 失败模式：用浮点秒 `issued_after` 直接对比只有秒级精度的邮件 `created_at`，同一秒内快速投递的 OTP 会被当成旧邮件跳过。
- 发现信号：第一次等待 180 秒超时，但重发后 5 秒即可从同一个 CF 邮箱拉到验证码。
- 预防规则：跨系统时间过滤要考虑精度差异和记录时机；发码前记录基线，过滤时给低精度时间戳保留边界余量，并用回归测试覆盖同秒边界。

- 失败模式：看到“等待 OTP”就默认是提取逻辑问题，没有先查 CF Worker 实际邮件列表。
- 发现信号：直接查询 `/admin/mails?address=...` 返回 `count=0`，而全局邮件列表存在其他地址的 OTP。
- 预防规则：OTP 等待问题先分层验证：目标邮箱邮件数量、邮件时间、raw 提取结果；只有确认邮件存在但没返回时才改提取/过滤逻辑。

- 失败模式：在函数内 `import urllib.parse` 导致 `urllib` 被 Python 判定为局部变量，curl fallback 的 POST 路径触发 `UnboundLocalError`。
- 发现信号：run 日志显示 `cannot access local variable 'urllib' where it is not associated with a value`。
- 预防规则：已在模块顶层导入包时，不要在函数体内重新导入同一顶级包的子模块；fallback 路径必须有单测覆盖。

- ??????? CF `poll mails=0` ?????????/Worker ??????????? Sentinel ?????
- ????????????? `Sentinel QuickJS ??`?`Sentinel /req ???`?`???? challenge ??`??????????????????
- ?????OTP ????????????????Sentinel ???? challenge ?????????????????? OTP?

- ?????Outlook ??????????????????????? CF ?????????????????????????
- ???????????????? outlook ????????????? CF??????? CF/Outlook ????? OTP ? `/about-you -> create_account`?
- ??????????????????? provider ????? provider ???? provider ????????? provider ???? provider ????????????

- 失败模式：CF Temp Email 自定义域名邮箱在 OTP 验证成功后仍反复排查本地注册链路，忽略了 OpenAI 服务端可能直接禁用自定义域名注册。
- 发现信号：同一流程中 Outlook 邮箱可成功；CF 自定义域名邮箱能收 OTP、能验证、`/about-you` 200，但 `/api/accounts/create_account` 稳定返回 `registration_disallowed`。
- 预防规则：当 `registration_disallowed` 出现在 create_account 阶段且 OTP/Sentinel/session 状态完整时，优先判断邮箱域名/账号信誉/服务端策略；不要再优先改 OTP、Sentinel、reauthorize 或本地 payload。

- 失败模式：给 provider 增加取消信号时直接访问实例属性，测试替身未走 `__init__` 导致 `AttributeError`。
- 发现信号：`tests.test_mail_cf` 中 `FakeCFTempEmailProvider` 调用 `wait_for_otp()` 报缺少 `cancel_event`。
- 预防规则：给长期存在的 provider 增加可选协作属性时使用 `getattr(obj, "field", None)`，保持旧测试替身和外部兼容实现可运行。

- 失败模式：SSE 接口用 `run_in_executor` 包装长时间阻塞的 `queue.get(timeout=30/60)`，浏览器保持页面打开时 Ctrl+C 会被长连接拖住，二次 Ctrl+C 产生 `CancelledError/KeyboardInterrupt` 长栈。
- 发现信号：终端显示 `Waiting for connections to close. (CTRL+C to force quit)`，随后在 Starlette `StreamingResponse` 和 uvicorn shutdown 中抛取消异常。
- 预防规则：SSE/长轮询接口必须使用非阻塞读取 + 短 sleep 心跳，并显式处理 `asyncio.CancelledError`；本地开发启动参数设置较短 `timeout_keep_alive` 和 `timeout_graceful_shutdown`。

- 失败模式：add-phone/send 失败时只向上抛 OpenAI 的泛化 `error.message`，导致日志只看到 `Invalid phone number. Please try again.`，丢失 status、error.code、param、request id 和号码格式线索。
- 发现信号：自定义接码连续换号失败，但日志无法区分是号码格式、号段风控、重复使用还是接口状态问题。
- 预防规则：跨服务接口失败不能只打印 message；至少保留 HTTP 状态、request id、错误 code/param/type、安全 payload 摘要和输入格式诊断，避免下一轮只能猜原因。

- 失败模式：看到诊断提示 `missing_plus_or_country_code` 后只增强日志，没有同步把自动 add-phone/send 请求对齐手动成功请求，导致继续发送裸手机号且缺少 `channel: sms`。
- 发现信号：手动 curl 使用 `{"phone_number":"+19027080724","channel":"sms"}` 可触发正确流程，而自动日志显示 `payload={'phone_number': '19027080724'}`。
- 预防规则：当用户提供手动成功请求时，必须逐项对比 method、URL、payload、关键 headers/cookies 和状态上下文；先修确认的协议差异，再继续排查风控或账号状态。

- 失败模式：代理池只做随机选择或固定分配，没有在使用前探测可用性；代理不可用时可能退化成直连或先占用账号。
- 发现信号：用户追加要求“当前代理不可用，则随机再选，直到选到可用的代理”。
- 预防规则：网络资源池使用前必须做可用性探测；全池不可用时应等待/报错，不能隐式直连，也不能提前 claim 账号。

- 失败模式：只在 SSE generator 内捕获 `asyncio.CancelledError`，没有覆盖 Starlette `StreamingResponse.__call__` 内部 `listen_for_disconnect()` 被 uvicorn shutdown 取消时抛到 ASGI 顶层的异常。
- 发现信号：Ctrl+C 后仍打印 `Cancel 1 running task(s), timeout graceful shutdown exceeded` 和 `Exception in ASGI application ... listen_for_disconnect ... CancelledError`。
- 预防规则：SSE/StreamingResponse 的 shutdown 噪声要在 ASGI 外层和 uvicorn logger 两层兜底；generator 内 try/except 只能处理 body iterator 自身取消，不能覆盖 disconnect listener。

- 失败模式：桌面端合适的悬浮日志窗在移动端默认展开后遮住主要表单和 KPI。
- 发现信号：Playwright 390×844 截图中，日志窗覆盖了 SMS 配置和统计卡片主体。
- 预防规则：悬浮工具窗必须分别验证桌面和移动视口；移动端默认最小化或改成底部抽屉，避免首屏遮挡核心操作。

- 失败模式：根据静态参考稿重构前端时，只抓住主题色和大结构，没有逐项对齐参考稿的首屏坐标、导航入口和卡片内部排布。
- 发现信号：用户指出真实界面和 `Redesign Preview.html` 仍然不一样；截图对比显示 KPI 高度、顶部标题排列、侧边栏入口、自动跑号池配置网格存在偏差。
- 预防规则：参考稿驱动的 UI 重构必须先保存参考/当前截图，并记录关键元素坐标与尺寸；实现后用同一视口复测，不只做肉眼概览。

- 失败模式：按原有 tab 名称保留“注册结果”位置，忽略用户希望在 ChatGPT 主工作流下直接查看结果。
- 发现信号：用户要求把“运行结果”的注册结果放到单个注册和自动跑号池下面，并把菜单改为“运行记录”。
- 预防规则：调整后台信息架构时优先按实际工作流放置数据；菜单名变更要同步页面标题、刷新逻辑和静态回归测试。

- 失败模式：首屏卡片重排后保留了默认页面 padding 和卡片标题区，导致参考截图里的“贴边/紧凑”关系没有对齐。
- 发现信号：用户截图标注统计条需要和顶部、下方主卡片直接衔接，同时要求删除注册结果标题区。
- 预防规则：做后台首屏微调时要量化 topbar、统计条、主卡片之间的 y 轴间距；用户要求删除标题时删除整个 header 容器，不只隐藏文案。

- 失败模式：把大量注册结果行直接放进 ChatGPT 页面，页面整体跟着表格纵向滚动，影响单个注册/自动跑号池的固定操作区。
- 发现信号：用户要求给数据表添加上下滑动条，从而将整个 ChatGPT 页面固定不动。
- 预防规则：主工作台页包含长表格时，外层页面固定、表格容器内部滚动；验证时同时量测外层 `overflow` 和表格 `clientHeight/scrollHeight`。

- 失败模式：把多个工具栏控件合并到同一行时，忽略了通用 `select { width: 100%; margin-top: 5px; }`，导致第一个下拉撑满整行，其他按钮被挤到横向滚动区域外。
- 发现信号：Playwright 截图里号池工具栏只露出“全部”下拉，按钮虽然同一行但不可见；量测显示 toolbar `scrollWidth` 大于 `clientWidth`。
- 预防规则：合并后台工具栏时必须覆盖表单控件的通用宽度和外边距，并用截图验证首屏能看到全部核心操作按钮，不只检查 DOM 顺序。

- 失败模式：数据导入页合并后保留了面板级标题、说明文案和重复字段标签，页面虽然功能正确但没有达到用户要求的极简铺满效果。
- 发现信号：用户继续点名要求删除“邮箱来源 / SMS 接码 / 代理池”等标题说明，并把示例格式压到标题右侧。
- 预防规则：合并配置页后要按可见文案逐项核对用户删除清单；保留功能控件时可以改为无可见标签或紧凑行，但必须用静态搜索和截图双重验证。

- 失败模式：为了让控件等高，给“启用 SMS 接码”加了按钮式边框，同时保留邮箱/接码输入区的 `config-block` 灰色外框，和用户要求的代理池同款输入区不一致。
- 发现信号：用户截图指出启用项“外面还有一个框”，并指出邮箱、接码输入框外层灰框不要。
- 预防规则：做“和某区域一样”的视觉对齐时，必须对比边框、背景、padding 和底部空白四项；不要只对齐高度。

- 失败模式：把“操作行贴底”误当成“输入框底边对齐页面底部”，导致邮箱/接码 textarea 底部仍比号池表格多出一行按钮高度。
- 发现信号：用户要求按照号池中表格数据距离页面底部的距离，重新调整数据导入页三个输入框。
- 预防规则：用户要求对齐另一个页面时，先用 Playwright 量测参考元素的 `getBoundingClientRect()`，再对齐目标元素本身；不要用负 margin 把控件压出可视区。

- 失败模式：手机号池页虽然表格容器使用了 `flex: 1`，但仍保留卡片标题行和 `.content` 默认 60px 底部 padding，导致表格框没有像号池/运行记录一样贴到底部。
- 发现信号：用户要求删除“刷新手机号池”上方的“手机号池”，并把整个输入框拉到最底部；Playwright 量测显示表格容器距视口底部约 75px。
- 预防规则：隐藏统计条的页面要单独检查 `.content` padding 对 `height: 100%` 的影响；做贴底布局时同时量测卡片、工具栏和滚动容器，不只看滚动容器是否 `flex: 1`。
