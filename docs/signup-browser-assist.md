# SignUpNewMember browser assist

## 背景
BR 流程在 OTP 成功后，纯 HTTP `SignUpNewMemberMutation` 可能返回 `authchallengenodeweb` HTML（表现为 `NON_JSON_RESPONSE`）。旧逻辑把它当成卡失败并反复换卡。

## 行为
1. HTTP SignUp 返回 challenge/non-JSON 且无 onboardAccount 时，打开有头浏览器
2. 浏览器在 signup 页 page context 内 POST `SignUpNewMemberMutation`（带 cookies / fn_sync_data）
3. 优先使用浏览器返回的 JSON（onboardAccount / errors / accessToken）
4. 仅真实卡错误（CARD_GENERIC_ERROR、CC_LINKED_TO_FULL_ACCOUNT、INSTRUMENT_SHARING_LIMIT_EXCEEDED、CREATE_CARD_ACCOUNT_CANDIDATE_VALIDATION_ERROR、addCard/validate.fi）才换卡

## 环境变量
- `PAYPAL_BROWSER_ASSIST=1`（默认开启）
- `PAYPAL_BROWSER_ASSIST_TIMEOUT=120`

## 操作提示
- 正常 signup 表单：无需操作
- 出现 captcha/slider：在浏览器窗口手动完成
- 出现 PayPal “Parece que as coisas não estão funcionando no momento” / “things don't appear to be working” 错误页：系统会判定为链接失效或当前会话不可用，立即退出本次浏览器等待并进入换代理/失败流程
- 服务需手动重启后重跑 BR 任务验证

## 代理绑定
- 有头浏览器必须复用当前 HTTP 会话同一条 `proxy_url`
- 来源优先 `session.proxy_url`，缺失时回退 `proxy_config.url`
- 代理已开启但解析失败时，浏览器会直接失败，禁止裸连
- 启动日志会打印脱敏代理 `scheme://***:***@host:port`，不再只写 on/off

