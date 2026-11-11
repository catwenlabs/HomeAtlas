# HomeAtlas

自托管的家庭数据中心。第一阶段：家庭收支管理后端 API（Python 3.12 + FastAPI + PostgreSQL 17 + SQLAlchemy 2.x async + Alembic），模块化单体，Docker Compose 部署。

> 规格说明书：[Specification v1.3（issue #1 评论）](https://github.com/catwenlabs/HomeAtlas/issues/1#issuecomment-6788969821)，本地镜像 `docs/specification.md`。

当前进度：**Phase 1.0–1.4、Phase 2E（转账与多币种）与 Phase 2B-1（数据导入同步骨架）完成；Phase 1.5 数据导入设计评审完成**。已实现家庭、账户、币种、分类、初始余额、账户余额查询，收入/支出的创建、确认、修改、删除、冲正、筛选与审计，同币种/跨币种/同账户换汇转账、手续费衍生支出与冲正，收入/支出、分类、月度/年度、资金流向、总览与账户余额统计，以及 CSV 上传 → 字段映射 → 同步预览/去重 → 人工确认 → 生成 `income`/`expense` 流水的导入闭环。Excel、模糊去重、NATS/Worker 异步化留到 2B-2/2B-3。

## 快速开始

```bash
cd deploy
cp .env.example .env          # 编辑 POSTGRES_PASSWORD
docker compose up -d          # 启动 postgres + api
docker compose run --rm api alembic upgrade head   # 执行迁移（独立命令，不在启动时自动跑）
curl http://127.0.0.1:8000/health   # {"status":"ok"}
curl http://127.0.0.1:8000/ready    # {"status":"ok","database":"ok"}
```

Swagger UI：<http://127.0.0.1:8000/docs>

## 已实现 API

统一前缀 `/api/v1`，成功/失败均使用统一 envelope（§6.8）。

| 模块 | 端点 |
| -- | -- |
| Households | `GET/POST /api/v1/households`、`GET/PUT /api/v1/households/{id}` |
| Accounts | `GET/POST /api/v1/accounts`、`GET/PUT/DELETE /api/v1/accounts/{id}` |
| 初始余额 | `PUT /api/v1/accounts/{id}/opening-balance` |
| 余额/流水 | `GET /api/v1/accounts/{id}/balances`、`/transactions`、`/balance-history` |
| Currencies | `GET /api/v1/currencies`、`GET /api/v1/currencies/{code}` |
| Categories | `GET/POST /api/v1/categories`、`GET/PUT/DELETE /api/v1/categories/{id}` |
| Transactions | `GET/POST /api/v1/transactions`、`GET/PUT/DELETE /api/v1/transactions/{id}`、`POST /api/v1/transactions/{id}/reverse` |
| Transfers | `GET/POST /api/v1/transfers`、`GET/PUT/DELETE /api/v1/transfers/{id}`、`POST /api/v1/transfers/{id}/reverse` |
| Imports | `POST/GET /api/v1/imports`、`GET/DELETE /api/v1/imports/{id}`、`PUT /api/v1/imports/{id}/mapping`、`POST /api/v1/imports/{id}/preview`、`GET /api/v1/imports/{id}/rows`、`PUT /api/v1/imports/{id}/rows/{row_id}`、`POST /api/v1/imports/{id}/confirm`、`POST /api/v1/imports/{id}/cancel` |
| Statistics | `GET /api/v1/statistics/income-expense`、`/category`、`/monthly`、`/cashflow`、`/overview`、`/account-balances` |
| 探针 | `GET /health`、`GET /ready`（不走 envelope） |

业务端点支持可选 Header `X-Household-Id`：只有一个家庭时自动兜底，多个家庭时必须显式指定（否则 400 `HOUSEHOLD_REQUIRED`）。

### 示例

```bash
# 创建家庭（会自动生成默认分类树）
curl -s -X POST http://127.0.0.1:8000/api/v1/households \
  -H 'Content-Type: application/json' \
  -d '{"name":"我的家","base_currency":"CNY"}'

# 创建账户
curl -s -X POST http://127.0.0.1:8000/api/v1/accounts \
  -H 'Content-Type: application/json' \
  -H "X-Household-Id: <household-id>" \
  -d '{"name":"中国银行","account_type":"bank","currency":"CNY"}'

# 设置初始余额（同一账户+币种重复 PUT 即修改，并留审计）
curl -s -X PUT http://127.0.0.1:8000/api/v1/accounts/<account-id>/opening-balance \
  -H 'Content-Type: application/json' \
  -H "X-Household-Id: <household-id>" \
  -d '{"amount":"1000.00","description":"开账"}'

# 多币种开账：非本位币必须提供汇率
curl -s -X PUT http://127.0.0.1:8000/api/v1/accounts/<account-id>/opening-balance \
  -H 'Content-Type: application/json' \
  -H "X-Household-Id: <household-id>" \
  -d '{"amount":"100.00","currency":"USD","exchange_rate":"7.10"}'

# 记一笔支出（默认 draft；传 "status":"confirmed" 可直接确认）
curl -s -X POST http://127.0.0.1:8000/api/v1/transactions \
  -H 'Content-Type: application/json' \
  -H "X-Household-Id: <household-id>" \
  -d '{"account_id":"<account-id>","category_id":"<expense-category-id>","transaction_type":"expense","amount":"35.50","description":"午餐"}'

# 确认 draft
curl -s -X PUT http://127.0.0.1:8000/api/v1/transactions/<transaction-id> \
  -H 'Content-Type: application/json' \
  -H "X-Household-Id: <household-id>" \
  -d '{"status":"confirmed"}'

# 冲正已确认流水（原记录置 reversed，并生成关联反向流水）
curl -s -X POST http://127.0.0.1:8000/api/v1/transactions/<transaction-id>/reverse \
  -H 'X-Household-Id: <household-id>'

# CSV 导入：上传 → 映射 → 预览 → 确认（2B-1 同步执行）
curl -s -X POST http://127.0.0.1:8000/api/v1/imports \
  -H "X-Household-Id: <household-id>" \
  -F 'file=@alipay-2026-06.csv' \
  -F 'source_format=csv' \
  -F 'account_id=<account-id>'

curl -s -X PUT http://127.0.0.1:8000/api/v1/imports/<batch-id>/mapping \
  -H 'Content-Type: application/json' \
  -H "X-Household-Id: <household-id>" \
  -d '{"columns":{"transaction_date":"交易日期","amount":"金额","description":"备注"},"amount_mode":"signed_positive_income"}'

curl -s -X POST http://127.0.0.1:8000/api/v1/imports/<batch-id>/preview \
  -H "X-Household-Id: <household-id>"

curl -s -X POST http://127.0.0.1:8000/api/v1/imports/<batch-id>/confirm \
  -H 'Content-Type: application/json' \
  -H "X-Household-Id: <household-id>" \
  -d '{"on_duplicate":"skip","create_status":"confirmed"}'
```

金额以字符串返回（Decimal，避免浮点误差）；写入时按币种 `decimal_places` 使用 half-even 取整。
普通收支必须为正数，`opening_balance` 只能通过初始余额端点写入。Phase 1 会拒绝导致账户该币种负余额的支出/冲正。

CSV 导入默认限制单文件 10 MB、单批次 20,000 行（`IMPORT_MAX_FILE_MB` / `IMPORT_MAX_ROWS`）；
文件落 `IMPORT_STORAGE_DIR`（默认 `/tmp/homeatlas-imports`），数据库只存路径与 SHA-256。
预览会重建批次行数据，因此手工修正应在完成预览后进行；再次预览会丢失修正。

## 开发

```bash
# 测试（需要 deploy/docker-compose.yml 的 postgres 在运行）
cd apps/api && pytest
# 或在容器内：
cd deploy && docker compose run --rm api pytest

# Lint / 格式 / 类型检查
cd apps/api
ruff check . && ruff format --check .
mypy app
```

CI（GitHub Actions）：push / PR 触发 ruff + mypy + pytest（覆盖率 ≥ 80% 强制）。

## 目录结构

```
home-atlas/
├── apps/api/          # FastAPI 应用（app/core 基础设施、app/modules 业务模块）
├── deploy/            # docker-compose.yml + .env.example
├── docs/              # architecture / database / development-roadmap / import-design / specification
└── .github/workflows/ # CI
```

## 文档

- [architecture.md](docs/architecture.md) — 架构、已实现 API 与请求流
- [database.md](docs/database.md) — schema、约束、迁移与测试策略
- [development-roadmap.md](docs/development-roadmap.md) — 阶段计划与当前进度
- [import-design.md](docs/import-design.md) — 数据导入设计与 2B-1 同步骨架实施记录
