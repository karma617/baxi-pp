# 网页代理配置

网页端可勾选“启用代理”，并自行选择代理来源：

1. **API 接口获取**：填写动态代理 API 地址，每次任务开始时按支付地区拉 1 个新代理
2. **手动代理池**：多行填写代理地址，任务开始时从中选择

配置会保存到浏览器 `localStorage`。

## API 模式

示例：

```text
https://www.kookeey.com/pickdynamicips?t=2&auth=pwd&format=4&n=1&p=http&gate=us&g={country}&r=3&type=txt&sign=...&accessid=...
```

规则：

- 支持 `{country}` 占位，任务地区 BR/US/BA 会自动替换
- 如果写死 `g=BR`，服务端也会按任务地区改写 `g=`
- 留空则使用服务端默认 `DYNAMIC_PROXY_API`

## 代理池模式

支持格式：

```text
host:port
user:pass@host:port
host:port:user:pass
host:port##user##pass
http://user:pass@host:port
socks5://user:pass@host:port
```

未写协议头时默认按 `http://` 使用。

## 失败回退

- API 模式失败：回退到环境变量 / `config.PROXY_POOL`
- 代理池为空：回退到环境变量 / `config.PROXY_POOL`
- TLS/连接类传输异常：同一请求最多短重试 3 次；代理开启时再切换下一个代理，代理关闭时只报明确网络/代理关闭错误

## 有头浏览器
启用代理后，Playwright 有头浏览器与 httpx 共用同一代理出口；不会在会话开代理时裸连。

