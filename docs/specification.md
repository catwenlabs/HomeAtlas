# HomeAtlas — AI Development Specification

> Version: **1.3**
> 本版本取代 issue #1 正文（v1.2）。修订依据：三方交叉评审（Claude × Antigravity × 独立第三评审），修订记录见文末附录 A。

- Project: HomeAtlas
- Repository: home-atlas
- Architecture: Modular Monolith
- Deployment: Docker Compose
- Backend: Python + FastAPI
- Database: PostgreSQL
- Message Broker: NATS JetStream（后续启用）
- Frontend: 暂不开发
- Visualization: Grafana（第二阶段）

## 0. 项目总目标

HomeAtlas 是一个自托管的家庭数据中心。

长期目标是统一管理：

- 家庭收入与支出。
- 银行账户和多币种资金。
- 投资和证券资产。
- 家庭资产与负债。
- 家庭基础设施。
- 其他自定义数据。

但当前开发必须严格控制范围。

### 当前第一阶段目标

**只开发家庭收支管理的后端 API，不开发 Web 前端。**

第一阶段交付一个可以独立运行的 REST API 服务，支持：

1. 家庭基础信息。
2. 银行账户管理。
3. 币种管理。
4. 收入记录。
5. 支出记录。
6. 收支分类。
7. 内部转账。
8. 多币种基础支持。
9. 账户余额管理和核对。
10. 收支统计查询。
11. 数据审计。
12. API 文档和自动化测试。

暂时不开发：

- React Web。
- shadcn/ui。
- 投资管理。
- 资产负债管理。
- 股票行情采集。
- 基础设施管理。
- 自定义数据集。
- Grafana。
- Prometheus。

CSV / Excel 文件导入作为第一阶段后续扩展任务，不阻塞基础收支 API 的交付。

## 1. 核心工程原则

- PostgreSQL 是唯一业务事实来源。
- 使用模块化单体，不拆分微服务。
- 所有金额使用 Decimal / NUMERIC。
- 所有时间使用带时区的时间类型。
- 所有数据库变更使用 Alembic。
- 所有业务逻辑放在 Service 层。
- API Router 只负责请求、响应和依赖注入。
- 所有重要业务操作必须有事务保护。
- 所有财务数据必须可以追溯来源。
- 重要数据修改必须保留审计记录。
- 内部转账不能计入收入或支出（转账手续费除外，见 5.2）。
- 不允许通过简单删除历史流水来修正账目。
- 未来扩展不能破坏现有数据模型。
- 所有服务使用 Docker Compose 部署。
- AI Agent 不允许一次性生成全部功能。
- 必须按照开发阶段逐步实现，每个阶段完成后进行测试和验收。

## 2. 技术栈

### 2.1 后端

| 技术 | 选型 |
| -- | -- |
| Language | Python 3.12+ |
| Framework | FastAPI |
| ORM | SQLAlchemy 2.x（async） |
| Migration | Alembic |
| Validation | Pydantic v2 |
| Database | PostgreSQL 17 |
| Database Driver | asyncpg |
| Testing | pytest + pytest-asyncio |
| Logging | structlog（定案，不用标准 logging） |
| API Documentation | OpenAPI / Swagger |

## 3. 项目结构

Monorepo 布局如下（Task 001 按此创建骨架，`deploy/docker-compose.yml` 的 `build: context: ../apps/api` 依赖此布局）：

```
home-atlas/
├── apps/
│   └── api/                      # FastAPI 应用
│       ├── app/
│       │   ├── core/             # 配置、日志、数据库会话、异常、依赖注入
│       │   ├── modules/          # 业务模块（按领域划分，对应 DB schema）
│       │   │   ├── households/   # core schema
│       │   │   ├── accounts/     # core schema
│       │   │   ├── currencies/   # core schema
│       │   │   ├── categories/   # finance schema
│       │   │   ├── transactions/ # finance schema
│       │   │   ├── transfers/    # finance schema
│       │   │   ├── balances/     # core schema
│       │   │   ├── statistics/
│       │   │   └── audit/        # system schema
│       │   └── main.py
│       ├── alembic/              # 迁移（含 data migration seed）
│       ├── tests/
│       ├── pyproject.toml
│       └── Dockerfile
├── deploy/
│   ├── docker-compose.yml
│   └── .env.example
├── docs/
│   ├── architecture.md
│   ├── database.md
│   └── development-roadmap.md
└── README.md
```

- 每个模块内部按 `router.py` / `schemas.py` / `service.py` / `models.py` 组织。
- 数据库使用三个 PostgreSQL schema：`core`、`finance`、`system`。
- 未来需要时再添加模块：`investment`、`asset`、`market`、`infra`、`ingest`、`custom_data`、`analytics`。

## 4. 数据模型

### 4.1 core.households

家庭主体。

- id UUID PRIMARY KEY
- name VARCHAR(100)
- base_currency CHAR(3)
- timezone VARCHAR(64)
- created_at TIMESTAMPTZ
- updated_at TIMESTAMPTZ

规则：

- base_currency 默认 CNY。
- timezone 默认 Asia/Shanghai。
- **已有任何流水或转账后，禁止修改 base_currency**（历史 base_amount 按录入时汇率固化，改本位币会导致统计失真）。Service 层校验。
- 第一阶段以单家庭使用为主要场景，但保留 household_id，避免以后扩展时重构所有业务表。

### 4.2 core.accounts

账户表。

- id UUID PRIMARY KEY
- household_id UUID NOT NULL
- name VARCHAR(100)
- institution VARCHAR(100)
- account_type VARCHAR(30)
- currency CHAR(3)
- external_ref VARCHAR(255)
- is_active BOOLEAN
- created_at TIMESTAMPTZ
- updated_at TIMESTAMPTZ

account_type：

- bank
- cash
- wallet
- other

规则：

- currency 表示账户**默认**币种；同一账户允许存在多个币种资金（交易币种可不同于默认币种，见 4.5）。
- 账户名称和机构名称允许用户自定义。
- 账户停用不代表删除历史交易。
- 已有历史交易（含 opening_balance 流水）的账户，DELETE 接口拒绝物理删除，建议停用。

### 4.3 core.currencies

币种表。

- code CHAR(3) PRIMARY KEY
- name VARCHAR(50)
- symbol VARCHAR(10)
- decimal_places SMALLINT
- is_active BOOLEAN

初始数据（Alembic data migration 写入）：CNY、USD、HKD、EUR、GBP、JPY。

- 币种列表允许后续扩展。
- API 录入金额时按 decimal_places 校验并取整（舍入方式 half-even）。

### 4.4 finance.categories

收支分类。

- id UUID PRIMARY KEY
- household_id UUID NOT NULL
- name VARCHAR(100)
- category_type VARCHAR(20)  # income | expense
- parent_id UUID NULL
- icon VARCHAR(50)
- sort_order INTEGER
- is_active BOOLEAN
- created_at TIMESTAMPTZ
- updated_at TIMESTAMPTZ

约束（Service 层 + DB 层）：

- parent 若存在，必须属于同一 household。
- 父子分类的 category_type 必须一致。
- parent_id 不得指向自身；层级最多两级（即 parent 不能再有 parent），天然禁环。
- 支持停用；分类停用不影响历史记录。
- 有历史交易引用的分类，DELETE 拒绝，建议停用。

初始分类树（seed）：收入（工资、奖金、利息、其他收入）、支出（餐饮、购物、交通、住房、娱乐、其他支出）、**金融手续费**（转账衍生支出专用，系统内置，不可删除）。

### 4.5 finance.transactions

收支流水主表（含初始余额开账流水）。

- id UUID PRIMARY KEY
- household_id UUID NOT NULL
- account_id UUID NOT NULL
- category_id UUID NULL
- transaction_type VARCHAR(20)
- amount NUMERIC(24,8)
- currency CHAR(3)
- base_amount NUMERIC(24,8)
- base_currency CHAR(3)
- exchange_rate NUMERIC(24,12)
- exchange_rate_date DATE
- transaction_date TIMESTAMPTZ
- description TEXT
- source VARCHAR(30)
- external_id VARCHAR(255)
- status VARCHAR(20)
- reverses_transaction_id UUID NULL   # 冲正关联：本记录冲正的原记录
- transfer_id UUID NULL               # 衍生关联：由内部转账自动生成的手续费支出
- created_at TIMESTAMPTZ
- updated_at TIMESTAMPTZ

transaction_type：

- income
- expense
- **opening_balance**（初始余额开账，单边流水）

status（状态机）：

- draft → confirmed → reversed
- 合法迁移：draft→confirmed；confirmed→reversed。其余禁止。

source 枚举：

- manual（手工录入）
- system（系统生成，如转账手续费衍生支出、冲正反向记录）
- import（文件导入，Phase 1.5 启用）

规则：

- income / expense：amount 恒为正数（DB CHECK `amount > 0`），方向由 transaction_type 表达，禁止正负金额混合表达。
- **opening_balance：豁免恒正规则，允许负数**（为第二阶段 C 负债/透支开账预留；Phase 1 正常场景为非负）。
- opening_balance 不计入任何收支统计；统计与余额相关查询中，收支统计必须显式过滤 `transaction_type != 'opening_balance'`。
- currency 可为任一激活币种，不限于账户默认币种；exchange_rate 与 base_amount 记录规则同 v1.2（同本位币时 rate = 1）。
- 修改（PUT）：仅 draft 状态可修改任意字段；confirmed 及之后状态拒绝修改，必须走冲正。
- 删除（DELETE）：仅 draft 状态可物理删除；confirmed 之后拒绝（见 5.5）。
- 冲正（reverse）：对 confirmed 记录生成一条关联反向记录（amount 相同、类型取反方向记账、reverses_transaction_id 指向原记录），原记录 status 置 reversed；冲正与反向记录在同一事务中落库。
- reverses_transaction_id / transfer_id 有值时，DB 外键指向 finance.transactions.id / finance.transfers.id。

索引：

- (household_id, transaction_date)
- (account_id, transaction_date)
- (category_id)
- (status)
- (transfer_id)

### 4.6 finance.transfers

内部转账。

- id UUID PRIMARY KEY
- household_id UUID NOT NULL
- from_account_id UUID NOT NULL
- to_account_id UUID NOT NULL
- from_amount NUMERIC(24,8)
- from_currency CHAR(3)
- to_amount NUMERIC(24,8)
- to_currency CHAR(3)
- exchange_rate NUMERIC(24,12)
- base_amount NUMERIC(24,8) NULL      # from_amount 的本位币折算，录入时固化
- base_currency CHAR(3) NULL
- fee NUMERIC(24,8)
- fee_currency CHAR(3)
- transfer_date TIMESTAMPTZ
- description TEXT
- status VARCHAR(20)                  # draft → confirmed → reversed，同 4.5
- reverses_transfer_id UUID NULL      # 冲正关联
- created_at TIMESTAMPTZ
- updated_at TIMESTAMPTZ

规则：

- **校验：`(from_account_id ≠ to_account_id) OR (from_currency ≠ to_currency)`**——允许同账户跨币种换汇（银行内购汇），禁止完全相同的无效转账。
- from_account / to_account 必须属于同一 household。
- **exchange_rate 仅为记录值（实际成交比价），不强制 `from_amount × exchange_rate = to_amount`**（容忍银行点差与隐含费用）；**to_amount 为入账权威值**。
- base_amount / base_currency 记录转账发生时的本位币价值（家庭本位币视角的资产变动历史），按录入时汇率折算固化。
- **手续费（fee）独立于 from_amount**（不含其中），从 from_account 以 fee_currency 扣除，DB CHECK `fee >= 0`。
- **fee > 0 时，必须在同一数据库事务中自动生成一笔关联支出流水**：transaction_type = expense、category = 金融手续费、account = from_account、amount = fee、currency = fee_currency、source = system、transfer_id 指向本转账、携带 base_amount 折算。转账记录、衍生手续费支出与余额变动的创建、冲正、回滚必须处于同一事务，杜绝孤儿流水。
- 转账（含衍生手续费）不计入收入；转账本金不计入支出，**手续费经由衍生支出行计入支出统计**（见 5.2）。
- 跨币种转账必须记录：转出金额、转出币种、转入金额、转入币种、汇率、手续费、发生时间。
- 冲正语义同 4.5：reverses_transfer_id + 关联反向记录（含衍生手续费支出的冲正），同事务。

索引：(household_id, transfer_date)、(from_account_id)、(to_account_id)、(status)。

### 4.7 core.account_balances

账户余额快照（**对账专用**，与流水计算的账面余额是两个概念，不得混用）。

- id UUID PRIMARY KEY
- account_id UUID NOT NULL
- currency CHAR(3)
- balance NUMERIC(24,8)
- snapshot_at TIMESTAMPTZ
- source VARCHAR(30)
- created_at TIMESTAMPTZ

source 枚举：

- manual（用户手工录入的实际余额）
- bank（银行对账单/导入的实际余额）

规则：

- 本表只存**实际余额快照**，用于与流水计算余额核对、保存历史余额；不承载初始余额（初始余额是 opening_balance 流水，见 4.5）。
- 唯一约束 `(account_id, currency, snapshot_at, source)`——同一时刻手工录入与银行导入可并存。
- `GET /accounts/{id}/balances` 返回**两部分**：按流水实时计算的各币种账面余额 + 每币种最近一条对账快照（含差额），一次调用即可完成核对。

### 4.8 system.audit_logs

审计日志。

- id UUID PRIMARY KEY
- household_id UUID NULL   # 预留多家庭隔离维度
- actor VARCHAR(100)       # Phase 1 无认证，固定为 'system'；字段保留
- action VARCHAR(100)
- entity_type VARCHAR(100)
- entity_id UUID
- before_data JSONB
- after_data JSONB
- created_at TIMESTAMPTZ

重要的新增、修改、冲正、状态迁移操作必须保留审计记录。

## 5. 财务业务规则

这一部分优先级高于接口实现。

### 5.1 收入和支出

收入与支出必须分开表达。

- Income = SUM(income transactions)
- Expense = SUM(expense transactions)（**含转账自动生成的手续费衍生支出**）
- Net Cashflow = Income − Expense

统计时必须排除：

- 内部转账本金。
- 账户间资金调拨。
- 换汇本金。
- 投资账户入金。
- **初始余额开账流水（opening_balance）**。

统计聚合口径：

- 收支/分类/月度统计直接聚合 `base_amount`（录入时已按当时汇率固化为家庭本位币），无需运行时汇率。
- **月度/年度统计的日期分组必须按 `household.timezone` 截断**（`AT TIME ZONE household.timezone`），不得按 UTC 分组，避免月初 0–8 点流水错划入上月。

### 5.2 内部转账与手续费

例如：从中国银行转账 1000 元到汇丰银行，结果：

- 中国银行余额减少 1000。
- 汇丰银行余额增加 1000。
- 家庭总资产不因这笔转账改变。
- 转账本金不计入收入，也不计入支出。

**手续费会计闭环**：转账手续费虽然伴随内部转账产生，但它是一项真实支出——若不计入支出统计，`Income − Expense` 将永远无法与现金流变动对账。因此 fee > 0 时自动生成衍生支出行（见 4.6），使 `Expense = SUM(expense transactions)` 保持唯一统计路径，余额公式亦无需单独的 Fee 项。

### 5.3 多币种

例如：人民币账户和美元账户之间发生资金转换，必须分别保留：

- 人民币转出金额。
- 美元转入金额。
- 汇率（记录值，见 4.6）。
- 手续费。
- 发生时间。

不允许简单把两边都当作收入或支出。同账户内购汇（from_account = to_account、币种不同）是合法场景。

### 5.4 余额计算

每个账户、每种币种分别计算：

```
Current Balance =
  SUM(opening_balance 流水)        # 含负数开账
+ SUM(income 流水)
− SUM(expense 流水)                # 含转账衍生手续费支出
+ SUM(transfer in)
− SUM(transfer out + fee)
```

规则：

- 全部由 finance.transactions 与 finance.transfers 单表聚合得出，无需拼接快照表。
- **Phase 1 拒绝导致负余额的支出/转账/手续费**（Service 层校验并返回明确错误）；透支与信用账户随第二阶段 C 引入。
- 初始余额由 opening_balance 单边流水承载，不是收入。

### 5.5 历史数据与状态机

- 状态机：`draft → confirmed → reversed`（transactions 与 transfers 一致）。
- draft：可任意修改（PUT）、可物理删除（DELETE）、可确认。
- confirmed：禁止修改、禁止物理删除；修正只能冲正（reverse 生成关联反向记录）或"冲正 + 新建正确记录"。
- reversed：终态，禁止一切修改与删除。
- 已确认流水的冲正必须留审计记录（before/after + 关联链）。

## 6. API 设计

统一前缀：`/api/v1`

### 6.0 Household 作用域（新增）

- 所有业务端点接受可选 Header `X-Household-Id`。
- 未传递且数据库中仅存在一个家庭：服务端兜底使用该家庭。
- 未传递且存在多个家庭：返回 400（error_code = HOUSEHOLD_REQUIRED）。
- 传递了不存在的家庭：返回 404。
- 前端/客户端应统一封装注入该 Header（Phase 2 实施项）。

### 6.1 Household API

- GET /households
- GET /households/{id}
- POST /households
- PUT /households/{id}（已有流水后禁止修改 base_currency）

### 6.2 Account API

- GET /accounts
- POST /accounts
- GET /accounts/{id}
- PUT /accounts/{id}
- DELETE /accounts/{id}（已有历史交易则拒绝，建议停用）
- GET /accounts/{id}/balances（实时账面余额 + 最近对账快照 + 差额）
- GET /accounts/{id}/transactions
- GET /accounts/{id}/balance-history（对账快照时间序列）

### 6.3 Currency API

- GET /currencies
- GET /currencies/{code}

第一阶段使用预置币种，不需要复杂的币种管理后台。

### 6.4 Category API

- GET /categories（按类型筛选、父子查询、排序）
- POST /categories
- GET /categories/{id}
- PUT /categories/{id}
- DELETE /categories/{id}（有历史引用则拒绝，建议停用）

### 6.5 Transaction API

- GET /transactions
- POST /transactions
- GET /transactions/{id}
- PUT /transactions/{id}（仅 draft）
- DELETE /transactions/{id}（仅 draft）
- POST /transactions/{id}/reverse（仅 confirmed）

查询支持：开始日期、结束日期、账户、分类、类型（income/expense/opening_balance）、币种、金额区间、关键词、状态、分页、排序。

### 6.6 Transfer API

- GET /transfers
- POST /transfers
- GET /transfers/{id}
- PUT /transfers/{id}（仅 draft）
- POST /transfers/{id}/reverse（仅 confirmed）

### 6.7 Statistics API

- GET /statistics/overview
- GET /statistics/income-expense
- GET /statistics/category
- GET /statistics/monthly
- GET /statistics/account-balances
- GET /statistics/cashflow

统计支持：月度/年度收入、支出、结余；分类占比；账户余额；自定义日期范围。

**Phase 1 币种口径（定案）**：

- 收支类统计（income-expense / category / monthly / cashflow）以家庭本位币返回（聚合 base_amount）。
- **余额类统计（account-balances / overview 的资产部分）只返回分币种明细，不折算总额**——运行时折算需要当前汇率，而 Phase 1 无汇率表；总额折算推迟到引入 exchange_rates（Phase 2 或更晚）。

### 6.8 API 规范

所有列表接口支持统一分页入参：`page`、`page_size`、`sort_by`、`sort_order`。

统一响应结构：

```json
{
  "success": true,
  "data": {},
  "message": null
}
```

列表响应的 `data` 固定为：

```json
{
  "items": [],
  "total": 120,
  "page": 1,
  "page_size": 20
}
```

错误响应：

```json
{
  "success": false,
  "data": null,
  "message": "Invalid transaction",
  "error_code": "TRANSACTION_INVALID"
}
```

- error_code 全局枚举（SCREAMING_SNAKE_CASE），与 HTTP 状态码一一映射（4xx 业务错误、5xx 系统错误），Phase 1.0 建表维护。
- FastAPI 自动生成 OpenAPI 文档，Swagger UI 可直接调试所有接口。
- `/health` 返回进程存活；`/ready` 检查数据库连接（`SELECT 1`），compose healthcheck 使用 `/ready`。

## 7. Docker Compose 部署

第一阶段只部署：

```
home-atlas
├── api
└── postgres
```

暂不部署：web、nats、worker、grafana、prometheus。

### 7.1 Docker Compose

```yaml
services:
  postgres:
    image: postgres:17
    container_name: homeatlas-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: home_atlas
      POSTGRES_USER: homeatlas
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - backend
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U homeatlas -d home_atlas"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    build:
      context: ../apps/api
    container_name: homeatlas-api
    restart: unless-stopped
    env_file:
      - .env
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "${API_BIND:-127.0.0.1:8000}:8000"
    networks:
      - backend
      - frontend
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready')"
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  postgres_data:

networks:
  backend:
    internal: true   # postgres ↔ api 内部通信，不发布端口
  frontend:          # 普通网络，承载 api 端口发布（internal 网络上的 ports 不可达）
```

修订说明（相对 v1.2）：

- **双网络**：api 同时挂 `backend`（internal，连 postgres）与 `frontend`（承载 ports 发布）——v1.2 中 api 只挂 internal 网络导致 8000 端口从宿主机不可达，Swagger 与 /health 验收必挂。
- 端口绑定默认 `127.0.0.1:8000`（仅本机）；需要局域网访问时通过 `.env` 的 `API_BIND` 改为内网 IP，不默认暴露。
- PostgreSQL 不映射公网端口。
- 镜像锁定版本。

**Migration 执行通道（定案）**：不在容器启动时自动迁移。使用独立命令：

```bash
docker compose run --rm api alembic upgrade head
```

此命令写入 README 与 development-roadmap.md。

要求：

- 数据使用持久化 Volume。
- 环境变量放入 `.env`（提供 `.env.example`），`.env` 不提交 Git。
- 定期备份数据库并测试恢复。

### 7.2 数据目录

建议：

```
/mnt/user/appdata/home-atlas/
├── backups/
└── exports/
```

PostgreSQL 数据优先放在可靠的本地 SSD 存储。备份放 Unraid，并进行加密。

## 8. 第一阶段开发计划

### Phase 1.0：基础设施

任务：创建 Monorepo（按 §3 布局）、初始化 FastAPI、配置 PostgreSQL、Docker Compose（§7.1 双网络版）、SQLAlchemy、Alembic、环境变量、structlog 日志、`/health` 与 `/ready`、基础文档（README、architecture.md、database.md、development-roadmap.md）、pytest 框架 + CI。

验收：docker compose up -d 正常；/health、/ready 正常（宿主机可达）；API 可访问 PostgreSQL；`docker compose run --rm api alembic upgrade head` 正常执行；数据库重启后数据不丢失；pytest 基础测试通过；CI 全绿。

### Phase 1.1：基础数据模型

任务：Household、Account、Currency、Category、Account Balance 建表（含 §4 全部约束、索引、状态机字段、冲正/衍生关联字段）；币种与分类 Seed（Alembic data migration）；opening_balance 开账流水；household 作用域依赖（§6.0）。

验收：可创建家庭/账户/分类；可设置（含修改）初始余额并留审计；多币种账户开账正确；非法操作（负金额、跨家庭 parent、越级 parent）被约束拒绝；X-Household-Id 兜底与 400 行为正确。

### Phase 1.2：收支管理 API

任务：收入/支出创建（状态机：draft → confirmed）、修改（仅 draft）、查询（全部筛选条件）、冲正（仅 confirmed，生成关联反向记录）、删除（仅 draft）、审计日志。

验收：能够创建/修改/冲正/删除（各状态边界正确）；修改与冲正均留审计记录；查询条件正确；金额精度正确（按 decimal_places 取整）；分页含 total/page/page_size。

### Phase 1.3：转账与多币种

任务：同币种转账、跨币种转账（含同账户换汇）、汇率记录（to_amount 权威、rate 记录值）、手续费衍生支出（同事务）、余额计算、余额核对（账面 vs 快照）。

验收：转账双边金额正确；同账户换汇可用；fee > 0 时衍生支出行同事务生成、冲正时同事务回滚；负余额操作被拒绝；失败事务完整回滚（含衍生支出不留孤儿）；多币种计算正确。

### Phase 1.4：统计 API

任务：收入/支出/月度/年度/分类/账户余额/资金流向统计（按 household.timezone 分组；收支类聚合 base_amount；余额类只出分币种明细）。

验收：统计结果与原始流水一致；内部转账本金不重复计算、手续费恰好计一次；开账余额不虚增收支；不同币种收支正确折算本位币；月度边界按家庭时区正确划分；支持自定义日期范围。

### Phase 1.5：数据导入预留

先完成接口和模型设计评审，不必立即开发文件导入。后续实现：CSV 上传、Excel 上传、字段映射、原始数据保存、数据预览、重复检测、人工确认、正式导入。这一阶段再引入 NATS JetStream 和独立 Import Worker。

## 9. 自动化测试

### 9.0 测试基建（新增）

- pytest + pytest-asyncio + httpx AsyncClient。
- 集成测试使用真实 PostgreSQL（docker compose 起的测试库或 testcontainers）。
- 测试隔离：每用例包裹事务回滚，或每用例 truncate 全部业务表。
- 覆盖率 ≥ 80%（pytest-cov），CI 强制。
- CI：GitHub Actions，push/PR 触发 lint（ruff）+ 类型检查 + pytest + coverage。

### 9.1 基础测试

创建家庭、创建账户、创建分类、设置初始余额（含负数开账）、修改账户状态、household 作用域（兜底/400/404）、base_currency 锁定。

### 9.2 收支测试

创建收入、创建支出、draft 修改、状态机边界（confirmed 不可改/不可删）、冲正（反向记录 + 原记录置 reversed + 审计）、删除限制、日期/分类/类型筛选、分页。

### 9.3 转账测试

同币种转账、跨币种转账、同账户换汇、手续费衍生支出（同事务、计入支出统计）、冲正回滚（含衍生行）、余额变化、负余额拒绝、事务回滚。

### 9.4 统计测试

月度收入、月度支出、分类统计、年度统计、多币种统计（base_amount 折算）、内部转账本金排除、手续费恰好计一次、开账余额排除、月度时区边界（月初 0–8 点归属）。

### 9.5 关键验收场景

创建家庭 → 创建中国银行账户 → 设置初始余额 → 创建工资收入 → 创建餐饮支出 → 转账到另一个账户（含手续费）→ 查询账户余额 → 查询当月收入支出 → 核对统计结果。

所有结果必须能够通过数据库原始记录核实。

## 10. 第二阶段规划

第一阶段稳定后，再逐步扩展。

- **第二阶段 A：Web 前端** — React、TypeScript、Vite、shadcn/ui、Tailwind CSS、TanStack Router/Query、Axios、Zustand、React Hook Form、Zod、Lucide React。先实现：登录、总览、账户管理、收支管理、分类管理、转账管理、统计页面。客户端统一注入 X-Household-Id。
- **第二阶段 B：异步数据处理** — NATS JetStream、Import Worker、Outbox Publisher；CSV / Excel 导入和外部数据采集。
- **第二阶段 C：投资与资产** — investment / asset / market schema；证券交易、股息、持仓、资产负债、净资产快照；引入 credit 账户类型与负余额/透支支持；余额类统计总额折算 + exchange_rates。
- **第二阶段 D：Grafana** — analytics schema 与只读视图，接入 Grafana。

## 11. AI Agent 当前执行任务

现在只执行：

**Task 001：建立 HomeAtlas 收支 API 基础项目**（Phase 1.0，前置阻塞项 §7.1 双网络与 §3 布局已在本规格定案）。

具体要求：初始化 FastAPI 项目（apps/api）、SQLAlchemy、Alembic、PostgreSQL、Docker Compose（deploy/，§7.1 版本）、环境变量（.env + .env.example）、统一异常处理、统一响应结构（§6.8）、/health 与 /ready、pytest + CI、README、architecture.md、database.md、development-roadmap.md。

暂时不要实现：Web、NATS、Worker、投资、资产负债、Grafana、文件导入。

验收：Docker Compose 正常启动（宿主机可达 8000）；API 可正常访问；/health、/ready 返回正常；API 可连接 PostgreSQL；`docker compose run --rm api alembic upgrade head` 正常执行；pytest 基础测试通过；数据库持久化正常。

完成后停止，不要自动执行 Task 002。向用户汇报：创建了哪些文件、项目目录结构、实际启动了哪些容器、测试结果、当前遗留问题、下一阶段开发计划。

---

## 附录 A：v1.3 修订记录（2026-11-11，三方交叉评审定案）

| # | 修订 | 来源 |
| -- | -- | -- |
| 1 | 新增 §3 项目结构（v1.2 缺失整节，补 monorepo 布局与模块/schema 映射） | 评审共识 |
| 2 | §7.1 修复 `internal: true` 与 ports 冲突：双网络 + API_BIND 默认绑 127.0.0.1 | 评审共识（唯一开工阻塞） |
| 3 | 初始余额定案为 `opening_balance` 单边流水，豁免恒正规则；§5.4 公式收敛为单表聚合 | A 提案，B 质疑负数，最终共识 |
| 4 | 状态机 `draft → confirmed → reversed` 落地；DELETE 保留但仅 draft（撤回"删端点"提案）；transactions/transfers 增加冲正关联字段 | B + 第三评审修正 A |
| 5 | 转账：exchange_rate 仅为记录值（容忍点差）、to_amount 为入账权威值；补 base_amount/base_currency；允许同账户跨币种换汇 | B 发现 |
| 6 | 手续费会计闭环：fee 独立于 from_amount、从 from_account 扣、同事务生成衍生支出行计入支出统计 | B 驳回 A 的"仅文档化"妥协 |
| 7 | 统计口径：收支类聚合 base_amount；余额类 Phase 1 只出分币种明细不折算总额；月度/年度按 household.timezone 分组 | 评审共识 |
| 8 | household 作用域：可选 `X-Household-Id` + 单家庭兜底 + 多家庭 400（撤回环境变量方案） | B 提案 |
| 9 | base_currency 已有流水后禁改；transaction.currency 放开为任一激活币种；Phase 1 拒绝负余额（透支随 2C） | 评审共识 |
| 10 | §6.8 分页出参 `{items, total, page, page_size}`、error_code 枚举与 HTTP 映射；/health 拆分 /ready（DB 检查） | 评审共识 |
| 11 | 约束与索引：金额/手续费 CHECK、转账双方同 household、分类层级约束（同家庭/同类型/两级/禁环）、account_balances 唯一键含 source、audit_logs 补 household_id | 第三评审 + B |
| 12 | §9 补测试基建：pytest-asyncio、真实 PG、事务回滚隔离、覆盖率 ≥80%、GitHub Actions CI；migration 执行通道定案 `docker compose run --rm api alembic upgrade head` | 第三评审 |

## 附录 B：v1.4 修订记录（2026-11-12，Phase 2C 设计评审）

| # | 修订 | 来源 |
| -- | -- | -- |
| 1 | §10 2C 范围调整：证券逐笔交易、股息、持仓明细与 market 行情 schema **暂缓**（持仓级 investments + 贷款 + 净资产快照先行）；`finance.trades` 前向预留，`investment_type` 含 stock/fund 保持兼容 | [asset-design.md](asset-design.md) §2.2 + 独立架构二审 |
| 2 | 2C 新增 `finance.exchange_rates`（家庭作用域）与账户扩展（`annual_rate` / `liquidity` / `credit_limit`，account_type 增加 `credit` / `investment`）；§519 的总额折算随 2C-1 落地 | asset-design §4.1–4.2 |
| 3 | 负余额规则细化：credit 账户放行透支（§430 的 2C 承诺兑现），守卫覆盖 transactions / transfers / imports 全部校验点；credit_limit 软校验默认开启 | asset-design §5.1 |
| 4 | 投资本金走内部转账（不得直改余额）、赎回损益衍生收支计入统计、`investment_transfers` 关联表保证冲正联动 | asset-design §4.6/§5.2 |
| 5 | 净资产唯一口径公式与 `unmapped_cash` 诊断字段定案；快照仅限当日（不接受历史补录） | asset-design §5.2/§6.5 |
