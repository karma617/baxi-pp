# Hermes 会话绑定（卡 contingency 后）

## 结论
Hermes `403 bytes≈761` 不是“绑定成功”，不能继续指望 authorize 返回 returnUrl。

## HAR 成功路径关键点
SignUp 出现卡 contingency（如 `CARD_GENERIC_ERROR` / sharing limit）且带 accessToken 后：

1. GET `/webapps/hermes`（entry）
   - `fromSignupLite=true`
   - `addFIContingency=noretry`
   - `redirectToHermes=true`
   - `fallback=1`
   - `reason=<base64(CARD_GENERIC_ERROR 等)>`
   - Referer = `checkoutweb/signup?...`
2. GET `/webapps/hermes`（review shell）
   - 去掉 `addFIContingency` / `redirectToHermes`
   - 保留 `fallback=1` + `reason=...`
3. 后续按地区分流：
   - BR：打开 `billingLite=1#/billingweb/review` 绑定 Hagrid review，再执行 `billing.authorize`
   - US：同样先打开 Hagrid review 并执行 `billing.authorize`，未拿到 `returnURL` 时再回落到 US HAR 的 `/pay/billing`
   - BA：继续走 BA HAR 的 `/pay/billing`

## 当前代码行为
- 保存 `signup_contingency_reason`
- BR/US Phase4 按上述 URL 绑定，Hermes `reason` 对齐 HAR 的 `R_ERROR`
- BR/US 在 authorize 前打开 `billingLite=1#/billingweb/review`，优先点击页面内 Hagrid 主 CTA 并监听页面自身 GraphQL authorize；若未捕获原生 authorize，再降级到同一 BrowserContext 的 request GraphQL，最后才使用页面 `fetch`
- httpx authorize 只作为浏览器 authorize 未拿到 `returnURL` 后的 fallback
- 仅当 status 正常且页面足够大/非 captcha 时记 `bound=true`
- 403/小页会告警，并可尝试 headed browser 再绑

## 验证日志
关注：
- `Phase4 step1: GET Hermes contingency shell reason=...`
- `Hermes review bound: status=... bound=true/false`
- `Phase4 BR/US step1c: open Hermes billing review route before authorize...`
- `Browser native authorize clicked CTA: ...`
- `Browser native captured authorize HTTP ...`
- `Browser authorize using mode=native_click|native_navigation|browser_request_context`
- `Browser BillingAgreementContextQueryForAddCard HTTP ...`
- `Browser authorize HTTP ...`
- `authorize result attempt ...`
- 不应再把 `status=403 bytes=761` 当成功绑定

## Phase4 成功判定
- BR/US 只有 `billing.authorize.returnURL` 才算 Hagrid authorize 成功；`BillingAgreementContextQueryForAddCard.returnURL` 只作预热/诊断。
- 优先采用浏览器页面上下文的 authorize 结果，保留 PayPal 页面态、cookies 和 EUAT。
- BR 不再把 `/pay/billing` 当主恢复链路。
- US 在 Hagrid authorize 未成功时回落到 US HAR 的 `/pay/billing` 链路，不套用 ContextQuery-returnURL 假成功。
- BA 保持 BA HAR 的 `/pay/billing` 链路，不套用 BR/US 的 ContextQuery-returnURL。
- 若 Hermes 绑定失败、authorize 仍返回 `BUYER_NOT_SET`，任务仍记 error，避免假成功导致“权益未到账”。

## SignUp 失败门禁
- `OAS_ERROR` + checkpoint `createMemberAccount` 且无 `accessToken`：账号未创建，直接失败
- 禁止再 `Continuing with billingAgreementId only` 空跑 Phase4
- 非 BR 的 authorize 若返回 `auth state ... ANONYMOUS`：直接失败，不做跨地区 fallback

