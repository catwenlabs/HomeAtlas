# Database

PostgreSQL 17 是唯一业务事实来源。所有结构变更走 Alembic——禁止手工改库。

## Schema 划分

| schema | 内容 |
| -- | -- |
| core | households / accounts / currencies / account_balances |
| finance | categories / transactions / transfers |
| system | audit_logs |

基线迁移 `0001_initial` 创建上述三个 schema。业务表自 Phase 1.1 起按规格 §4 建表（含 CHECK 约束、索引、状态机字段、冲正/衍生关联字段）；币种与分类 seed 通过 Alembic data migration 写入。

## 迁移命令

迁移是独立命令，不在容器启动时自动执行：

```bash
cd deploy
docker compose run --rm api alembic upgrade head
```

连接串由应用配置组装（`POSTGRES_*` 环境变量，经 `app/core/config.py`），alembic 与应用永远指向同一数据库。

## 测试数据库策略

- 集成测试使用真实 PostgreSQL 的独立库 `home_atlas_test`（`tests/conftest.py` 每次会话先 DROP/CREATE，再跑 `alembic upgrade head`——与生产同一套迁移）。
- Phase 1.1 起为每个用例提供事务回滚/truncate 隔离（规格 §9.0）。

## 约定

- 金额 NUMERIC，时间 TIMESTAMPTZ（规格 §1）。
- 约束命名遵循 `app/core/db.py` 的 naming_convention。
- 持久化：compose named volume `postgres_data`；不发布端口（backend internal 网络）。
