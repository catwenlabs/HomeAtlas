# 数据导入设计评审（Phase 1.5）

> 状态：**设计评审完成（2026-11-11）；Phase 2B-1 同步骨架已实现**。
> 2B-1 已落地 CSV 上传、字段映射、同步预览、去重、人工确认与交易生成；
> NATS/Worker 异步化（2B-2）与 Excel/模糊去重（2B-3）仍按本文后续章节推进。
>
> 依据：`specification.md` §8 Phase 1.5、§10 第二阶段 B；现有交易/余额/统计规则
> 见 `architecture.md`、`database.md`。实现记录见本文 §15。

## 1. 目标与范围

### 目标

- 支持 CSV / Excel 文件上传。
- 字段映射（列名 → 标准字段）与导入参数配置。
- 原始数据保存，导入前可预览、逐行修正。
- 重复检测（文件级 + 行级）。
- 人工确认后正式生成 `finance.transactions`。
- 导入过程可追踪、可重试、失败可定位。
- 与现有 household 作用域、审计、余额和统计规则一致。

### 非目标（2B 首版不做）

- 银行 API / 开放银行直连。
- 自动抓取邮件或网银导出文件。
- 转账、开账余额导入（只导入 `income` / `expense`）。
- 复杂规则引擎、脚本化转换。
- 多文件合并为同一批次。
- 前端页面（属于 2A，导入 API 先就绪）。

### 硬约束

- 导入流水 `source = 'import'`，与手工录入可区分。
- 金额使用 `NUMERIC` / `Decimal`，禁止 float。
- 日期按家庭时区解释；无时区信息时使用 `household.timezone`。
- 外币流水必须固化 `base_amount`；没有汇率列且币种 ≠ 本位币时该行判为无效。
- 导入不得绕过现有校验：账户/分类归属、分类类型、金额精度、负余额规则。
- 所有导入写 `system.audit_logs`，动作包含 `import.create/preview/confirm/execute`。

## 2. 用户流程与状态机

```text
上传文件
  → uploaded（解析表头，返回列样例）
  → mapped（用户提交字段映射）
  → previewed（逐行校验，展示有效/无效/重复）
  → confirmed（人工确认，等待执行）
  → processing（Worker 逐行写入）
  → completed | partial | failed
```

- `uploaded` / `mapped` / `previewed` / `confirmed` 可取消 → `cancelled`。
- `processing` 只能请求取消，Worker 在当前块结束后停止 → `cancelled`。
- `completed` / `partial` / `failed` 为终态；可重新上传新批次。
- `partial`：部分行成功，部分行无效或重复（按跳过策略）。

### 批次状态

| 状态 | 含义 |
| -- | -- |
| `uploaded` | 文件已保存，表头已解析 |
| `mapped` | 映射已保存，尚未预览 |
| `previewed` | 已完成逐行校验 |
| `confirmed` | 已人工确认，等待 Worker |
| `processing` | Worker 正在写入 |
| `completed` | 全部有效行导入成功 |
| `partial` | 部分成功，存在无效/重复/失败行 |
| `failed` | 批次级失败（文件损坏、Worker 异常、超时） |
| `cancelled` | 用户取消 |
| `expired` | 超过保留期，文件/行数据已清理 |

### 行状态

| 状态 | 含义 |
| -- | -- |
| `pending` | 尚未校验 |
| `valid` | 校验通过，待导入 |
| `invalid` | 校验失败，带 `errors` |
| `duplicate` | 判定重复，默认跳过 |
| `imported` | 已生成交易流水 |
| `skipped` | 用户或策略跳过 |

## 3. API 草案（`/api/v1/imports`）

统一 envelope、`X-Household-Id` 作用域；上传支持 `Idempotency-Key`（2B-1 暂未启用），
确认通过状态机天然幂等。2B-1 已实现下表端点（`GET /imports/{id}/template` 除外）。

| 方法 | 路径 | 说明 |
| -- | -- | -- |
| `POST` | `/imports` | `multipart/form-data` 上传文件，创建批次 |
| `GET` | `/imports` | 批次列表，支持 `status`、分页 |
| `GET` | `/imports/{id}` | 批次详情与计数 |
| `PUT` | `/imports/{id}/mapping` | 保存字段映射与导入参数 |
| `POST` | `/imports/{id}/preview` | 校验全部行（异步任务） |
| `GET` | `/imports/{id}/rows` | 行列表，支持 `status`、分页 |
| `PUT` | `/imports/{id}/rows/{row_id}` | 手工修正单行规范化数据 |
| `POST` | `/imports/{id}/confirm` | 人工确认并触发正式导入 |
| `POST` | `/imports/{id}/cancel` | 取消未开始或处理中的批次 |
| `DELETE` | `/imports/{id}` | 删除未确认批次（级联文件与行） |
| `GET` | `/imports/{id}/template` | 可选：下载 CSV 模板 |

### 3.1 上传

```http
POST /api/v1/imports
Content-Type: multipart/form-data

file=@alipay-2026-06.csv
source_format=csv
account_id=<默认目标账户>
```

响应 `201`：

```json
{
  "success": true,
  "data": {
    "id": "<batch-id>",
    "status": "uploaded",
    "source_format": "csv",
    "original_filename": "alipay-2026-06.csv",
    "file_sha256": "...",
    "columns": ["交易日期", "金额", "收支方向", "备注"],
    "sample_rows": [["2026-06-01", "30.00", "支出", "午餐"]],
    "total_rows": 128
  },
  "message": null
}
```

- 上传阶段只解析表头与有限行样例，不做完整校验。
- 文件落共享卷，数据库存路径、大小、SHA-256，不存二进制。
- 同一 household 已存在相同 `file_sha256` 的成功批次时返回 `409 IMPORT_FILE_DUPLICATE`，可用 `allow_duplicate_file=true` 覆盖。

### 3.2 映射

```json
{
  "header_row": 1,
  "delimiter": ",",
  "encoding": "utf-8",
  "columns": {
    "transaction_date": "交易日期",
    "amount": "金额",
    "direction": "收支方向",
    "description": "备注",
    "category": "分类",
    "currency": "币种",
    "external_id": "流水号"
  },
  "amount_mode": "signed_positive_income",
  "direction_map": {"收入": "income", "支出": "expense"},
  "default_category_id": null,
  "category_map": {"餐饮美食": "<category-uuid>"},
  "date_formats": ["%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"]
}
```

`amount_mode`：

- `signed_positive_income`：正数收入、负数支出（默认）。
- `signed_positive_expense`：正数支出、负数收入。
- `type_column`：金额恒正，方向由 `direction` 列决定。
- `debit_credit`：`debit` 列支出、`credit` 列收入，两列最多一列有值。

映射保存到 `mapping JSONB`，带 `mapping_version`，便于追溯/重新预览。

### 3.3 预览

```http
POST /api/v1/imports/{id}/preview
```

返回批次摘要与预览结果。2B-1 在 API 内同步解析、校验并重建 `import_rows`，
直接返回 `200` 与 `previewed` 结果；2B-2 对超大批次再切换为 `202` + Worker 进度查询：

```json
{
  "status": "previewed",
  "total_rows": 128,
  "valid_rows": 120,
  "invalid_rows": 5,
  "duplicate_rows": 3,
  "preview": [
    {
      "row_number": 1,
      "status": "valid",
      "normalized": {
        "transaction_date": "2026-06-01T12:00:00+08:00",
        "transaction_type": "expense",
        "amount": "30.00",
        "currency": "CNY",
        "description": "午餐",
        "category_id": "..."
      },
      "errors": []
    },
    {
      "row_number": 2,
      "status": "invalid",
      "errors": [
        {"code": "AMOUNT_INVALID", "field": "amount", "message": "金额必须大于 0"}
      ]
    }
  ]
}
```

### 3.4 确认与执行

```http
POST /api/v1/imports/{id}/confirm
Content-Type: application/json

{
  "on_duplicate": "skip",
  "create_status": "confirmed"
}
```

- `on_duplicate`：`skip`（默认）/ `allow`。
- `create_status`：`confirmed`（默认）/ `draft`。
- 负余额规则始终生效，不提供绕过开关；`create_status=draft` 时不执行确认态
  余额校验。
- 2B-1 同步执行：确认请求内逐行写入交易，返回 `200` 与批次终态
  `completed` / `partial` / `failed`；2B-2 再改为返回 `202`、批次进入 `confirmed`
  并由 Worker 拉取为 `processing`。
- 重复确认幂等：`completed` / `partial` 批次直接返回当前结果，不重复写入。
- 每行使用 savepoint；单行失败标记 `invalid` 并继续，不中断整批。

## 4. 文件格式与解析

### CSV

- 编码：默认 UTF-8（含 BOM），支持 `utf-8-sig`、`gb18030`；检测失败返回 `IMPORT_ENCODING_UNSUPPORTED`。
- 分隔符：逗号、分号、Tab 自动探测，可显式指定。
- 必须有表头行；空行忽略；列数不一致的行判为 `ROW_SHAPE_INVALID`。
- 字段内换行、引号转义按 RFC 4180 处理。
- 金额按字符串解析为 `Decimal`，禁止经过 float。

### Excel

- 首版只支持 `.xlsx`（`openpyxl`，`read_only=True`、`data_only=True`）。
- 不支持 `.xls`、`.xlsm`、宏、外部链接、隐藏工作表自动导入。
- 公式单元格只读取缓存值；无缓存值判为无效。
- 默认读取第一个工作表，允许映射时指定 `sheet_name`。

### 限制与安全

| 项 | 默认值 | 配置 |
| -- | -- | -- |
| 单文件大小 | 10 MB | `IMPORT_MAX_FILE_MB` |
| 单批次行数 | 20,000 | `IMPORT_MAX_ROWS` |
| 表头列数 | 100 | 固定 |
| 预览样本行 | 50 | 固定 |
| 原始文件保留 | 30 天 | `IMPORT_FILE_RETENTION_DAYS` |
| 批次行数据保留 | 180 天 | `IMPORT_ROW_RETENTION_DAYS` |

- 校验扩展名 + MIME + 文件头（magic bytes）；`.xlsx` 额外限制解压后大小，防 zip bomb。
- 文件名不参与路径拼接，存储名使用 `batch_id + 随机后缀`。
- CSV 导出/预览转义以 `= + - @` 开头的单元格，防公式注入。
- 文件只存私有卷，不提供静态直链；下载走鉴权端点（2A 增加鉴权后）。
- 日志不记录完整描述/对手方信息，只记录 `batch_id`、行号、错误码。

## 5. 字段映射与规范化

### 标准字段

| 字段 | 必填 | 说明 |
| -- | -- | -- |
| `transaction_date` | 是 | 日期或日期时间；无时区按家庭时区 |
| `amount` | 是 | 字符串/数值；方向归一后必须 > 0 |
| `direction` | 条件 | `type_column` 模式下必填 |
| `currency` | 否 | 默认账户币种 |
| `category` | 否 | 名称/路径或 UUID；未匹配归「未分类」或默认分类 |
| `description` | 否 | 最长 2000 |
| `external_id` | 否 | 最长 255，用于去重 |
| `exchange_rate` | 否 | 非本位币且无汇率列时该行无效 |

### 账户解析

- 首版一个批次绑定一个默认账户（`account_id`）。
- 可选映射 `account` 列 + `account_map`（别名 → 账户 UUID），支持银行导出多账户文件。
- 映射到的账户必须属于当前 household 且处于激活状态，否则整批拒绝 `IMPORT_ACCOUNT_INVALID` 或单行 `ACCOUNT_INACTIVE`。

### 分类解析

- 支持分类 UUID、完整路径（`支出/餐饮`）、唯一名称。
- 同名/歧义 → `CATEGORY_AMBIGUOUS`，要求用户在映射中显式指定。
- 未提供/未匹配：使用 `default_category_id`；仍为空则 `category_id = NULL`（统计归入「未分类」）。
- 分类类型必须与归一后的交易类型一致，否则 `CATEGORY_TYPE_MISMATCH`。

### 金额与方向

1. 解析为 `Decimal`，按币种 `decimal_places` 校验精度；超出精度默认判无效，不做静默四舍五入。
2. 按 `amount_mode` + `direction_map` 归一为 `income` / `expense`。
3. 归一后金额必须 > 0；零或负数（方向模式冲突）判 `AMOUNT_INVALID`。
4. 币种等于家庭本位币时汇率固定 1；否则必须有映射汇率或同币种账户默认汇率
   （2B 首版只支持文件内汇率列，缺失则行无效）。

### 日期

- 支持 `date_formats` 列表，默认 ISO 8601 + `YYYY/MM/DD` + `YYYY-MM-DD HH:MM:SS`。
- 纯日期按家庭时区当天 `00:00:00`；带偏移的时间保留偏移并转换为 UTC 存储。
- 无法解析 → `DATE_INVALID`；未来日期默认允许（银行预授权场景），可在预览中提示。

## 6. 去重设计

### 文件级

- 计算文件 SHA-256。
- 同 household 下存在相同哈希且状态为 `completed` / `partial` 的批次 → 409
  `IMPORT_FILE_DUPLICATE`；用户可显式 `allow_duplicate_file=true` 重传。

### 行级

按优先级依次判断：

1. **外部流水号**：`external_id` 在 `finance.transactions` 中同账户已存在 → 重复。
2. **精确指纹**：`sha256(account_id | type | amount | currency | transaction_date(UTC, 秒) | normalized_description)`。
3. **批内重复**：同一批次内指纹相同，保留 `row_number` 最小的一行，其余标 `duplicate`。
4. **模糊匹配（可选，默认关闭）**：同账户、同类型、同币种、金额相同、日期相差 ≤ 1 天；
   仅标记提示，不自动跳过。

规则：

- 去重范围限定当前 household，绝不跨家庭。
- `opening_balance` 与转账衍生流水不参与去重匹配。
- 用户可在预览中把 `duplicate` 行改为 `valid`（覆盖跳过）。
- 不新增 `finance.transactions` 唯一约束；去重在 Service/Worker 层完成，避免历史数据迁移风险。
- 大批量执行时按批次日期范围预加载候选交易到内存集合，避免逐行全表扫描。

## 7. 校验规则

逐行收集全部错误，不 fail-fast，便于一次性修正。

| 错误码 | 场景 |
| -- | -- |
| `DATE_INVALID` | 日期无法解析 |
| `AMOUNT_INVALID` | 金额非法、为 0、方向冲突 |
| `AMOUNT_PRECISION` | 超出币种小数位 |
| `CURRENCY_INVALID` | 未知/停用币种 |
| `EXCHANGE_RATE_REQUIRED` | 非本位币缺少汇率 |
| `ACCOUNT_INACTIVE` | 账户停用 |
| `ACCOUNT_NOT_FOUND` | 账户不属于当前家庭 |
| `CATEGORY_NOT_FOUND` | 分类不存在 |
| `CATEGORY_AMBIGUOUS` | 名称匹配到多个分类 |
| `CATEGORY_TYPE_MISMATCH` | 分类类型与收支方向不一致 |
| `DESCRIPTION_TOO_LONG` | 超过 2000 字符 |
| `EXTERNAL_ID_TOO_LONG` | 超过 255 字符 |
| `ROW_SHAPE_INVALID` | 列数与表头不一致 |
| `INSUFFICIENT_BALANCE` | 执行时确认态支出导致负余额 |
| `DUPLICATE_ROW` | 判定重复（预览状态，不阻断确认） |

## 8. 数据模型（建议，未建表）

放置于 `system` schema，保持现有三 schema 结构；若评审倾向独立
`ingestion` schema，可在 2B 迁移时调整。

### `system.import_batches`

| 列 | 类型 | 说明 |
| -- | -- | -- |
| `id` | UUID PK | |
| `household_id` | UUID FK `core.households` | 作用域 |
| `account_id` | UUID FK `core.accounts` NULL | 默认目标账户 |
| `status` | VARCHAR(20) | 状态机 + CHECK |
| `source_format` | VARCHAR(10) | `csv` / `xlsx` |
| `original_filename` | VARCHAR(255) | 仅展示 |
| `stored_path` | TEXT | 私有卷相对路径 |
| `file_sha256` | CHAR(64) | 文件级去重 |
| `file_size_bytes` | BIGINT | |
| `mapping` | JSONB | 字段映射与参数 |
| `mapping_version` | INTEGER | 默认 0 |
| `total_rows` / `valid_rows` / `invalid_rows` / `duplicate_rows` / `imported_rows` | INTEGER | 计数缓存 |
| `error_code` / `error_message` | VARCHAR / TEXT | 批次级错误 |
| `idempotency_key` | VARCHAR(100) NULL | 上传幂等键 |
| `correlation_id` | UUID | NATS/Worker 追踪 |
| `created_at` / `updated_at` / `confirmed_at` / `completed_at` / `expires_at` | TIMESTAMPTZ | |

索引：`(household_id, created_at DESC)`、`(status)`、`(household_id, file_sha256)`。

### `system.import_rows`

| 列 | 类型 | 说明 |
| -- | -- | -- |
| `id` | UUID PK | |
| `batch_id` | UUID FK `import_batches` ON DELETE CASCADE | |
| `row_number` | INTEGER | 文件内序号，从 1 开始 |
| `raw_data` | JSONB | 原始单元格 |
| `normalized_data` | JSONB | 规范化后的交易字段 |
| `row_hash` | CHAR(64) | 行指纹 |
| `status` | VARCHAR(20) | 行状态 + CHECK |
| `errors` | JSONB | 错误数组 |
| `transaction_id` | UUID FK `finance.transactions` NULL | 成功导入后的流水 |
| `duplicate_of_transaction_id` | UUID FK `finance.transactions` NULL | 命中的已有流水 |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

约束/索引：

- `UNIQUE (batch_id, row_number)`
- `(batch_id, status)`
- `(batch_id, row_hash)`
- `(transaction_id)`

### 审计动作

- `import.create`：上传成功
- `import.mapping`：映射保存
- `import.preview`：预览完成（含计数）
- `import.confirm`：人工确认
- `import.execute`：Worker 完成/部分完成
- `import.cancel` / `import.delete`

`before_data` / `after_data` 只存批次状态与计数，不重复存整行原始数据。

## 9. 异步处理（第二阶段 2B）

### 组件

```text
API ──写批次+outbox──> PostgreSQL
 │                        │
 │                        └── Outbox Publisher ──> NATS JetStream
 │                                                   │
 └── 查询状态 <── Import Worker <────────────────────┘
                     ├── 解析文件（CSV/XLSX）
                     ├── 校验/去重
                     └── 生成 finance.transactions（source=import）
```

- 新增 `nats` 与 `import-worker` 容器；文件通过 `import_data` named volume 共享。
- API 只做上传、映射、状态查询；重解析与批量写入在 Worker。
- 小文件（≤ 2,000 行）可在 API 内同步预览，避免为一次预览启动完整链路；
  执行阶段仍走 Worker。
- 上传后立即返回 `uploaded`；映射保存后调用 `preview` 投递 NATS。

### Outbox 与幂等

- `system.outbox_events`（2B 新增）：`id`、`aggregate_type`、`aggregate_id`、
  `event_type`、`payload`、`published_at`、`attempts`。
- API 在批次状态变更的同一事务写 outbox；Publisher 轮询未发布事件并投递。
- JetStream 持久化 stream `IMPORT`，subject 建议：
  - `import.preview`
  - `import.execute`
- Worker 使用 durable consumer；处理成功后 ack；失败 `nak` 重试，最多 5 次，
  超过进入 `IMPORT_DLQ` 并标记批次 `failed`。
- 执行前用 `UPDATE import_batches SET status='processing' WHERE id=:id AND status='confirmed'`
  抢占；重复消息直接 ack，保证幂等。

### 执行事务与顺序

- 按 `row_number` 顺序处理，保证同一账户余额校验与文件顺序一致。
- 每 200 行一个事务块；块内每行使用 savepoint，单行失败只标记该行，不中断整批。
- 负余额校验读取当前账面余额 + 本块已成功行；`create_status=draft` 时跳过负余额校验。
- 每行生成交易后回写 `transaction_id`；块提交后再更新批次计数。
- Worker 崩溃后从最后未处理的 `valid/pending` 行继续，已 `imported` 行不重复写入。

## 10. 错误码与 HTTP 行为

| 场景 | HTTP | error_code |
| -- | -- | -- |
| 文件过大/行数超限 | 413 / 400 | `IMPORT_FILE_TOO_LARGE` / `IMPORT_TOO_MANY_ROWS` |
| 文件类型不支持 | 415 | `IMPORT_FILE_TYPE_UNSUPPORTED` |
| 编码无法识别 | 400 | `IMPORT_ENCODING_UNSUPPORTED` |
| 表头缺失/为空 | 400 | `IMPORT_HEADER_INVALID` |
| 相同文件已导入 | 409 | `IMPORT_FILE_DUPLICATE` |
| 批次状态不允许当前操作 | 409 | `IMPORT_STATE_INVALID` |
| 批次不存在/跨家庭 | 404 | `IMPORT_NOT_FOUND` |
| 映射字段缺失/非法 | 400 | `IMPORT_MAPPING_INVALID` |
| 账户/分类不属于家庭 | 400/404 | `IMPORT_ACCOUNT_INVALID` / `IMPORT_CATEGORY_INVALID` |
| 重复确认 | 200（幂等） | — |

## 11. 测试计划

- **解析器**：UTF-8 BOM、GB18030、分号/Tab、引号换行、空行、列数不一致、
  超大文件、zip bomb、公式单元格。
- **映射**：四种金额方向模式、日期格式、币种/汇率、分类路径与歧义。
- **去重**：external_id、精确指纹、批内重复、跨家庭不误判、模糊匹配开关。
- **状态机**：上传→映射→预览→确认→执行→完成/部分/失败/取消/过期；
  重复确认与重复回调幂等。
- **执行**：余额校验、draft/confirmed 两种创建模式、单行失败不污染整批、
  Worker 崩溃续跑。
- **隔离**：`X-Household-Id` 缺失/多家庭/跨家庭访问。
- **审计**：每个动作都有记录，且不含完整原始数据。
- **性能**：10,000 行 CSV 预览与执行在可接受时间内完成（目标 < 60s，本地环境）。

## 12. 实施拆分（2B）

1. **2B-1 同步骨架** ✅ 已完成（Task 007）
   - 迁移：`import_batches`、`import_rows`（`outbox_events` 延后到 2B-2）
   - API：上传、映射、同步预览、同步确认、列表/详情/行查询/行修正/取消/删除
   - CSV 解析、映射、校验、去重、生成交易
   - 测试与文档
2. **2B-2 异步化**
   - NATS JetStream、Outbox Publisher、Import Worker
   - 预览/执行投递、重试、DLQ、进度查询
   - Compose 增加 `nats`、`import-worker`、`import_data` volume
3. **2B-3 增强**
   - Excel `.xlsx`
   - 模糊去重、批量修正、模板下载
   - 与 2A 前端导入页联调

## 13. 待评审决策

| # | 问题 | 建议 |
| -- | -- | -- |
| 1 | 导入交易默认 `confirmed` 还是 `draft`？ | 默认 `confirmed`，提供 `create_status=draft` 选项；预览阶段提示负余额风险 |
| 2 | 一个批次一个账户，还是支持账户列映射？ | 默认一个账户，同时允许可选的 `account_map` |
| 3 | 导入表放 `system` 还是新 `ingestion` schema？ | 首版放 `system`，减少 schema 扩张 |
| 4 | 是否支持 GB18030？ | 支持，国内银行/支付宝导出常见 |
| 5 | 模糊去重是否默认开启？ | 默认关闭，只做精确匹配 + 外部流水号 |
| 6 | 原始文件与行数据保留多久？ | 文件 30 天、行数据 180 天，可配置 |
| 7 | 是否支持 `.xls`？ | 不支持，首版只支持 `.xlsx` |
| 8 | 是否需要批量确认 draft 交易？ | 2B 视前端需求再定，避免导入后大量草稿无法一键转正式 |
| 9 | 导入是否允许负数金额表达方向？ | 允许，但归一后金额必须 > 0；方向模式必须明确 |
| 10 | 单批最大行数？ | 20,000，超过建议拆分文件 |

## 14. 验收标准（设计评审）

- 接口、状态机、数据模型、去重与校验规则经确认。
- 与现有交易/余额/统计/审计规则无冲突。
- 明确 2B 实施拆分与测试范围。
- 本阶段不产生代码、迁移或容器变更。

## 15. 2B-1 实施记录（2026-11-11）

### 已落地

- 迁移 `0003_phase_2b_1`：`system.import_batches` / `system.import_rows`；
  文件二进制不入库。未创建 `outbox_events`、`idempotency_key`、`correlation_id`。
- 端点：`POST/GET /imports`、`GET/DELETE /imports/{id}`、
  `PUT /imports/{id}/mapping`、`POST /imports/{id}/preview`、
  `GET /imports/{id}/rows`、`PUT /imports/{id}/rows/{row_id}`、
  `POST /imports/{id}/confirm`、`POST /imports/{id}/cancel`。
- CSV：`utf-8-sig` → `gb18030` 回退；分隔符自动探测 `, ; tab |`；
  上传时解析表头与前 10 行样例，预览时重新解析整个文件。
- 映射保存即校验必填字段与源列存在；预览再次校验。
- 行状态机：`pending → valid/invalid/duplicate`，确认后 `imported/skipped`；
  手工修正可改 `normalized_data` 并置 `valid`，或置 `skipped`。
- 批次状态机：`uploaded → mapped → previewed → (completed|partial|failed)`；
  `cancelled` 可从可编辑态进入；`processing/confirmed/expired` 为 2B-2 预留。
- 去重：外部流水号 → 精确指纹 → 批内重复；排除开账与转账衍生流水；
  模糊匹配默认关闭且未实现。
- 执行：逐行 savepoint；确认态支出做负余额校验；`create_status=draft` 跳过；
  `on_duplicate=skip` 将重复行置 `skipped`；仅当 `imported == total_rows` 时
  `completed`，否则部分成功 `partial` 或 `failed`。
- 审计：`import.create/mapping/preview/confirm/execute/row_update/cancel/delete`。
- 配置：`IMPORT_STORAGE_DIR`（默认 `/tmp/homeatlas-imports`）、
  `IMPORT_MAX_FILE_MB=10`、`IMPORT_MAX_ROWS=20000`；依赖 `python-multipart`。

### 与设计稿的差异

- 预览/确认均为同步 `200`，不会出现持久化的 `confirmed`/`processing` 中间态。
- 预览会删除并重建 `import_rows`：手工修正后再次预览会丢失修正。
- 未实现上传幂等键、模板下载、Excel、模糊去重、保留期清理任务。
- 文件存放在 API 进程本地目录；容器重建或换实例后需重新上传（2B-2 共享卷解决）。
- 确认只处理 `income`/`expense`，不导入转账与 `opening_balance`。

### 验证

- `apps/api/tests/test_imports.py`：9 项集成测试，覆盖上传/映射/预览/确认、
  四种金额模式、外币与本位币、文件级与行级去重、负余额与 draft、账户/分类解析、
  状态机、文件限制、跨家庭隔离、审计与 OpenAPI。
- 全量 99 项通过，覆盖率 97.46%；`ruff check` / `ruff format --check` /
  `mypy app` 通过。
