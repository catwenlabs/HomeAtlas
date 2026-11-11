# Development Roadmap

完整规格见 [specification.md](specification.md) §8–§11。当前进度：

| Phase | 内容 | 状态 |
| -- | -- | -- |
| 1.0 Task 001 | 基础设施：FastAPI + SQLAlchemy + Alembic + Compose + CI + 探针 | ✅ 完成 |
| 1.1 | 基础数据模型：households/accounts/currencies/categories/balances + seed + opening_balance | ⬜ 下一任务（Task 002） |
| 1.2 | 收支管理 API：状态机、冲正、审计 | ⬜ |
| 1.3 | 转账与多币种：跨币种、手续费衍生支出、余额核对 | ⬜ |
| 1.4 | 统计 API：本位币聚合、家庭时区分组 | ⬜ |
| 1.5 | 数据导入预留（设计评审） | ⬜ |
| 2A/2B/2C/2D | Web 前端 / 异步导入 / 投资与资产 / Grafana | ⬜ 第一阶段稳定后 |

## Task 002（Phase 1.1）预告

- 按 §4 建 8 张表（全部约束/索引/状态机字段）。
- Alembic data migration：币种 seed（CNY/USD/HKD/EUR/GBP/JPY）、默认分类树 + 金融手续费。
- opening_balance 开账流水 + household 作用域依赖（X-Household-Id，§6.0）。

## 验收复查（Task 001）

- docker compose up -d 正常；/health、/ready 宿主机可达
- docker compose run --rm api alembic upgrade head 正常
- pytest 通过（覆盖率 ≥ 80%）；CI 全绿
- postgres 重启后数据仍在（named volume）
