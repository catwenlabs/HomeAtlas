# Architecture

> 详细规格见 [specification.md](specification.md)（v1.3）。本文只描述已实现部分与结构约定。

## 总体

模块化单体（Modular Monolith）：单进程 FastAPI 应用 + 单 PostgreSQL 实例。不拆微服务；NATS / Worker / Grafana 属于第二阶段。

```
Client ──> uvicorn (FastAPI app)
             ├── app/api/health.py      横切路由（/health /ready，envelope 之外）
             ├── app/api/v1.py          /api/v1 路由聚合
             ├── app/modules/<domain>/  业务路由 / schemas / service / models
             ├── app/core/              配置 / 日志 / DB 会话 / 异常 / 统一响应
             └── SQLAlchemy async engine (asyncpg) ──> PostgreSQL
```

## 模块与 schema 映射（当前）

| app/modules/ | PostgreSQL schema | 状态 |
| -- | -- | -- |
| households | core | ✅ Phase 1.1 |
| accounts（含 account_balances） | core | ✅ Phase 1.1 |
| currencies | core | ✅ Phase 1.1（只读） |
| categories | finance | ✅ Phase 1.1 |
| transactions | finance | ✅ Phase 1.2（opening_balance + 收支生命周期） |
| transfers | finance | ✅ Phase 2E（同币种/跨币种/同账户换汇、手续费、冲正） |
| imports | system | ✅ Phase 2B-3（CSV/XLSX、模板、精确/模糊去重、批量行修正、确认生成交易） |
| audit | system | 表 + 写入服务；审计查询 API 未定义 |
| statistics | （跨 schema 只读聚合） | ✅ Phase 1.4（收支类 + 余额类分币种明细） |

每个业务模块内部：`router.py`（只做请求/响应/依赖注入）、`schemas.py`（Pydantic）、`service.py`（业务逻辑，事务边界）、`models.py`（ORM）。事务提交由 service 负责；`get_db` 在异常时回滚。

## 已实现业务 API（`/api/v1`）

| 模块 | 端点 |
| -- | -- |
| Households | `GET/POST /households`、`GET/PUT /households/{id}` |
| Accounts | `GET/POST /accounts`、`GET/PUT/DELETE /accounts/{id}`、`PUT /accounts/{id}/opening-balance`、`GET /accounts/{id}/balances`、`GET /accounts/{id}/transactions`、`GET /accounts/{id}/balance-history` |
| Currencies | `GET /currencies`、`GET /currencies/{code}` |
| Categories | `GET/POST /categories`、`GET/PUT/DELETE /categories/{id}` |
| Transactions | `GET/POST /transactions`、`GET/PUT/DELETE /transactions/{id}`、`POST /transactions/{id}/reverse` |
| Transfers | `GET/POST /transfers`、`GET/PUT/DELETE /transfers/{id}`、`POST /transfers/{id}/reverse` |
| Imports | `POST/GET /imports`、`GET/DELETE /imports/{id}`、`PUT /imports/{id}/mapping`、`POST /imports/{id}/preview`、`GET /imports/{id}/rows`、`PUT /imports/{id}/rows/{row_id}`、`POST /imports/{id}/confirm`、`POST /imports/{id}/cancel` |
| Statistics | `GET /statistics/income-expense`、`GET /statistics/category`、`GET /statistics/monthly`、`GET /statistics/cashflow`、`GET /statistics/overview`、`GET /statistics/account-balances` |

### Household 作用域

所有带家庭语义的端点接受可选 Header `X-Household-Id`：

- 提供且存在 → 使用该家庭；不存在 → 404 `HOUSEHOLD_NOT_FOUND`。
- 未提供且仅一个家庭 → 自动兜底。
- 未提供且多个家庭 → 400 `HOUSEHOLD_REQUIRED`。
- 未提供且无家庭 → 400 `HOUSEHOLD_REQUIRED`。

### 初始余额（opening_balance）

- `PUT /accounts/{id}/opening-balance` 按「账户 + 币种」upsert 一条确认态单边流水。
- 金额按币种 `decimal_places` 使用 half-even 舍入；允许负数。
- 币种等于家庭本位币时汇率固定为 1；不同币种必须提供 `exchange_rate`，并固化 `base_amount`。
- 每次设置/修改写入 `system.audit_logs`（`opening_balance.set` / `opening_balance.update`）。

### 交易生命周期（Phase 1.2）

- `POST /transactions` 仅接受 `income` / `expense`，默认 `draft`；可传 `status=confirmed` 直接确认。
- `draft → confirmed`：通过 `PUT /transactions/{id}`（`status=confirmed`）；`confirmed → reversed`：
  通过 `POST /transactions/{id}/reverse`。其余迁移被拒绝。
- 仅 draft 可修改（PUT）与物理删除（DELETE）；confirmed 只能冲正；reversed 为终态。
- 冲正在同一事务中把原记录置 `reversed`，并生成金额相同、方向翻转、
  `source=system`、`reverses_transaction_id` 指向原记录的 confirmed 反向流水。
- 普通金额恒正；`opening_balance` 只能通过账户初始余额端点写入。
- Phase 1 负余额规则：确认 expense 或冲正收入时校验账户该币种账面余额，
  不足返回 409 `INSUFFICIENT_BALANCE`。
- 审计动作：`transaction.create/update/confirm/delete/reverse`。

### 转账（Phase 2E）

- `POST /transfers` 默认创建 `draft`，也可直接 `status=confirmed`；`PUT /transfers/{id}`
  仅可修改 draft，并可通过 `status=confirmed` 完成确认。
- 支持同币种转账、跨币种转账，以及 `from_account = to_account` 的同账户换汇；
  完全相同的账户 + 币种返回 400 `TRANSFER_SOURCE_SAME`。
- `to_amount` 是入账权威值；`exchange_rate` 仅记录实际成交比价，不强制
  `from_amount × exchange_rate = to_amount`（容忍银行点差）。
- `base_amount` / `base_currency` 固化转账的家庭本位币价值：
  - 任一侧币种为本位币时直接取该侧金额；
  - 两侧都不是本位币时必须提供请求字段 `base_exchange_rate`，
    否则 400 `BASE_EXCHANGE_RATE_REQUIRED`。
- 手续费独立于 `from_amount`，从 `from_account` 以 `fee_currency` 扣除；
  确认时在同一事务内生成 `金融手续费` 衍生支出流水（`source=system`、
  `transfer_id` 关联、携带 `base_amount`）。草稿阶段不生成手续费流水。
- 手续费币种不是本位币/转出币种/转入币种时，必须提供请求字段
  `fee_exchange_rate`，否则 400 `FEE_EXCHANGE_RATE_REQUIRED`。
- Phase 1 负余额规则：确认时校验转出本金 + 同币种手续费合计，或分别校验
  不同币种的本金/手续费；不足返回 409 `INSUFFICIENT_BALANCE`。
- 冲正仅适用于 confirmed 且非冲正的转账：同一事务内把原转账置 `reversed`，
  生成反向转账，并将原手续费支出置 `reversed`、生成关联反向收入流水。
  转出资金不足时拒绝冲正；冲正生成的转账不可再次冲正。
- 审计动作：`transfer.create/update/confirm/delete/reverse`；手续费衍生流水
  同时写入 `transaction.create/reverse`。
- 转账本金不计收入/支出；手续费衍生支出恰好计一次，统计与账户余额自动联动。

### 数据导入（Phase 2B-1 同步骨架）

- `POST /imports` 接收 `multipart/form-data`：CSV 文件 + 可选 `account_id`；
  解析表头、保存文件与 SHA-256，创建 `uploaded` 批次。
- CSV 编码优先 `utf-8-sig`、回退 `gb18030`；分隔符自动探测 `, ; tab |`；
  表头最多 100 列，单文件默认 10 MB、单批次 20,000 行。
- `PUT /mapping` 保存列映射、四种 `amount_mode`（正数收入/正数支出/方向列/借贷列）、
  币种、汇率、分类映射与日期格式，并校验必填字段与源列存在。
- `POST /preview` 重新解析文件，按行规范化并**重建** `import_rows`：
  账户/分类归属、分类类型、金额精度、外币汇率、日期、描述/流水号长度等
  逐行收集错误；有效行、无效行、重复行分别计数。
- 去重顺序：同账户 `external_id` → 精确指纹（账户/类型/金额/币种/UTC 秒/描述）
  → 批内重复；范围限定当前 household，排除开账与转账衍生流水。模糊匹配默认关闭，
  开启后按同账户、同类型、同币种、金额相等、日期相差 ≤ 1 天、描述相似度 ≥ 0.85
  标记 `duplicate` 并返回 `DUPLICATE_FUZZY` 相似度提示。
- `PUT /rows/{row_id}` 可修正规范化数据或把行标记为 `valid` / `skipped`。
- `POST /confirm` 同步执行：默认生成 `confirmed` 交易，可传 `create_status=draft`；
  `on_duplicate=skip` 跳过重复行，`allow` 允许导入。每行使用 savepoint，
  单行失败不中断整批；确认态支出仍执行负余额校验，不提供绕过开关。
- 完成状态：全部成功 `completed`，部分成功 `partial`，全部失败 `failed`；
  重复确认 `completed/partial` 批次为幂等返回。
- 导入流水 `source='import'`，固化 `base_amount`；不导入转账与开账余额。
- 文件存 `IMPORT_STORAGE_DIR`（默认 `/tmp/homeatlas-imports`），数据库仅存路径、
  大小与 SHA-256。预览会重建行数据，手工修正应在预览后完成。
- 审计动作：`import.create/mapping/preview/confirm/execute/row_update/cancel/delete`，
  以及批量操作 `import.rows_bulk_update/rows_bulk_skip`。
- 2B-3 增强已实现：Excel `.xlsx` 上传（`openpyxl` 只读首个工作表）、全局模板下载
  `GET /imports/template?format=csv|xlsx`、可选模糊去重（默认关闭）、批量行修正
  `PUT /imports/{id}/rows` 与按范围跳过 `POST /imports/{id}/rows/skip`（单次上限 500 行）。
- 2B-2 引入 NATS JetStream + Outbox + Import Worker 与共享文件卷（**当前暂缓**，
  继续使用 API 内同步执行）。

### 余额口径

- 账面余额 = 已确认/已冲正交易流水的符号汇总（opening 计原值、income 加、expense 减）
  + 转账本金（转出减、转入加）。
- 转账手续费是独立衍生支出流水（Phase 2E 已实现），余额公式不重复扣减 `transfer.fee`。
- `balances` 同时返回每币种最近一条对账快照与差额；对账快照表不承载初始余额。

### 统计（Phase 1.4）

- `GET /statistics/income-expense`：区间收入、支出、净结余与笔数。
- `GET /statistics/category`：按分类聚合（含 `category_id=null` 的「未分类」），
  `transaction_type` 可选 `income` / `expense`，占比按同类型合计计算。
- `GET /statistics/monthly`：`granularity=month|year`，返回区间内每个周期（含空周期）
  的收入、支出、净结余。
- `GET /statistics/cashflow`：`granularity=day|month|year` 的时间序列，
  含每期净额与累计净额；空周期补零。
- `GET /statistics/overview`：区间收支摘要 + 分币种资产明细（不折算总额）。
- `GET /statistics/account-balances`：按账户、币种列出账面余额，并给出分币种合计；
  不折算总额，停用账户仍会返回并带 `is_active=false`。
- 收支口径：只聚合 `status=confirmed`、`reverses_transaction_id IS NULL` 的
  `income` / `expense` 流水，金额使用录入时固化的 `base_amount`（家庭本位币）。
  开账流水、草稿、已冲正原记录与反向记录均被排除；转账本金不在 `transactions`
  中，手续费衍生支出恰好计一次。
- 余额口径与账户余额接口一致：confirmed + reversed 流水（opening 计原值）
  加转账本金；手续费不重复扣减。余额类统计按规格 §6.7 只出分币种明细。
- 日期参数为家庭时区下的自然日（`start_date` / `end_date` 含端点）；
  `income-expense` / `category` / `cashflow` / `overview` 默认当前月，
  `monthly` 默认当前年。
- 周期分组使用 PostgreSQL `timezone(household.timezone, transaction_date)`，
  不按 UTC 截断。

## 请求流与统一响应

- 业务端点统一前缀 `/api/v1`。
- 成功：`{"success": true, "data": ..., "message": null}`；列表的 `data` 为 `{items, total, page, page_size}`。
- 失败：`{"success": false, "data": null, "message": "...", "error_code": "..."}`，由全局异常处理器产出：
  - `AppError` 及子类 → 业务错误码（4xx）
  - `RequestValidationError` → `VALIDATION_ERROR`（422）
  - Starlette `HTTPException` → 按状态码映射（404→`NOT_FOUND` 等）
  - 未捕获异常 → `INTERNAL_ERROR`（500，细节不外泄）
- `/health`（进程存活）与 `/ready`（`SELECT 1` 数据库探活）是基础设施探针，不走 envelope；compose healthcheck 用 `/ready`。

## 日志

structlog：开发环境 Console 渲染，生产（`APP_ENV=production`）JSON。经 `ProcessorFormatter` 桥接 uvicorn/sqlalchemy 的标准库日志。

## 已知范围

- 无认证；`audit_logs.actor` 固定为 `system`。
- 转账 API（Phase 2E）与统计 API（收支类 + 余额类分币种明细）已完成。
- 数据导入 2B-1 同步骨架与 2B-3 增强已完成（CSV/XLSX、模板下载、精确/模糊去重、
  批量行修正）；NATS/Worker 异步化（2B-2）已决定暂缓。
- 转账冲正生成的转账不可再次冲正，避免手续费反向链失控。
- 余额类统计不折算总额（规格 §6.7）。
