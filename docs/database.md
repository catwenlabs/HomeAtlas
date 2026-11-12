# Database

PostgreSQL 17 是唯一业务事实来源。所有结构变更走 Alembic——禁止手工改库。

## Schema 划分

| schema | 表 |
| -- | -- |
| core | households / accounts / currencies / account_balances |
| finance | categories / transactions / transfers |
| system | audit_logs / import_batches / import_rows |

- 基线迁移 `0001_initial` 创建三个 schema。
- `0002_phase_1_1` 创建全部 8 张业务表，包含规格 §4 的 CHECK 约束、索引、
  状态机字段、冲正/衍生关联字段。
- `0003_phase_2b_1` 创建导入表 `system.import_batches` / `system.import_rows`
  （Phase 2B-1 同步骨架，2B-3 复用同一结构支持 CSV/XLSX）；文件二进制不入库，
  只存路径、大小与 SHA-256，存储文件后缀随 `source_format` 为 `.csv` 或 `.xlsx`。
- 同一次迁移写入 seed：6 个币种（CNY/USD/HKD/EUR/GBP/JPY）、默认家庭
  （`默认家庭`，base CNY，Asia/Shanghai）、11 个默认分类（含系统内置
  `金融手续费`）。
- 新建家庭时服务层会克隆默认分类树，保证每个家庭都有可用分类。

## 关键约束

- `finance.transactions.amount > 0`，仅 `opening_balance` 豁免（允许负数）。
- 交易/转账状态：`draft → confirmed → reversed`；仅 draft 可修改/物理删除，
  confirmed 只能冲正，reversed 为终态。
- 冲正生成关联反向流水（`reverses_transaction_id`），原记录置 `reversed`，
  两行在同一事务内写入；余额聚合包含 `confirmed` 与 `reversed` 两态以互相抵消。
- 交易生命周期写入 `system.audit_logs`：`transaction.create/update/confirm/delete/reverse`。
- 分类：`parent_id <> id`；同一 household、父子类型一致、最多两级由 Service 校验。
- 转账：`from_account_id <> to_account_id OR from_currency <> to_currency`；
  `fee >= 0`。`base_amount` / `base_currency` 固化转账的本位币价值；
  `base_exchange_rate` / `fee_exchange_rate` 仅为请求字段，不落库。
- 转账确认时，若 `fee > 0`，同一事务生成 `金融手续费` 支出流水：
  `transfer_id` 关联、`source=system`、`status=confirmed`、携带 `base_amount`；
  草稿阶段不生成。冲正转账时同事务冲正该手续费流水并生成反向收入。
- 转账生命周期写入 `system.audit_logs`：`transfer.create/update/confirm/delete/reverse`；
  衍生手续费流水另写 `transaction.create/reverse`。
- `account_balances` 唯一键 `(account_id, currency, snapshot_at, source)`。
- 金额 `NUMERIC(24,8)`，汇率 `NUMERIC(24,12)`，时间 `TIMESTAMPTZ`。
- Phase 2E 未新增迁移，复用 `0002_phase_1_1` 已建好的 `finance.transfers`。
- 导入批次：`status IN ('uploaded','mapped','previewed','confirmed','processing',
  'completed','partial','failed','cancelled','expired')`，`source_format IN ('csv','xlsx')`；
  索引 `(household_id, created_at)`、`status`、`(household_id, file_sha256)`。
- 导入行：`UNIQUE (batch_id, row_number)`，`status IN ('pending','valid','invalid',
  'duplicate','imported','skipped')`；`transaction_id` /
  `duplicate_of_transaction_id` 指向 `finance.transactions`，删除交易时置 NULL；
  删除批次时行级联删除。
- 导入文件级去重按 `(household_id, file_sha256)` 查询已完成/部分完成批次；
  行级去重不建唯一约束，在 Service 层按外部流水号、精确指纹与可选模糊匹配判断。

## 迁移命令

迁移是独立命令，不在容器启动时自动执行：

```bash
cd deploy
docker compose run --rm api alembic upgrade head
# 回滚一个版本：
docker compose run --rm api alembic downgrade -1
```

连接串由应用配置组装（`POSTGRES_*` 环境变量，经 `app/core/config.py`），alembic 与应用永远指向同一数据库。

## 测试数据库策略

- 集成测试使用真实 PostgreSQL 的独立库 `home_atlas_test`（`tests/conftest.py` 每次会话先 DROP/CREATE，再跑 `alembic upgrade head`——与生产同一套迁移）。
- 每个业务用例通过 `clean_db` fixture TRUNCATE 全部业务表（保留币种 seed）；
  家庭等数据由用例自行创建。`system.import_rows` / `system.import_batches`
  一并清理。
- 覆盖率配置 `concurrency = ["greenlet", "thread"]`，确保 SQLAlchemy async
  greenlet 切换后的代码仍被统计。

## 约定

- 金额 NUMERIC，时间 TIMESTAMPTZ（规格 §1）。
- 约束命名遵循 `app/core/db.py` 的 naming_convention。
- 持久化：compose named volume `postgres_data`；不发布端口（backend internal 网络）。
