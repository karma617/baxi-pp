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
3. 后续才是 billing/authorize 或 `/pay/billing`

## 当前代码行为
- 保存 `signup_contingency_reason`
- BR Phase4 按上述 URL 绑定
- 仅当 status 正常且页面足够大/非 captcha 时记 `bound=true`
- 403/小页会告警，并可尝试 headed browser 再绑

## 验证日志
关注：
- `Phase4 step1: GET Hermes contingency shell reason=...`
- `Hermes review bound: status=... bound=true/false`
- 不应再把 `status=403 bytes=761` 当成功绑定

## authorize 成功判定
- 只有 `billing.authorize.returnURL` 才算成功
- `BUYER_NOT_SET` 时禁止用 `BillingAgreementContextQueryForAddCard.returnURL` 报成功
- 失败后会：Hermes 重绑 + 再 authorize 一次；仍失败则尝试 `/pay/billing` 恢复
- 仍失败则任务记 error，避免假成功导致“权益未到账”

## SignUp 失败门禁
- `OAS_ERROR` + checkpoint `createMemberAccount` 且无 `accessToken`：账号未创建，直接失败
- 禁止再 `Continuing with billingAgreementId only` 空跑 Phase4
- authorize 若返回 `auth state ... ANONYMOUS`：直接失败，不做 ContextQuery 假成功

