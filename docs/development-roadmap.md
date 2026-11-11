# Development Roadmap

完整规格见 [specification.md](specification.md) §8–§11。当前进度：

| Phase | 内容 | 状态 |
| -- | -- | -- |
| 1.0 Task 001 | 基础设施：FastAPI + SQLAlchemy + Alembic + Compose + CI + 探针 | ✅ 完成 |
| 1.1 Task 002 | 基础数据模型：households/accounts/currencies/categories/balances + seed + opening_balance | ✅ 完成 |
| 1.2 Task 003 | 收支管理 API：状态机、冲正、审计、完整查询筛选 | ✅ 完成 |
| 1.4 | 统计 API：收支类 + 余额类分币种明细、家庭时区分组 | ✅ 完成（Task 004） |
| 1.5 | 数据导入预留：接口、模型、去重与异步流程设计评审 | ✅ 设计评审完成（实现移至 2B） |
| 2A/2B/2C/2D | Web 前端 / 异步导入 / 投资与资产 / Grafana | ⬜ 第一阶段稳定后 |
| 2B-1 | 数据导入同步骨架：CSV 上传、映射、预览/去重、确认生成交易 | ✅ 完成（Task 007） |
| 2E（原 Phase 1.3） | 转账与多币种：跨币种、手续费衍生支出、余额核对 | ✅ 完成（Task 006） |

> **排期调整（2026-11-11）**：原 Phase 1.3「转账与多币种」整体移入第二阶段（记为 2E），
> Phase 1 聚焦收支业务逻辑与统计。`finance.transfers` 表、状态机字段与余额计算已在
> `0002_phase_1_1` 中建好，2E 实施未新增迁移；交易侧仍禁止单独冲正 `transfer_id`
> 关联流水，手续费必须随转账冲正。

## Task 002（Phase 1.1）已完成

- `0002_phase_1_1` 建 8 张业务表：`core.households`、`core.accounts`、
  `core.currencies`、`core.account_balances`、`finance.categories`、
  `finance.transactions`、`finance.transfers`、`system.audit_logs`，含 §4 的
  CHECK 约束、索引、状态机字段、冲正/衍生关联字段。
- Alembic data migration：6 个币种、默认家庭、11 个默认分类（含系统内置「金融手续费」）。
- 已实现 API（`/api/v1`）：households CRUD、accounts CRUD + 初始余额 + 账面余额 +
  流水/对账历史读取、currencies 查询、categories CRUD（两级分类校验）。
- `X-Household-Id` 作用域依赖：单家庭兜底、多家庭 400、未知家庭 404。
- 初始余额为 `opening_balance` 确认态单边流水，支持负数、多币种（非本位币需汇率），
  每次设置/修改写入 `system.audit_logs`。
- 测试：pytest 43 项；覆盖率 98%（CI 门槛 80%）。

### 已知边界（留给后续阶段）

- 转账 API 已由 Task 006（2E）补齐；`finance.transfers` 表与余额计算在此阶段已就绪。
- `account_balances` 仅提供读取（账面余额/对账历史），快照写入接口未在 §6 定义，
  留待对账功能设计时补齐。
- 默认家庭由迁移创建；新建家庭会自动克隆默认分类树。

## 验收复查（Task 002）

- `alembic upgrade head` 建表 + seed 成功；降级可回滚。
- 可创建家庭/账户/分类；可设置与修改初始余额并查询审计记录。
- 多币种开账正确（汇率必填、按币种精度 half-even 取整）。
- 跨家庭 parent、越级 parent、自引用、系统手续费删除均被拒绝。
- `X-Household-Id` 兜底/400/404 行为通过测试。

## Task 003（Phase 1.2）已完成

- 新增 `GET/POST /transactions`、`GET/PUT/DELETE /transactions/{id}`、
  `POST /transactions/{id}/reverse`（`/api/v1` 前缀，统一 envelope）。
- 状态机：创建默认 `draft`，可用 `status=confirmed` 直接确认或通过
  `PUT status=confirmed` 从 draft 确认；`draft → confirmed → reversed`，
  其余迁移由 Pydantic（422）或 Service（409）拒绝。
- 仅 draft 可修改、可物理删除；confirmed 只能冲正；reversed 为终态。
- 冲正：同一事务内把原记录置 `reversed` 并生成一条金额相同、方向翻转、
  `source=system`、`reverses_transaction_id` 指向原记录的 `confirmed` 反向流水；
  冲正收入为 expense 时执行负余额校验。
- `POST /transactions` 仅接受 `income` / `expense`；`opening_balance` 只能通过
  `PUT /accounts/{id}/opening-balance` 写入。
- 金额：按币种 `decimal_places` half-even 取整；`income/expense` 必须为正；
  非本位币必须提供汇率并固化 `base_amount`。
- Phase 1 负余额规则：创建为 confirmed 的 expense、draft→confirmed 的 expense、
  冲正收入导致的 expense 均在 Service 层校验，返回 409 `INSUFFICIENT_BALANCE`。
- 查询支持：日期区间（按家庭时区）、账户、分类、类型（含 opening_balance）、币种、
  金额区间、关键词（description/external_id）、状态、分页与排序白名单。
- 审计：`transaction.create/update/confirm/delete/reverse`，冲正记录含原记录快照与
  反向流水关联信息。
- 测试：全量 59 项通过，覆盖率 98.67%；ruff / mypy strict 通过。

### Phase 1.2 已知边界

- 转账 API 已由 Task 006（2E）补齐；`transfer_id` 关联流水仍禁止通过交易冲正端点处理
  （返回 `TRANSACTION_LINKED_TO_TRANSFER`）。
- 统计 API（Phase 1.4）需显式排除 `opening_balance`，并按 `household.timezone`
  做月度分组。
- 无认证，审计 `actor` 固定为 `system`。

## Task 004（Phase 1.4）已完成

- 新增 `app/modules/statistics/`（router / schemas / service），注册到 `/api/v1`：
  - `GET /statistics/income-expense`
  - `GET /statistics/category`
  - `GET /statistics/monthly`
  - `GET /statistics/cashflow`
  - `GET /statistics/overview`
  - `GET /statistics/account-balances`
- 收支口径：只聚合 `status=confirmed` 且 `reverses_transaction_id IS NULL` 的
  `income` / `expense` 流水（`transaction_type != 'opening_balance'`），金额聚合
  录入时固化的 `base_amount`，返回家庭本位币。
- 开账流水、草稿、已冲正原记录及其反向记录均排除；内部转账本金不在
  `transactions` 中，手续费衍生支出恰好计一次。
- 日期参数为家庭时区自然日；`income-expense` / `category` / `cashflow` / `overview`
  默认当前月，`monthly` 默认当前年；结束日期含当天。
- `monthly` 支持 `granularity=month|year`，`cashflow` 支持
  `granularity=day|month|year`；周期分组使用
  `timezone(household.timezone, transaction_date)`，空周期补零，
  `cashflow` 额外返回 `cumulative_net`。
- `category` 支持 `transaction_type=income|expense` 筛选，未分类流水归入
  「未分类」，占比按同类型合计计算。
- 余额类统计：
  - `account-balances` 按账户 + 币种返回账面余额，并给出分币种合计与账户数；
    停用账户仍返回并标记 `is_active=false`。
  - `overview` 返回区间收支摘要 + 分币种资产明细。
  - 两者只出分币种明细，不折算总额（规格 §6.7）；余额口径复用
    `get_household_book_balances`（confirmed + reversed 流水 + 转账本金）。
- 错误：`INVALID_DATE_RANGE`（400）、`DATE_RANGE_TOO_LARGE`（400，
  cashflow 超过 3660 个周期）、granularity 非法（422 `VALIDATION_ERROR`）。
- 测试：新增 `tests/test_statistics.py`（15 项）；全量 74 项通过，
  覆盖率 98.92%；ruff / mypy strict 通过。

### Phase 1.4 已知边界

- 余额类统计只返回分币种明细，不折算总额；总额折算推迟到引入汇率表。
- `cashflow` 的累计净额从请求区间起点归零，不包含区间之前的余额。
- 转账统计已用真实转账数据回归（Task 006）：本金不计收支、手续费计一次。

## Task 005（Phase 1.5）设计评审已完成

- 产出 [import-design.md](import-design.md)：数据导入的接口草案、批次/行状态机、
  文件解析限制、字段映射、去重、校验、建议数据模型、NATS/Worker 异步流程、
  错误码、测试计划与 2B 实施拆分。
- 范围：CSV / Excel 上传 → 映射 → 预览 → 人工确认 → 正式导入；
  只导入 `income` / `expense`，不涉及转账与开账余额。
- 关键建议：
  - 批次与行数据放 `system` schema（`import_batches` / `import_rows`），
    2B 再建迁移。
  - 行级去重用「外部流水号 + 精确指纹」，模糊匹配默认关闭。
  - 导入默认生成 `confirmed` 交易，提供 `create_status=draft` 选项；
    负余额规则不被绕过。
  - 解析与写库由 Import Worker 异步执行，API 通过状态查询进度；
    Outbox 保证任务不丢失，JetStream 重试 + DLQ。
  - 首版单文件 10 MB / 20,000 行；文件保留 30 天、行数据保留 180 天。
- 本阶段**未**产生代码、迁移或容器变更；实际开发排在第二阶段 2B
  （2B-1 同步骨架、2B-2 NATS/Worker、2B-3 Excel 与增强）。
- 设计决策待评审项见文档 §13，合并前需确认默认交易状态、账户映射方式和
  数据保留策略。

## Task 006（Phase 2E）已完成

- 新增 `app/modules/transfers/`（router / schemas / service），注册到 `/api/v1`：
  - `GET/POST /transfers`
  - `GET/PUT/DELETE /transfers/{id}`
  - `POST /transfers/{id}/reverse`
- 支持同币种转账、跨币种转账、同账户换汇；完全相同的账户 + 币种返回
  `TRANSFER_SOURCE_SAME`。
- `to_amount` 为入账权威值，`exchange_rate` 仅记录成交比价；跨币种缺省时按
  `to_amount / from_amount` 记录，不强制与金额相乘一致。
- `base_amount` 固化家庭本位币价值：任一侧为本位币直接取值；两侧均非本位币
  必须提供请求字段 `base_exchange_rate`（不新增数据库列）。
- 手续费独立于本金，从转出账户以 `fee_currency` 扣除；确认时同事务生成
  `金融手续费` 衍生支出（`source=system`、`transfer_id`、`base_amount`）。
  手续费为第三种币种时必须提供 `fee_exchange_rate`。
- 状态机 `draft → confirmed → reversed`：仅 draft 可修改/删除，confirmed 通过
  `PUT status=confirmed` 确认、通过 `POST /reverse` 冲正，reversed 为终态。
- 冲正同事务完成：原转账置 reversed、生成反向转账、原手续费支出置 reversed、
  生成反向收入并写 `transaction.reverse` 审计；冲正生成的转账不可再次冲正。
- Phase 1 负余额规则覆盖本金 + 同币种手续费合计；确认或冲正转出资金不足返回
  409 `INSUFFICIENT_BALANCE`。
- 余额与统计自动联动：转账本金不计收支；手续费衍生支出恰好计一次；
  `account-balances` / `overview` 已用真实转账回归。
- 错误码：`TRANSFER_NOT_FOUND`、`TRANSFER_NOT_EDITABLE`、
  `TRANSFER_NOT_DELETABLE`、`TRANSFER_NOT_REVERSIBLE`、`TRANSFER_SOURCE_SAME`、
  `BASE_EXCHANGE_RATE_REQUIRED`、`FEE_EXCHANGE_RATE_REQUIRED`、
  `AMOUNT_INVALID`，并复用 `ACCOUNT_INACTIVE`、`INSUFFICIENT_BALANCE`。
- 未新增迁移：`finance.transfers` 表在 `0002_phase_1_1` 中已就绪。
- 测试：新增 `tests/test_transfers.py`（16 项）；全量 90 项通过，覆盖率
  98.58%；ruff / mypy strict 通过。

### Phase 2E 已知边界

- 转账本金不做运行时币种折算，余额类统计仍只出分币种明细。
- `fee_exchange_rate` / `base_exchange_rate` 仅作为请求字段，不落库；
  草稿更新第三种币种手续费时需要重新提供汇率。
- 不支持批量转账、模板转账或定时转账。

## Task 007（Phase 2B-1）已完成

- 新增迁移 `0003_phase_2b_1`：`system.import_batches` / `system.import_rows`，
  含状态 CHECK、`UNIQUE (batch_id, row_number)`、批次/行/哈希/交易索引。
- 新增 `app/modules/imports/`（models / schemas / service / router），注册到 `/api/v1`：
  - `POST/GET /imports`
  - `GET/DELETE /imports/{id}`
  - `PUT /imports/{id}/mapping`
  - `POST /imports/{id}/preview`
  - `GET /imports/{id}/rows`
  - `PUT /imports/{id}/rows/{row_id}`
  - `POST /imports/{id}/confirm`
  - `POST /imports/{id}/cancel`
- 上传：`multipart/form-data`；CSV 编码 `utf-8-sig` → `gb18030`，分隔符自动探测；
  文件 SHA-256 文件级去重（`allow_duplicate_file=true` 可覆盖）。
- 映射：四种金额方向模式（`signed_positive_income` / `signed_positive_expense` /
  `type_column` / `debit_credit`）、方向映射、分类映射/默认分类、账户列映射、
  日期格式与编码/分隔符；保存时校验必填字段与源列存在。
- 预览：同步重新解析文件并重建行数据，逐行收集 `DATE_INVALID`、`AMOUNT_INVALID`、
  `AMOUNT_PRECISION`、`CURRENCY_INVALID`、`EXCHANGE_RATE_REQUIRED`、
  `CATEGORY_*`、`ACCOUNT_*`、`ROW_SHAPE_INVALID` 等错误；有效/无效/重复计数。
- 去重：外部流水号 → 精确指纹 → 批内重复；限定当前 household，排除开账与转账
  衍生流水；模糊匹配未启用。
- 确认：同步执行，默认 `create_status=confirmed`，可选 `draft`；
  `on_duplicate=skip|allow`；逐行 savepoint，单行失败不中断整批；
  确认态支出执行负余额校验，无绕过开关。结果 `completed|partial|failed`，
  重复确认已完成批次幂等返回。
- 导入流水 `source='import'`，固化 `base_amount`；只导入 `income`/`expense`。
- 文件落 `IMPORT_STORAGE_DIR`（默认 `/tmp/homeatlas-imports`）；新增配置
  `IMPORT_MAX_FILE_MB=10`、`IMPORT_MAX_ROWS=20000`；依赖新增 `python-multipart`。
- 审计：`import.create/mapping/preview/confirm/execute/row_update/cancel/delete`。
- 测试：新增 `tests/test_imports.py`（9 项）；全量 99 项通过，覆盖率 97.46%；
  ruff / mypy strict 通过。

### Phase 2B-1 已知边界

- 预览会删除并重建 `import_rows`，再次预览会丢失手工修正；修正应在首次预览后完成。
- 仅支持 CSV；`.xlsx`、模板下载、模糊去重、批量修正留到 2B-3。
- 同步执行受 API 请求时长限制；NATS JetStream、Outbox Publisher、Import Worker、
  共享文件卷与进度查询留到 2B-2。
- 文件保存在 API 容器本地目录，容器重建后文件丢失；批次会返回
  `IMPORT_FILE_MISSING`，需重新上传。
