# 接码平台配置

网页端支持三种验证码方式：

- `manual`：手动填写手机号，短信验证码到达后在网页输入。
- `herosms`：从 Hero-SMS 获取手机号并自动等待验证码。
- `smsbower`：从 SMSBrower/SMSBower 获取手机号并自动等待验证码。

## 页面配置

选择自动接码后，手机号可以留空。任务启动时会先从所选平台获取手机号，再用该手机号生成资料并进入 PayPal 任务流程。

每个平台需要配置：

- `API Key`：平台后台提供的 `api_key`。
- `API 地址`：可选。留空时使用内置默认地址，Hero-SMS 默认 `https://hero-sms.com/stubs/handler_api.php`，SMSBrower 默认 `https://smsbower.page/stubs/handler_api.php`。只有平台域名变更、镜像接口或自建转发时才需要填写。
- `service`：填写 API Key 后页面会自动调用平台接口加载下拉选项，输入框本身按服务名显示和筛选，提交任务时会自动转换成平台需要的 service code。默认兜底值为 `ot`。
- `country`：填写 API Key 后页面会自动调用平台接口加载下拉选项，输入框本身按国家名显示和筛选，提交任务时会自动转换成平台需要的 country code。默认兜底值为 `73`。
- `自动等码超时`：默认 `60` 秒。超时视为当前手机号不可用。

配置会保存到当前浏览器 `localStorage`，包括 API Key、API 地址、service、country、超时时间和代理配置。刷新页面后会自动回填；设置页右上角齿轮打开，点击刷新会加载已填写 API Key 的平台下拉选项。

Hero-SMS 的 service 选项会先从 `getServicesList` 获取服务名，再合并 `getPrices` 返回的库存；如果服务名接口不可用才退回显示 service code。不会调用会返回 `404` 的 `getServices`。SMSBrower/SMSBower 的 service 选项来自 `getServicesList`。

## Hero-SMS 复用规则

Hero-SMS 获取到手机号后，如果本轮成功收到验证码，后续任务会优先复用同一个手机号，并在下一轮发码前调用 `setStatus=3` 准备接收下一条短信。

如果 `60` 秒内没有收到验证码，或者自动返回的验证码未通过 PayPal 校验，系统会调用 `setStatus=8` 释放当前手机号，并重新获取新手机号。

## SMSBrower 规则

SMSBrower 不复用手机号。每个任务获取一个新手机号，成功收到验证码后调用 `setStatus=6` 完成；失败或超时调用 `setStatus=8` 取消。

## 注意

不要在不可信浏览器上保存平台 API Key。
