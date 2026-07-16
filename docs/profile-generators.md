# 多国家资料生成模块

本项目已将 `https://oaipay.12001234.xyz/public/app.js` 中的资料生成逻辑移植为后端 Python 模块，当前支持 `JP`、`BR`、`US`、`GB`、`BA` 五个国家资料生成。

## 入口

- `paypal.profile_generators.generate_profile_data(country)`：生成完整资料，返回 `GeneratedProfile`。
- `paypal.profile_generators.generate_profile_dict(country)`：生成完整资料并转为 `dict`。
- `paypal.models.generate_country_materials(phone, country)`：生成同一份资料，并转换为现有 `UserInfo`、`CardInfo`、`BillingAddress` 三类模型。
- `paypal.models.generate_user_for_country(phone, country)`、`generate_address_for_country(country)`、`generate_card_for_country(country)`：分别生成指定国家的用户、地址、卡片模型。

## 兼容性

现有协议支付默认链路没有切换国家：`generate_user(phone)` 和 `generate_address()` 不传国家时仍按原巴西 `BR` 行为执行。

新增资料生成用于各地区协议分支的基础数据。当前 `US` 和 `BA` 已有独立支付分支；其他地区仍需分别处理 locale、phoneCountry、identityDocument、signup terms、风控指纹、GraphQL header 和最终 authorize 上下文。

## 示例

```python
from paypal.models import generate_country_materials

user, card, address, profile = generate_country_materials("+14155550123", "US")
print(user.email, user.phone_country_code)
print(card.number, card.expiry, card.card_type)
print(address.country, address.city, address.postal_code)
print(profile.full_address)
```
