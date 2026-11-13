# HomeAtlas

自托管的家庭数据中心。第一阶段：家庭收支管理后端 API（Python 3.12 + FastAPI + PostgreSQL 17 + SQLAlchemy 2.x async + Alembic），模块化单体，Docker Compose 部署。

> 规格说明书：[Specification v1.3（issue #1 评论）](https://github.com/catwenlabs/HomeAtlas/issues/1#issuecomment-6788969821)，本地镜像 `docs/specification.md`。

当前进度：**Phase 1.0–1.4、Phase 2E（转账与多币种）、Phase 2B-1 与 2B-3（数据导入）、Phase 2A（认证与 Web 前端）完成；Phase 1.5 数据导入设计评审完成**。已实现家庭、账户、币种、分类、初始余额、账户余额查询，收入/支出的创建、确认、修改、删除、冲正、筛选与审计，同币种/跨币种/同账户换汇转账、手续费衍生支出与冲正，收入/支出、分类、月度/年度、资金流向、总览与账户余额统计，以及 CSV/XLSX 上传 → 字段映射 → 同步预览/去重（精确 + 可选模糊）→ 人工确认 → 生成 `income`/`expense` 流水的导入闭环，支持模板下载与批量行修正。Phase 2A 增加 JWT 认证、首次部署初始化向导与 React Web 前端。NATS/Worker 异步化（2B-2）已决定暂缓。

## 快速开始

```bash
cd deploy
cp .env.example .env          # 编辑 POSTGRES_PASSWORD 与 JWT_SECRET_KEY
docker compose up -d          # 启动 postgres + api + web
docker compose run --rm api alembic upgrade head   # 执行迁移（独立命令，不在启动时自动跑）
curl http://127.0.0.1:8000/health   # {"status":"ok"}
curl http://127.0.0.1:8000/ready    # {"status":"ok","database":"ok"}
```

打开 <http://127.0.0.1:8080> 进入首次部署向导：创建管理员账户、确认家庭信息、
勾选需要写入的币种与分类。**迁移不会写入任何用户基础数据**；内置币种与分类只作为
向导预填项，只有用户确认后才会落库。

Swagger UI：<http://127.0.0.1:8000/docs>（业务接口需要 Bearer token）。

## 已实现 API

统一前缀 `/api/v1`，成功/失败均使用统一 envelope（§6.8）。除 `setup/*` 与 `auth/login` 外，
所有业务接口都要求 `Authorization: Bearer <token>`；家庭作用域由 JWT 中的 `household_id` 派生。

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

### 首次初始化与登录

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
`BASE_CURRENCY_NOT_SELECTED`；因此币种至少要选择一个。
初始化只能执行一次，重复调用返回 409 `SETUP_ALREADY_COMPLETED`。

### 示例

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

# CSV 导入：上传 → 映射 → 预览 → 确认（2B-1 同步执行）
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

金额以字符串返回（Decimal，避免浮点误差）；写入时按币种 `decimal_places` 使用 half-even 取整。
普通收支必须为正数，`opening_balance` 只能通过初始余额端点写入。Phase 1 会拒绝导致账户该币种负余额的支出/冲正。

CSV 导入默认限制单文件 10 MB、单批次 20,000 行（`IMPORT_MAX_FILE_MB` / `IMPORT_MAX_ROWS`）；
文件落 `IMPORT_STORAGE_DIR`（默认 `/tmp/homeatlas-imports`），数据库只存路径与 SHA-256。
预览会重建批次行数据，因此手工修正应在完成预览后进行；再次预览会丢失修正。

## 开发

本地开发通过根目录 Makefile 驱动（参考 pulse 项目的模式）。`deploy/compose.dev.yaml`
为 postgres 叠加发布开发端口 `127.0.0.1:54321`（生产 compose 的 `backend` 网络是
internal-only，主机不可直达），API 与前端跑在本机：

```bash
make dev          # 一键本地环境：dev postgres + uvicorn --reload + Vite dev server
make test         # API 测试套件（自动起 dev postgres、建 venv、跑 pytest + 覆盖率）
make lint         # ruff check + format --check
make typecheck    # mypy strict
make web-build    # tsc --noEmit + vite build

make dev-db-up    # 单独启动带开发端口 overlay 的 postgres
make dev-db-down  # 停掉并移除 dev postgres 容器（数据卷保留）
make dev-migrate  # 对开发库执行 alembic upgrade head
```

首次 `make dev` 会自动创建 `apps/api/.venv`（优先 uv，回退 python3 -m venv）、
安装依赖、跑迁移，并按需安装 `apps/web/node_modules`。API 在
`http://127.0.0.1:8000`（文档 `/docs`），前端在 `http://localhost:5173`（`/api`
代理到本机 API）。

等价的单步命令（不依赖 Makefile）：

```bash
cd apps/api && pytest          # 需 postgres 可达（POSTGRES_HOST/PORT/Password 环境变量）
ruff check . && ruff format --check . && mypy app

cd apps/web
npm install
npm run dev      # Vite dev server，/api 代理到 127.0.0.1:8000
npm run build    # tsc --noEmit + vite build
```

CI（GitHub Actions）：push / PR 触发四个 job —— **Backend**（ruff + mypy strict + pytest，
覆盖率 ≥ 80% 强制，起 Postgres service）、**Frontend**（`npm ci && npm run build`）、
**Container**（compose 配置校验 + api/web 镜像构建，GHA 层缓存）、**Publish images**（仅
push 到 main 或 `v*` tag 时，把 `ghcr.io/<owner>/<repo>/api|web` 推到 GHCR，tag 含
`sha-<短哈希>`、`main`、语义化版本）。同一分支的新推送会自动取消旧跑。

## 目录结构

```
home-atlas/
├── apps/api/          # FastAPI 应用（app/core 基础设施、app/modules 业务模块）
├── apps/web/          # React + TypeScript + Tailwind 前端（Vite 构建，nginx 托管）
├── deploy/            # docker-compose.yml + compose.dev.yaml（本地开发 overlay）+ .env.example
├── scripts/           # dev.sh（make dev 的编排脚本）
├── docs/              # architecture / database / development-roadmap / import-design / specification
└── .github/workflows/ # CI
```

## 文档

- [architecture.md](docs/architecture.md) — 架构、已实现 API 与请求流
- [database.md](docs/database.md) — schema、约束、迁移与测试策略
- [development-roadmap.md](docs/development-roadmap.md) — 阶段计划与当前进度
- [import-design.md](docs/import-design.md) — 数据导入设计与 2B-1 同步骨架实施记录
