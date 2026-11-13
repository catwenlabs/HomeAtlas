# API 参考

统一前缀 `/api/v1`，成功/失败均使用统一 envelope（spec §6.8）。除 `setup/*` 与 `auth/login` 外，
所有业务接口都要求 `Authorization: Bearer <token>`；家庭作用域由 JWT 中的 `household_id` 派生。
交互式文档：运行后访问 <http://127.0.0.1:8000/docs>。

## 端点清单

| 模块 | 端点 |
| -- | -- |
| Setup（公开） | `GET /api/v1/setup/status`、`GET /api/v1/setup/options`、`POST /api/v1/setup` |
| Auth | `POST /api/v1/auth/login`（公开）、`GET /api/v1/auth/me`、`POST /api/v1/auth/logout` |
| Users | `GET /api/v1/users`、`POST /api/v1/users`、`PUT /api/v1/users/{id}`（owner） |
| Households | `GET /api/v1/households`、`GET/PUT /api/v1/households/{id}`（PUT 仅 owner） |
| Accounts | `GET/POST /api/v1/accounts`、`GET/PUT/DELETE /api/v1/accounts/{id}` |
| 初始余额 | `PUT /api/v1/accounts/{id}/opening-balance` |
| 余额/流水 | `GET /api/v1/accounts/{id}/balances`、`/transactions`、`/balance-history` |
| Currencies | `GET /api/v1/currencies`、`GET /api/v1/currencies/{code}` |
| Categories | `GET/POST /api/v1/categories`、`GET/PUT/DELETE /api/v1/categories/{id}` |
| Transactions | `GET/POST /api/v1/transactions`、`GET/PUT/DELETE /api/v1/transactions/{id}`、`POST /api/v1/transactions/{id}/reverse` |
| Transfers | `GET/POST /api/v1/transfers`、`GET/PUT/DELETE /api/v1/transfers/{id}`、`POST /api/v1/transfers/{id}/reverse` |
| Imports | `POST/GET /api/v1/imports`、`GET/DELETE /api/v1/imports/{id}`、`PUT /api/v1/imports/{id}/mapping`、`POST /api/v1/imports/{id}/preview`、`GET /api/v1/imports/{id}/rows`、`PUT /api/v1/imports/{id}/rows`（批量）、`POST /api/v1/imports/{id}/rows/skip`、`PUT /api/v1/imports/{id}/rows/{row_id}`、`POST /api/v1/imports/{id}/confirm`、`POST /api/v1/imports/{id}/cancel`、`GET /api/v1/imports/template?format=csv\|xlsx` |
| Statistics | `GET /api/v1/statistics/income-expense`、`/category`、`/monthly`、`/cashflow`、`/overview`、`/account-balances` |
| Exchange rates | `GET/POST /api/v1/exchange-rates`、`GET /api/v1/exchange-rates/latest?base=&quote=`、`DELETE /api/v1/exchange-rates/{id}` |
| Assets | `GET /api/v1/assets/summary`、`POST /api/v1/assets/snapshots`（当日快照 upsert）、`GET /api/v1/assets/snapshots`、`GET /api/v1/assets/snapshots/monthly?year=` |
| Investments | `GET/POST /api/v1/investments`、`GET/PUT/DELETE /api/v1/investments/{id}`、`PUT /api/v1/investments/{id}/value`、`PUT /api/v1/investments/{id}/tags`、`POST /api/v1/investments/{id}/fund`、`POST /api/v1/investments/{id}/redeem`（建仓可带 `fund_transfer` 同事务入金） |
| Holdings | `GET/POST /api/v1/investments/{id}/holdings`、`PUT/DELETE /api/v1/investments/{id}/holdings/{holding_id}`、`POST /api/v1/investments/{id}/refresh-value`（按行情自动估值） |
| Tags | `GET/POST /api/v1/investment-tags`、`PUT/DELETE /api/v1/investment-tags/{id}` |
| Loans | `GET/POST /api/v1/loans`、`GET/PUT/DELETE /api/v1/loans/{id}`、`POST /api/v1/loans/{id}/settle`（负债端与日利息自动并入净资产总览/快照） |
| Market | `GET /api/v1/market/quotes?symbols=SH:600519,HK:00700,US:AAPL`（按需拉取，30s 缓存；`QUOTE_PROVIDER=fake` 可离线） |
| 探针 | `GET /health`、`GET /ready`（不走 envelope） |

## 首次初始化与登录

```bash
# 是否已初始化；options 只返回预填项，不写库
curl -s http://127.0.0.1:8000/api/v1/setup/status
curl -s http://127.0.0.1:8000/api/v1/setup/options

# 首次初始化：创建家庭 + owner + 用户确认的币种/分类，并直接返回 token
curl -s -X POST http://127.0.0.1:8000/api/v1/setup \
  -H 'Content-Type: application/json' \
  -d '{"username":"owner","password":"password123","household_name":"我的家",
       "base_currency":"CNY","currency_codes":["CNY","USD"],
       "categories":[{"name":"工资","category_type":"income"},
                     {"name":"餐饮","category_type":"expense"}]}'

# 后续登录
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"owner","password":"password123"}' | jq -r '.data.access_token')
```

`currency_codes` / `categories` 省略（`null`）表示使用全部内置项；`categories: []` 表示不
写入任何分类。`currency_codes` 必须至少包含本位币，否则返回 400
`BASE_CURRENCY_NOT_SELECTED`。初始化只能执行一次，重复调用返回 409
`SETUP_ALREADY_COMPLETED`。

## 调用示例

```bash
# 创建账户（使用登录返回的 $TOKEN）
curl -s -X POST http://127.0.0.1:8000/api/v1/accounts \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name":"中国银行","account_type":"bank","currency":"CNY"}'

# 设置初始余额（同一账户+币种重复 PUT 即修改，并留审计）
curl -s -X PUT http://127.0.0.1:8000/api/v1/accounts/<account-id>/opening-balance \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"amount":"1000.00","description":"开账"}'

# 多币种开账：非本位币必须提供汇率
curl -s -X PUT http://127.0.0.1:8000/api/v1/accounts/<account-id>/opening-balance \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"amount":"100.00","currency":"USD","exchange_rate":"7.10"}'

# 记一笔支出（默认 draft；传 "status":"confirmed" 可直接确认）
curl -s -X POST http://127.0.0.1:8000/api/v1/transactions \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"account_id":"<account-id>","category_id":"<expense-category-id>","transaction_type":"expense","amount":"35.50","description":"午餐"}'

# 确认 draft
curl -s -X PUT http://127.0.0.1:8000/api/v1/transactions/<transaction-id> \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"status":"confirmed"}'

# 冲正已确认流水（原记录置 reversed，并生成关联反向流水）
curl -s -X POST http://127.0.0.1:8000/api/v1/transactions/<transaction-id>/reverse \
  -H "Authorization: Bearer $TOKEN"

# 录入汇率并获取净资产总览
curl -s -X POST http://127.0.0.1:8000/api/v1/exchange-rates \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"base_currency":"USD","quote_currency":"CNY","rate":"7.20","rate_date":"2026-11-14"}'

curl -s http://127.0.0.1:8000/api/v1/assets/summary -H "Authorization: Bearer $TOKEN"

# 记录当日净资产快照（幂等，重复调用更新同日记录）
curl -s -X POST http://127.0.0.1:8000/api/v1/assets/snapshots -H "Authorization: Bearer $TOKEN"

# 登记股票持仓并按行情一键估值
curl -s -X POST http://127.0.0.1:8000/api/v1/investments \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name":"A股组合","investment_type":"stock","currency":"CNY","principal":"0","start_date":"2026-01-01"}'

curl -s -X POST http://127.0.0.1:8000/api/v1/investments/<investment-id>/holdings \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"market":"SH","symbol":"600519","quantity":100,"cost_price":"1700"}'

curl -s -X POST http://127.0.0.1:8000/api/v1/investments/<investment-id>/refresh-value \
  -H "Authorization: Bearer $TOKEN"

# CSV 导入：上传 → 映射 → 预览 → 确认
curl -s -X POST http://127.0.0.1:8000/api/v1/imports \
  -H "Authorization: Bearer $TOKEN" \
  -F 'file=@alipay-2026-06.csv' \
  -F 'source_format=csv' \
  -F 'account_id=<account-id>'

curl -s -X PUT http://127.0.0.1:8000/api/v1/imports/<batch-id>/mapping \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"columns":{"transaction_date":"交易日期","amount":"金额","description":"备注"},"amount_mode":"signed_positive_income"}'

curl -s -X POST http://127.0.0.1:8000/api/v1/imports/<batch-id>/preview \
  -H "Authorization: Bearer $TOKEN"

curl -s -X POST http://127.0.0.1:8000/api/v1/imports/<batch-id>/confirm \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"on_duplicate":"skip","create_status":"confirmed"}'
```

## 通用约定

- 金额以字符串返回（Decimal，避免浮点误差）；写入时按币种 `decimal_places` 使用 half-even 取整。
- 普通收支必须为正数；`opening_balance` 只能通过初始余额端点写入；credit 账户允许透支（可设额度），其余账户拒绝负余额。
- 已确认记录不可修改或删除，只能冲正（生成关联反向记录并留审计）；冲正可完整回滚转账、手续费、赎回损益。
- CSV 导入默认限制单文件 10 MB、单批次 20,000 行（`IMPORT_MAX_FILE_MB` / `IMPORT_MAX_ROWS`）；文件落 `IMPORT_STORAGE_DIR`（默认 `/tmp/homeatlas-imports`），数据库只存路径与 SHA-256。预览会重建批次行数据，手工修正应在完成预览后进行。
- 错误响应统一为 `{"success": false, "data": ..., "message": ..., "error_code": ...}`；`error_code` 全局枚举（如 `INSUFFICIENT_BALANCE`、`CREDIT_LIMIT_EXCEEDED`、`EXCHANGE_RATE_NOT_FOUND`），部分错误的 `data` 携带结构化上下文（如缺失币对清单）。
