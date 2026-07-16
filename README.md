# PayPal 协议支付网页端（公开发布版）

这是公开发布版：网页端直接可用，不需要任何授权绑定步骤。

## 启动

```bash
python -m pip install -r requirements.txt
python web.py --host 0.0.0.0 --port 8080
```

然后打开：`http://服务器IP:8080`。

本机测试也可以使用：

```bash
python web.py --host 127.0.0.1 --port 8080
```

打开：<http://127.0.0.1:8080>

Windows 下也可以直接双击根目录 `start.bat` 一键启动。脚本会自动创建或复用 `.venv`、安装依赖、打开浏览器并启动网页端；可通过 `PAYPAL_WEB_HOST`、`PAYPAL_WEB_PORT` 覆盖默认监听地址和端口。详见 `docs/start-bat.md`。

## 功能

- 直接输入 `BA Token`、手机号、最大换卡次数后启动任务。
- 支持 `BR`、`US`、`BA` 三个支付地区；`BA` 使用波黑资料、`+387` 手机区号、`en_BA` locale 和 `/pay/billing` 审批链路。
- 可在启动任务时动态勾选是否启用网页代理池；网页填写的代理会优先用于本次任务，空内容则回退到环境变量配置的代理池。
- 点击“开始执行”时会保存启动表单所有字段到当前浏览器，刷新页面后自动回填。
- 后台自动生成用户、卡片和所选地区地址等资料。
- 实时显示任务阶段、日志、生成资料和最终结果。
- 实时日志支持一键复制当前全部日志文本。
- 执行到短信验证时，网页会暂停并显示验证码输入框。
- 验证码错误后可继续输入验证码；也可以输入新手机号重新发送。
- 输入 `q` / `quit` / `exit` 可结束当前验证码流程。

## 环境变量

- `PAYPAL_WEB_MAX_LOG_LINES`：网页保留日志行数，默认 `300`。
- `PAYPAL_WEB_MAX_TOTAL_JOBS`：最多保留任务数，默认 `200`。
- `PAYPAL_WEB_MAX_ACTIVE_JOBS`：全局并发执行数，默认 `4`。
- `PAYPAL_WEB_MAX_ACTIVE_JOBS_PER_DEVICE`：单浏览器并发数，默认 `2`。
- `PAYPAL_WEB_ALLOW_DEBUG_LOGS=1`：允许网页端显示 DEBUG 日志。
- `PAYPAL_WEB_COOKIE_SECURE=1`：通过 HTTPS 反向代理发布时给浏览器标记 Secure Cookie。
- `PAYPAL_WEB_PRODUCTION=1`：生产模式提示。
- `PAYPAL_PROXY_ENABLED=1`：命令行未传 `--proxy/--no-proxy` 时默认开启。
- `PAYPAL_PROXY_URL="http://user:pass@host:port"`：使用单个代理 URL。
- `PAYPAL_PROXY_POOL="host:port:user:pass,host:port:user:pass"`：覆盖代理池。

网页代理池支持一行一个代理，格式包括 `host:port`、`user:pass@host:port`、`host:port:user:pass`、`user:pass:host:port`、`host:port##user##pass`，以及 `http://user:pass@host:port`、`socks5://user:pass@host:port`、`socks5://host:port:user:pass` 等带协议头的 URL；未写协议头时运行时默认使用 `http://`。详见 `docs/web-proxy-pool.md`。

运行中遇到代理/TLS/连接等传输异常时，当前代理会对同一请求最多尝试 `3` 次；仍失败则切换代理池中的下一个代理，单次请求最多使用 `6` 个代理。SOCKS5 握手返回 `Malformed reply` 也按传输异常处理。该规则只处理传输异常，不会重试 PayPal 返回的业务错误。使用 SOCKS 代理时依赖 `httpx[http2,socks]` 和 `httpcore[socks]`；如果运行时发现缺少 SOCKS 相关包，会自动用当前 Python 执行 pip 安装后继续创建会话。

原来的命令行入口 `main.py` 保持可用。

波黑 BA 分支的请求差异和运行方式见 `docs/paypal-ba-flow.md`。
