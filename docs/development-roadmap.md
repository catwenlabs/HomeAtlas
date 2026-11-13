# Development Roadmap

完整规格见 [specification.md](specification.md) §8–§11。当前进度：

| Phase | 内容 | 状态 |
| -- | -- | -- |
| 1.0 Task 001 | 基础设施：FastAPI + SQLAlchemy + Alembic + Compose + CI + 探针 | ✅ 完成 |
| 1.1 Task 002 | 基础数据模型：households/accounts/currencies/categories/balances + seed + opening_balance | ✅ 完成 |
| 1.2 Task 003 | 收支管理 API：状态机、冲正、审计、完整查询筛选 | ✅ 完成 |
| 1.4 | 统计 API：收支类 + 余额类分币种明细、家庭时区分组 | ✅ 完成（Task 004） |
| 1.5 | 数据导入预留：接口、模型、去重与异步流程设计评审 | ✅ 设计评审完成（实现移至 2B） |
| 2A | JWT 认证、首次部署初始化向导、React Web 前端 | ✅ 完成（Task 009） |
| 2B-2 | 异步导入：NATS JetStream + Outbox + Worker | ⏸ 暂缓 |
| 2C-1 | 汇率表、credit/透支账户、净资产快照与总览 | ✅ 完成（Task 010） |
| 2C-2 | 投资与标签、入金/赎回闭环、持股快照与行情估值 | ✅ 完成（Task 011） |
| 2C-3 | 贷款与负债端 | ✅ 完成（Task 012） |
| 2C-4 | Web：资产负债页、图表、到期提醒 | ⬜ 待实施 |
| 2D | Grafana | ⬜ 2C 之后 |
| 2B-1 | 数据导入同步骨架：CSV 上传、映射、预览/去重、确认生成交易 | ✅ 完成（Task 007） |
| 2B-3 | 数据导入增强：Excel、模板下载、模糊去重、批量行修正 | ✅ 完成（Task 008） |
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
- `X-Household-Id` 作用域依赖：单家庭兜底、多家庭 400、未知家庭 404（Phase 2A 已改为 JWT 派生）。
- 初始余额为 `opening_balance` 确认态单边流水，支持负数、多币种（非本位币需汇率），
  每次设置/修改写入 `system.audit_logs`。
- 测试：pytest 43 项；覆盖率 98%（CI 门槛 80%）。

### 已知边界（留给后续阶段）

- 转账 API 已由 Task 006（2E）补齐；`finance.transfers` 表与余额计算在此阶段已就绪。
- `account_balances` 仅提供读取（账面余额/对账历史），快照写入接口未在 §6 定义，
  留待对账功能设计时补齐。
- 默认家庭由迁移创建；新建家庭会自动克隆默认分类树（Phase 2A 已移除迁移 seed，基础数据改由首次部署向导确认后写入）。

## 验收复查（Task 002）

- `alembic upgrade head` 建表 + seed 成功；降级可回滚（seed 已在 Phase 2A 移除）。
- 可创建家庭/账户/分类；可设置与修改初始余额并查询审计记录。
- 多币种开账正确（汇率必填、按币种精度 half-even 取整）。
- 跨家庭 parent、越级 parent、自引用、系统手续费删除均被拒绝。
- `X-Household-Id` 兜底/400/404 行为通过测试（Phase 2A 起由 Bearer 认证替代）。

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
- 无认证，审计 `actor` 固定为 `system`（Phase 2A 已补齐 JWT 认证与用户级 actor）。

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
  其中 2B-2 异步化已决定**暂缓**，见下方 Task 007 记录。
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

### Task 008（Phase 2B-3）已完成（2026-11-12）

- Excel `.xlsx` / `.xlsm` 上传与解析：`openpyxl` 读取首个工作表，复用映射/预览/
  确认链路；日期与数字单元格做确定性字符串化；扩展名与 `source_format` 不匹配
  返回 415。
- 模板下载：`GET /api/v1/imports/template?format=csv|xlsx`，返回标准 11 列与两行
  示例。
- 模糊去重：默认关闭；开启后按同账户、同类型、同币种、金额相等、日期相差
  ≤ 1 天、描述相似度 ≥ 0.85 标记 `duplicate`，并在行错误中给出 `DUPLICATE_FUZZY`
  与相似度；阈值与日期窗口可配置。
- 批量行操作：`PUT /imports/{id}/rows` 批量修正/标记（最多 500 条），
  `POST /imports/{id}/rows/skip` 按 `invalid|duplicate|pending|valid` 范围跳过；
  计数统一重算，并写审计 `import.rows_bulk_update` / `import.rows_bulk_skip`。
- 文件按 `{batch_id}.csv` / `{batch_id}.xlsx` 存储；依赖新增 `openpyxl`。
- 测试：`tests/test_imports.py` 扩到 13 项；全量 **103 项通过，覆盖率 96.91%**；
  ruff / mypy strict 通过。

### Phase 2B-3 已知边界

- XLSX 只读第一个工作表，不支持 `.xls`、宏执行与外部链接。
- 模糊去重只在映射参数开启时生效，命中仅标记为 `duplicate`，不自动物理删除。
- 预览仍会重建行数据，批量修正应在预览后、确认前完成。

### Task 009（Phase 2A）已完成（2026-11-12）

- 用户与认证：新增 `core.users`（`household_id`、`username`、`password_hash`、
  `display_name`、`role=owner|member`、`is_active`），一个家庭可绑定多个成员；
  `users.household_id` 多对一，业务数据仍以 household 为作用域。迁移
  `20261112_0004_phase_2a_users` 负责建表，并在无业务数据时清理旧默认家庭。
- JWT Bearer（HS256）：claims 含 `sub`(user_id)、`household_id`、`role`、`username`、
  `exp`、`iat`；`POST /auth/login`、`GET /auth/me`、`POST /auth/logout`；
  密码使用 bcrypt。新配置 `JWT_SECRET_KEY`、`ACCESS_TOKEN_EXPIRE_MINUTES`（默认 7 天）。
- 首次初始化：`GET /setup/status`、`GET /setup/options`（仅预填）、`POST /setup`
  （无用户时可调用）。一次写入用户确认的币种、家庭、owner 与分类，重复调用返回
  409 `SETUP_ALREADY_COMPLETED`；本位币不在所选币种中返回 400
  `BASE_CURRENCY_NOT_SELECTED`。`currency_codes` / `categories` 为 `null` 用全部
  内置项；`categories: []` 表示不写入分类，`currency_codes` 必须包含本位币。
- 原则：**迁移不再写入任何用户基础数据**。`0002` 的币种/家庭/分类 seed 已移除；
  币种与分类目录改为代码内置（`currencies/defaults.py`、`categories/defaults.py`），
  仅作为向导预填项。家庭只由初始化向导创建，不再提供 `POST /households`。
- 作用域：移除 `X-Household-Id`，household 一律由 JWT 派生；`/api/v1` 业务路由
  统一要求 Bearer，`/health`、`/ready`、`/setup/*`、`/auth/login` 保持公开。
- 成员管理：owner 可列出/新增/修改成员（显示名、角色、密码、停用），
  保护最后一个 active owner 不被降级或停用。
- 审计：新增请求级 actor 上下文（`app/core/context.py`），`write_audit` 写入
  当前用户名；系统动作仍为 `system`。
- Web：Vite + React 19 + TypeScript + Tailwind；TanStack Query/Router、Zustand、
  Axios、Lucide。页面：初始化向导、登录、总览、账户、收支、分类、转账、统计、
  导入、设置；向导预填币种/分类复选，确认后才提交。
- 部署：`apps/web` 多阶段构建（Node 构建 + nginx 托管），nginx 反代 `/api`
  到 `api:8000`；compose 增加 `web` 服务与 `WEB_BIND`（默认 `127.0.0.1:8080`）；
  `.env.example` 增加 `JWT_SECRET_KEY` 与 `WEB_BIND`。
- 测试：新增 `tests/test_auth.py` 并改造 `conftest.py`（每测 truncate + setup +
  默认 Bearer）；全量 **108 项通过，覆盖率 96.85%**；ruff / mypy strict 通过；
  前端 `npm run build`（tsc + vite）通过。

### Phase 2A 已知边界

- JWT 无刷新令牌与登出黑名单；`POST /auth/logout` 仅作语义占位，客户端丢弃 token。
- 初始化只能执行一次；忘记管理员密码需要直接改库或重建环境。
- 前端暂无离线缓存与移动端原生壳；导入行编辑仅支持“跳过”，完整字段修正走 API。
- 家庭切换未开放（符合“一用户一家庭”的产品约束）。

### 决策：2B-2 异步化暂缓（2026-11-11）

- 暂不引入 NATS JetStream、Outbox Publisher、Import Worker 与共享 `import_data`
  卷；CSV 导入继续在 API 内同步执行。
- 理由：当前自托管单家庭场景下，10 MB / 20,000 行的同步链路已够用；异步化会
  新增 NATS、Worker、Outbox 与共享卷的运维复杂度。
- 上述已知边界（请求时长、容器本地文件、预览重建）在暂缓期间保留，README 与
  `import-design.md` 已记录。
- 触发条件：数据量或文件规模增长、需要后台进度查询或跨实例部署时，再按
  `docs/import-design.md` §12 的 2B-2 方案实施。

## Task 010（Phase 2C-1）已完成（2026-11-13）

- 迁移 `20261113_0005_phase_2c_1`：`finance.exchange_rates`（§4.1 全列、
  `UNIQUE(household, base, quote, rate_date)`、`rate > 0`、`base <> quote`）、
  `core.accounts` 扩展（`account_type` CHECK 增 `credit`/`investment`；可空列
  `annual_rate Numeric(12,8)`、`liquidity`、`credit_limit Numeric(24,8)` 均带
  CHECK）、`finance.net_worth_snapshots`（§4.7 全列，含 JSONB
  `currency_breakdown` / `fx_rates_used`，`UNIQUE(household_id, snapshot_date)`）。
  升级/降级往返验证通过。
- 汇率模块 `app/modules/exchange_rates/`（`/api/v1`，Bearer）：
  - `GET /exchange-rates`（分页，币对/日期区间筛选）、`POST /exchange-rates`、
    `GET /exchange-rates/latest?base=&quote=[&date=]`（响应带
    `direction: direct|inverse` 与 `source_pair`）、`DELETE /exchange-rates/{id}`。
  - 取数规则（§4.1）：`rate_date <= 查询日` 最新直连 → 反向 `1/rate`（12 位
    half-even）→ 缺失抛 `EXCHANGE_RATE_NOT_FOUND`；不做三角套算。
  - 校验：`rate <= 0` / `base = quote` → 422 `EXCHANGE_RATE_VALUE_INVALID`
    （与 transactions 既有 400 `EXCHANGE_RATE_INVALID` 不撞）；同家庭+币对+日期
    重复 → 409 `EXCHANGE_RATE_DUPLICATE`；币种不存在 → 404 `CURRENCY_NOT_FOUND`。
  - 审计：`exchange_rate.create/delete`。
- credit 账户与负余额（§5.1）：
  - 公共守卫 `app/modules/accounts/guards.py`：`withdrawal_violation`（纯函数，
    返回错误码）+ `ensure_withdrawable`（抛出版）。非 credit 账户透支 →
    `INSUFFICIENT_BALANCE`；credit 账户放行，`credit_limit` 非空且
    `abs(新余额) > credit_limit` → `CREDIT_LIMIT_EXCEEDED`（409）；
    `credit_limit IS NULL` 不校验；透支恰好等于额度放行。
  - 替换全部 7 个校验点：transactions 创建/确认/冲正收入
    （`transactions/service.py`）、transfers 创建/确认/冲正
    （`transfers/service.py`，`_ensure_balance` 改为委托守卫）、imports 确认
    （`imports/service.py` 用非抛出版落行级错误）。两个旧私有 helper 删除，
    守卫单一来源。
- 账户扩展（§4.2/§6.3）：`POST/PUT /accounts` 接受可选
  `annual_rate` / `liquidity` / `credit_limit`（Pydantic ge=0 与枚举校验），
  响应同步带出；**已有任何流水或转账的账户禁改 `account_type`**（409
  `ACCOUNT_TYPE_IMMUTABLE`，H8 收窄；新错误码已回写 asset-design §8）；
  三个新字段随时可改。credit 负数开账沿用 opening_balance 豁免恒正。
- 总览与快照（§5.2/§5.3/§5.4/§6.5）`app/modules/assets/`：
  - `GET /assets/summary` 实时计算：复用 `get_household_book_balances`，
    非投资账户正余额 = 现金、负余额 = 负债，investment 账户余额全额计入
    「理财中」；净资产 = 现金 + 投资账户余额 − 负债（2C-2/2C-3 项：浮盈、
    unmanaged、贷款固定为 0，字段占位）。分桶（闲置/理财中/已到期）、
    `unmapped_cash`（2C-1 = 投资账户余额，尚无投资登记）、`inactive_count`、
    分币种明细含 `fx_rate`；缺任一币对 → 400 `EXCHANGE_RATE_NOT_FOUND`，
    `data.missing` 带缺口清单（AppError 新增 `details` 通道，透传至错误
    envelope 的 `data`，向后兼容）。单币种家庭恒等折算、不查表。
  - 日利息：非投资账户按其**默认币种**余额（决策：多币种账户只对默认币种
    计息）`max(balance,0) × annual_rate / 365`，折算本位币；credit 负余额
    不计负利息；贷款端 2C-3 接入。
  - `POST /assets/snapshots`：无 body，日期 = 家庭时区今日；按
    `UNIQUE(household_id, snapshot_date)` upsert（201 新建 / 200 更新），
    固化 `fx_rates_used` 与 `currency_breakdown`；缺汇率整体失败且不落行，
    审计 `net_worth.snapshot.create` / `.update` 分支单列。
  - `GET /assets/snapshots`（分页 + 日期区间，默认按日期升序）、
    `GET /assets/snapshots/monthly?year=`：月度聚合（首末快照净资产差、
    日利息合计、快照天数），只含有快照的月份，单快照月 `net_change = 0`。
- 既有 statistics 端点零改动：分币种明细本就含负值，合计语义不变；
  总额折算的正式出口是 `/assets/summary` 与快照（§5.3 口径）。
- 测试：新增 `tests/test_exchange_rates.py`（7 项）、`tests/test_assets.py`
  （8 项）、credit 语义扩展 test_accounts/test_transactions/test_transfers/
  test_imports；conftest TRUNCATE 清单补 `finance.exchange_rates` /
  `finance.net_worth_snapshots`。全量 **143 项通过，覆盖率 97.15%**；
  ruff / ruff format / mypy strict 通过。

### Phase 2C-1 已知边界

- 快照只记当日（家庭时区），不支持历史补录；`SNAPSHOT_DATE_INVALID`
  留在错误码表但无触发路径。
- `unmapped_cash` 在 2C-1 恒等于投资账户余额（无投资登记可对账），
  2C-2 引入 investments 后改为「投资账户余额 − Σ managed principal」。
- 日利息是估算口径，不产生流水；贷款利息（支出端）随 2C-3。
- 汇率为家庭视角手工录入，无行情源与自动更新；反向取数不做精度
  二次校验（1/rate 已按 12 位 half-even 取整）。

## Task 011（Phase 2C-2）已完成（2026-11-14）

- 迁移 `20261114_0006_phase_2c_2`：`finance.investments`（§4.4 全列，含
  `realized_pnl` / `pre_redeem_value`）、`finance.investment_tags`（UNIQUE
  家庭+名称）、`finance.investment_tag_links`（复合 PK，DB 级联）、
  `finance.investment_transfers`（§4.6：复合 PK + transfer_id 唯一）、
  `finance.holdings`（市场+代码+数量+成本单价，UNIQUE 投资内仓位）。
  升级/降级往返验证通过。
- 投资模块 `app/modules/investments/`（service / flows / linkage / tags /
  holdings / router）：
  - **建仓**：`account_id` 可空 —— 带则为 managed（校验 investment 类型 +
    同家庭 + 同币种，否则 422 `INVESTMENT_ACCOUNT_INVALID`），不带即
    unmanaged 独立快照（推荐路径：股票只做登记，不进账户体系）。可选
    `fund_transfer` 同事务入金：复用 `_resolve_terms` + 新拆的
    `_persist_transfer`（无 commit 内核），守卫失败整笔回滚（不留投资行、
    不留孤儿转账）；`principal += to_amount`，`current_value` 随第一笔入金
    初始化。跨币种入金要求显式 `exchange_rate`；两侧均非本位币时从
    `finance.exchange_rates` 取 base 汇率（缺则 400 带缺口）。
  - **追加入金** `POST /investments/{id}/fund`、**估值唯一入口**
    `PUT /value`（浮盈不计收支）、**PUT 收窄**（managed 的 principal /
    account_id / currency 拒改 409 `INVESTMENT_NOT_EDITABLE`；unmanaged
    principal 可改）、**DELETE** 仅 active 且无未冲正关联转账（409
    `INVESTMENT_HAS_TRANSFERS`，链接行显式清理）。
  - **赎回闭环**（C1 固定顺序）：① 衍生 pnl 流水先落投资账户（盈利→
    「投资收益」收入 / 亏损→「投资亏损」支出，金额 |pnl|，transfer_id
    待转账落库后回填——此刻账户余额恰等于 to_amount）；② 资金转账回
    现金账户（守卫自然通过）；③ 置 redeemed + `realized_pnl` +
    `current_value=0` + 留存 `pre_redeem_value`。赎回要求 managed +
    to_account 同币种（422 `REDEEM_AMOUNT_INVALID`）；base 汇率可请求
    覆盖，缺省查汇率表。账面断言：投资账户 −principal、现金 +to_amount、
    收支统计 +pnl 恰一次。
  - **到期**：`matured` 为查询期派生态（`end_date <= 今日(household tz)
    AND status='active'`），不落库；`GET /investments?status=` 三态筛选。
  - **冲正联动**（linkage.py，在 `reverse_transfer` 同事务最前方执行）：
    冲正入金转账等额调减 principal（<0 或投资已 redeemed → 409
    `TRANSFER_LINKED_TO_INVESTMENT`，提示先冲正赎回）；冲正赎回转账回滚
    status/realized_pnl/current_value（`pre_redeem_value` 快照），衍生
    pnl 流水随行冲正。`reverse_transfer` 衍生冲正查询泛化为全部
    confirmed 衍生流水（原仅 EXPENSE，赎回盈利的衍生收入现在也能冲正），
    `_reverse_fee_transaction` 泛化为 `_reverse_derived_transaction`
    （方向按原流水翻转）。
- 持股与行情（本次决策并入，asset-design §2.2 的暂缓项按需求提前）：
  - `finance.holdings`：市场（SH/SZ/HK/US）+ 代码 + 数量 + 成本单价；
    仅 stock/fund 投资可挂（422 `HOLDING_NOT_SUPPORTED`），市场币种必须
    等于投资币种（422 `HOLDING_CURRENCY_MISMATCH`）；持仓成本
    `Σ quantity × cost_price` 与投资 principal 并列展示作对账参考，
    **不进净资产公式**。拆股/送股手动改数量；成本自动核算（移动加权）
    留待未来 `finance.trades`，表结构前向兼容。
  - `app/modules/market/`：`GET /market/quotes?symbols=SH:600519,...`
    （MARKET:SYMBOL 格式，单次 ≤50）；Provider 抽象 + 腾讯免 key 实现
    （SH/SZ/HK/US，GBK 解析、字段容错）+ FakeProvider（确定性哈希价，
    CI 零出网，conftest 注入 `QUOTE_PROVIDER=fake`）；30s 内存缓存、
    5s 超时、可选 `QUOTE_PROXY_URL`；失败 502
    `QUOTE_PROVIDER_ERROR`（details 带失败代码清单）；行情为信息性数据
    不落库，出网请求只携带代码。
  - `POST /investments/{id}/refresh-value`：按全部持股拉价，`Σ 数量×现价`
    **自动写入 current_value**（复用 value 审计路径，after 带
    `source=quote` 与逐股 breakdown），响应返回新旧估值与逐股明细；
    无持股 422。
- 净资产公式完整版（assets/service.py）：`net = 现金 + Σ投资账户余额 +
  Σ_managed 浮盈(current_value−principal) + Σ_unmanaged current_value −
  负债`；`unrealized_pnl`、`unmapped_cash`（= 投资账户余额 − Σ_managed
  principal，可负）落地；matured 计入净资产但移入「已到期」分桶并输出
  `matured_investments` 列表（M9 回归）；日利息纳入投资项
  （current_value × annual_rate / 365）；分币种 breakdown 的 invested
  改为登记口径（managed principal + unmanaged current_value）。
- 内置分类双通道：defaults.py 预填「投资收益」「投资亏损」（新家庭向导
  可见，默认分类 11 → 13）；存量家庭运行时兜底（照抄 `_fee_category`
  模式）。setup 向导行为不变（新列均可空）。
- 审计：`investment.create/fund/update/value/tags/redeem/delete`、
  `investment.fund_reverse/redeem_reverse`、`investment.holding.*`、
  `investment_tag.*`；衍生 pnl 另写 `transaction.create`（带
  investment_id 上下文）。
- 测试：新增 `tests/test_investments.py`（16 项：建仓/入金/守卫回滚/
  PUT 收窄/删除规则/盈亏赎回账面/校验矩阵/全链路冲正还原/到期派生/
  标签/持股/行情刷新/缓存与 502/跨币种汇率表）+ test_assets 四象限
  净资产回归。全量 **160 项通过，覆盖率 95.91%**；ruff / mypy strict
  通过；迁移往返验证通过。

### Phase 2C-2 已知边界

- 赎回仅全额、仅同币种 to_account；跨币种赎回随需求放开。
- 加仓/减仓/卖出与移动加权成本核算未实现（预留 `finance.trades`）；
  手工改 holdings 数量/单价即手工修正。
- 行情按需拉取（打开页面/点刷新），无后台定时估值；腾讯接口为非官方
  免 key 通道，可能变动，Provider 可替换。
- refresh-value 仅覆盖 stock/fund 投资且要求全部持股行情可得，任一
  失败整体 502（宁可失败不写半价）。
- 分桶 invested 为登记口径；投资账户内的未映射现金体现在
  `unmapped_cash`（含负值诊断），不进分桶。

## Task 012（Phase 2C-3）已完成（2026-11-14）

- 迁移 `20261114_0007_phase_2c_3`：`finance.loans`（§4.3 全列，CHECK 含
  `principal > 0`、`due_day 1..31`、`repayment_type IN
  ('monthly_interest','one_time')`、`0 <= remaining_principal <= principal`、
  household+status 索引）。升级/降级往返验证通过。
- 贷款模块 `app/modules/loans/`（`/api/v1`，Bearer）：
  - `GET /loans?status=active|settled`（分页 + 排序白名单）、`POST /loans`、
    `GET/PUT/DELETE /loans/{id}`、`POST /loans/{id}/settle {settled_date}`。
  - 轻模型落地：无每期还款表；还款是普通支出流水（默认分类新增系统建议
    「贷款还款」，双通道预填/兜底，默认分类 13 → 14）；`linked_account_id`
    仅作扣款提示（同家庭校验，不校验币种/活跃）。
  - `remaining_principal` 默认 = principal，登记存量贷款可显式传入较小值
    （`<= principal` 双层校验：Pydantic 422 + DB CHECK；PUT 超出 422
    `LOAN_REMAINING_INVALID`）；日常手动维护走 PUT。
  - 状态机 `active → settled`（terminal、不可逆）：`settle` 允许
    `remaining_principal > 0` 的提前结清并置 0、落 `settled_date`；settled
    后 PUT / DELETE / 重复 settle 分别返回 409 `LOAN_NOT_EDITABLE` /
    `LOAN_NOT_DELETABLE` / `LOAN_ALREADY_SETTLED`（对齐 §8 设计码）。
  - 响应带派生 `daily_interest`（remaining × annual_rate / 365，估算口径
    不产生流水）。
- 净资产联动（assets）：active 贷款 `remaining_principal` 按币种并入
  `total_liabilities`（净资产公式减项）；`daily_interest_expense` 从常量 0
  变为 Σ active 贷款日利息（分币种折算）；分币种 breakdown 的 liabilities
  含贷款；快照同步固化。多币种贷款缺汇率 → summary/快照 400 带缺口清单
  （复用 2C-1 机制）。
- 审计：`loan.create/update/settle/delete`。
- 测试：新增 `tests/test_loans.py`（6 项：CRUD 与默认值、存量登记、校验
  矩阵（零本金/超额剩余/坏还款日/坏币种/跨家庭关联账户）、settle 语义与
  审计、净资产 + 日利息联动 + 快照、外币贷款折算与缺汇率）。全量
  **166 项通过，覆盖率 95.80%**；ruff / mypy strict 通过。

### Phase 2C-3 已知边界

- 还款流水与贷款无外键关联，DELETE 仅校验 active（「无关联还款流水」不可
  判定，按 active 门槛落地）；还款自动联动 remaining_principal 待使用
  反馈后评估（§13.3 定案不变）。
- `settled_date` 不做未来日期校验（KISS）。
- 无批量导入与摊销计划表（§3 非目标）。
