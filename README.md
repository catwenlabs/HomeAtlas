# HomeAtlas

> 自托管的家庭财务数据中心 —— 收支记账、多币种资金、投资持股、贷款负债与净资产趋势，全部数据留在自己的服务器上。

[![ci](https://github.com/catwenlabs/HomeAtlas/actions/workflows/ci.yml/badge.svg)](https://github.com/catwenlabs/HomeAtlas/actions/workflows/ci.yml)

## 这是什么

HomeAtlas 是一个面向单家庭（可多成员）的自托管记账与资产负债应用。它不只是记流水：账户余额完全由流水推导、支持多币种与跨币种转账、信用卡透支、CSV/Excel 账单导入、投资持仓与股票行情估值、贷款负债，最终汇总为**每日净资产快照**——现金 + 投资浮盈 − 负债，一目了然。

核心原则：

- **余额只能由流水推导**，任何资金变动都留痕，不允许直接改余额；
- **已确认记录只能冲正，不能删改**，每一步都有审计日志；
- **金额全程 Decimal**，按币种精度 half-even 取整，永不浮点失真；
- 模块化单体 + Docker Compose，一台 NAS / VPS 即可运行。

## 功能特性

- **收支记账**：草稿 → 确认 → 冲正状态机；分类（两级）、备注、外部流水号、关键词与多维筛选；负余额拒绝（信用卡账户除外）。
- **多币种与转账**：同币种 / 跨币种 / 同账户换汇；`to_amount` 为入账权威值，汇率为记录值；手续费自动生成衍生支出并计入统计；一切可冲正回滚。
- **数据导入**：CSV / XLSX 上传 → 字段映射（四种金额方向模式）→ 预览与去重（精确指纹 + 可选模糊）→ 行级修正 → 人工确认生成流水；支持模板下载与批量操作。
- **统计**：收支 / 分类 / 月度 / 年度 / 现金流（按家庭时区分组、本位币聚合），转账本金不计收支、手续费恰计一次。
- **投资与持股**：登记型（独立快照，推荐股票用法）或托管型（入金走内部转账）；全额赎回自动结算损益并生成衍生收支；持股记录市场 + 代码 + 数量 + 成本单价，一键拉取 A股 / 港股 / 美股行情自动估值。
- **贷款**：轻量模型（本金 / 利率 / 还款日），剩余本金手动维护，日利息与负债端自动并入净资产。
- **净资产总览**：实时 summary 与每日快照（幂等 upsert）、趋势序列、月度聚合、闲置 / 理财中 / 已到期分桶、到期提醒数据、未映射现金对账诊断。
- **认证与多成员**：JWT 登录，owner 可管理成员；首次部署初始化向导，迁移不写入任何用户数据。
- **审计**：全部关键操作（创建 / 修改 / 冲正 / 状态迁移 / 导入 / 估值 / 快照）写入审计日志，含变更前后快照。

## 技术栈

| 层 | 选型 |
| -- | -- |
| 后端 | Python 3.12 · FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic v2 |
| 数据库 | PostgreSQL 17（schema: `core` / `finance` / `system`） |
| 前端 | React 19 · TypeScript · Vite · Tailwind CSS · TanStack Router/Query |
| 部署 | Docker Compose（postgres + api + web/nginx）；CI 构建并发布镜像到 GHCR |
| 质量 | pytest（覆盖率 ≥ 80% 强制）· ruff · mypy strict |

## 快速开始

前置条件：Docker（含 compose v2）。

```bash
git clone https://github.com/catwenlabs/HomeAtlas.git
cd HomeAtlas/deploy

cp .env.example .env
# 编辑 .env，至少设置：
#   POSTGRES_PASSWORD=强密码
#   JWT_SECRET_KEY=至少 32 字节的随机串

docker compose up -d                                   # postgres + api + web
docker compose run --rm api alembic upgrade head       # 建表（不会写入任何用户数据）
```

验证：

```bash
curl http://127.0.0.1:8000/health    # {"status":"ok"}
```

然后打开 **<http://127.0.0.1:8080>**，按首次部署向导创建管理员、确认家庭信息、勾选要写入的币种与分类即可开始使用。API 交互文档（Swagger UI）在 <http://127.0.0.1:8000/docs>。

> 数据库迁移是显式命令，不在容器启动时自动执行；升级版本后同样执行一次 `docker compose run --rm api alembic upgrade head`。

## 配置

必填两项见上。常用可选项（完整列表见 [deploy/.env.example](deploy/.env.example)）：

| 变量 | 默认 | 说明 |
| -- | -- | -- |
| `API_BIND` | `127.0.0.1:8000` | API 端口绑定（仅本机；局域网访问改为内网 IP） |
| `WEB_BIND` | `127.0.0.1:8080` | Web 前端端口绑定 |
| `QUOTE_PROVIDER` | `tencent` | 行情源（`tencent` 免 key 覆盖 A股/港股/美股；`fake` 离线确定性价格） |
| `QUOTE_PROXY_URL` | 空 | 访问美股行情的 HTTP 代理（按需） |
| `IMPORT_MAX_FILE_MB` / `IMPORT_MAX_ROWS` | `10` / `20000` | 导入单文件上限 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `10080`（7 天） | JWT 有效期 |

## API

统一前缀 `/api/v1`，统一响应 envelope，除 `setup/*`、`auth/login` 与探针外全部需要 `Authorization: Bearer <token>`（家庭作用域由 token 派生）。模块一览：

Setup / Auth / Users / Households / Accounts（含 credit 透支与 investment 托管账户）/ Currencies / Categories / Transactions / Transfers / Imports / Statistics / Exchange Rates / Assets（summary 与快照）/ Investments / Holdings / Tags / Loans / Market Quotes

- **完整端点清单与 curl 示例**：[docs/api.md](docs/api.md)
- **交互式文档**：运行后访问 `/docs`

## 文档

| 文档 | 内容 |
| -- | -- |
| [docs/architecture.md](docs/architecture.md) | 架构与请求流 |
| [docs/database.md](docs/database.md) | 数据库 schema、约束与迁移策略 |
| [docs/api.md](docs/api.md) | 端点清单与调用示例 |
| [docs/development-roadmap.md](docs/development-roadmap.md) | 阶段计划与已完成任务记录 |
| [docs/specification.md](docs/specification.md) | 完整规格说明书（v1.5） |
| [docs/asset-design.md](docs/asset-design.md) | 投资 / 资产 / 负债设计（Phase 2C） |
| [docs/import-design.md](docs/import-design.md) | 数据导入设计 |

## 本地开发

仓库根目录的 Makefile 驱动（详见 [development-roadmap.md](docs/development-roadmap.md)）：

```bash
make dev          # 一键环境：dev postgres(127.0.0.1:54321) + uvicorn --reload + Vite
make test         # pytest + 覆盖率（CI 门槛 80%）
make lint         # ruff check + format --check
make typecheck    # mypy strict
make web-build    # tsc --noEmit + vite build
```

CI：push / PR 触发 Backend / Frontend / Container / Publish 四个 job，镜像发布至 GHCR。

## 项目状态

后端功能主体与 Web 界面已完成（Phase 1 全部、2A 认证与 Web、2B 导入、2E 转账、2C 全部——汇率、投资与持股行情估值、贷款、净资产快照与资产负债页）；剩余 2D（Grafana）与暂缓的 2B-2（异步导入）。完整状态见 [development-roadmap.md](docs/development-roadmap.md)。
