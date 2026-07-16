# 波黑 BA PayPal 支付分支

网页和命令行均可选择 `BA`。该分支按 BA HAR 实现从初始协议页、signup、短信验证、注册、Hermes、`/pay/billing` 到商户回跳的关键协议链路。

## 地区参数

- PayPal country：`BA`
- locale：`en_BA`
- language：`en`
- checkout GraphQL channel：`MOBILE`
- 手机国际区号：`+387`
- signup 合规资料：包含 `dateOfBirth` 和 `nationality=BA`
- Hermes 与 billing reason：`Q0FSRF9HRU5FUklDX0VSUk9S`

HAR 前段出现的 `country.x=CN`、`locale.x=en_CN` 属于进入 BA signup 前的页面状态；项目直接构建 BA signup URL，不回放该段。HAR 中的 `/auth/validatecaptcha` 也位于这段页面交互中，BA 分支保持与现有 US 分支相同的协议流程，不主动调用该接口。

## 链路

1. 打开 `/agreements/approve`，提取 `SSRT`、`ctxId` 和页面内的 `EC Token`。
2. BA 分支使用该 EC Token 直接加载 `/checkoutweb/signup`，提取实时 signup terms content hash。
3. 按 `MOBILE / BA / en_BA` 上下文执行 checkout GraphQL warmup。
4. 依次执行短信发起、短信确认和 `SignUpNewMemberMutation`；signup 请求结构与 HAR 一致，不额外发送 `fn_sync_data`，并包含出生日期及 BA 国籍。
5. 使用 EC Token 加载带 `addFIContingency=noretry` 的 Hermes URL，再加载去除 contingency 参数的 review URL。
6. `/pay/billing` 使用 BA Token，发送 HAR 对应的 multipart 字段、3DS 屏幕参数和 `Next-Action`，且不额外发送 `RSC` Header。
7. 从 billing 响应、`x-action-redirect` 或 HTTP Location 中提取商户返回地址，继续跟随 Stripe/OpenAI 回跳。

如果 EC Token、signup URL 或实时 content hash 缺失，任务会在短信发送前停止并明确指出缺失项，避免使用不完整上下文继续注册。

## 使用

网页端在“支付地区”选择“波黑 BA”。

命令行示例：

```powershell
python main.py --country BA --ba-token BA-TOKEN --phone +387PHONE
```

`/pay/billing` 的 `Next-Action` 会优先从实时 Hermes 页面提取，其次读取 `PAYPAL_BA_BILLING_NEXT_ACTION`，最后使用本次 BA HAR 捕获的 action id 作为 fallback。PayPal 更新前端部署后，如 fallback 失效，应使用新页面的 action id 覆盖环境变量。

SOCKS5 代理握手中的 `Malformed reply` 会进入传输重试：当前代理最多重试三次，随后按代理池切换节点，不再直接中断 OTP Confirm。
