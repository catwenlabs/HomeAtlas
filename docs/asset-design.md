# 投资与资产负债设计（Phase 2C）

状态：设计评审稿 v2（2026-11-12）。基于 [specification.md](specification.md) §10 的 2C 规划，
结合 `ai-agent` 项目 `asset-panorama-web`（下称 panorama）的已验证实现评估整理。
v2 已吸收独立架构二审（对抗性评审）的全部 CRITICAL/HIGH 发现：
赎回闭环顺序定案（§5.2）、单一净资产公式（§5.2）、投资-转账关联表（§4.6）、
贷款剩余本金列（§4.3）、追加入金端点（§6.3）、币种口径统一（§5.6）、
负余额守卫统一（§5.1）、PUT 收窄（§6.3）、matured 计入净资产（§5.2）、
错误码去撞（§8）、迁移编号（§4）。本阶段**尚未产生代码**。

## 1. 背景与输入

- 规格长期目标包含「投资和证券资产」「家庭资产与负债」；§736 为 2C 预规划：
  investment / asset / market schema、证券交易、股息、持仓、资产负债、净资产快照、
  credit 账户与负余额/透支、余额类统计总额折算 + exchange_rates。
- Phase 1/2A/2B 已交付的收支/转账/导入/统计/认证地基（详见
  [development-roadmap.md](development-roadmap.md)）。
- panorama（NestJS + Prisma，单币种、余额直改、无审计）作为**产品层面的参考实现**：
  其贷款/理财/快照/总览功能经过真实使用验证，但工程实现不可直接照搬。

## 2. 既有 2C 规划评估与 panorama 参考价值

### 2.1 既有规划中保留的部分（价值已验证）

| 规划项 | 结论 | 依据 |
| -- | -- | -- |
| credit 账户 + 负余额/透支 | **保留，必做** | 地基已预留（opening_balance 豁免恒正 §273、负余额校验在 Service 层可按账户类型放行 §430） |
| exchange_rates + 余额类统计总额折算 | **保留，必做（2C 前置）** | 统计口径已预留（§519「折算推迟到引入 exchange_rates」）；净资产快照依赖它 |
| 净资产快照 | **保留，必做** | panorama 核心价值功能：每日 upsert + 历史趋势 + 月度汇总 |
| 资产负债管理 | **保留，按 panorama 模型裁剪** | 贷款用「本金 + 利率 + 还款日」的轻模型，不做逐期摊销台账 |

### 2.2 既有规划中降级/暂缓的部分

**证券交易、股息、持仓明细、market 行情 schema → 暂缓（2C-4 之后视需求）。**

理由：

1. 单家庭自托管场景下，panorama 证明「持仓级」（principal / current_value / 到期日）
   已覆盖家庭理财的记录需求（定存、活期、基金、股票账户整体、债券）。
2. 逐笔证券交易 + 行情采集意味着：行情数据源与定时任务、除权除息/拆股处理、
   成本基准（移动加权 vs 先进先出）、与快照的一致性 —— 复杂度高出一个量级，
   且 Phase 2B-2 异步化的教训是：没有明确数据量与运维需求前不引入后台组件。
3. 前向兼容已预留：`investments.investment_type` 含 `stock` / `fund`；未来若做交易级，
   增设 `finance.trades` 并以持仓快照对账迁移即可，不需要改动本设计的表结构。

### 2.3 panorama 贡献、panorama 不可照搬之处

**采纳（经适配）**：

- 总览三分：闲置（现金）/ 理财中（active 投资）/ 已到期未赎回；总负债；净资产；
  **日利息收入/支出 → dailyProfit**（账户与投资 `annual_rate` 计收入、贷款计支出）。
- 投资 `deduct_from_account`：建仓资金从现金账户转出，**避免现金与投资重复计入资产**。
- 到期处理：`end_date <= now` 的投资不计入「理财中」，进「已到期」提醒视图，
  赎回是显式操作（不自动改余额）。
- 投资多对多标签（资产配置分析维度）。
- 账户属性：`annual_rate`（账户利率）、`liquidity`（T0/T1/T2/T3/none）、`credit_limit`。
- 贷款轻模型：本金/年利率/起止日/`due_day` 还款日/还款方式/关联账户；不追每期还款。
- UI 模式：净资产趋势（Area/Line）、月度汇总（Bar）、资产配置（Pie）、到期提醒列表、
  使用指南页（guide）。

**不可照搬（与 HomeAtlas 原则冲突）**：

| panorama 做法 | HomeAtlas 原则 | 本设计替代 |
| -- | -- | -- |
| `PUT balance` 直改账户余额 | 余额只能由流水推导（§5.4） | 投资本金走**内部转账**进投资账户；估值走 `current_value` 字段 |
| 投资建仓记一笔普通支出 | 收支统计口径不被投资本金污染 | 转账本金不计收支（与 2E 一致）；赎回差额生成衍生收支 |
| 单币种 float 金额 | 多币种 Decimal + 精度取整 | 全链路 `Numeric` + 币种 `decimal_places` half-even |
| 快照由前端保证每日一条 | 服务端约束 | `UNIQUE (household_id, snapshot_date)` + upsert |
| 无审计 | 全操作审计 | loans / investments / 快照 / 汇率均写 `system.audit_logs` |
| 多租户 appKey / refreshToken / 配额 | 自托管单家庭 | 维持 2A 的 JWT + household 派生 |

## 3. 范围与非目标

**范围（拆分为 2C-1 ~ 2C-4，见 §11）**：汇率表、账户扩展与 credit/透支、贷款、
投资持仓与标签、净资产快照与总览折算、Web 图表与到期提醒。

**非目标**：证券逐笔交易/股息/行情采集（暂缓，§2.2）、贷款逐期摊销计划表、
外币负债自动估值、多家庭切换、导入工具（投资/贷款数据量小，手工录入）。

## 4. 数据模型设计（迁移草案）

迁移编号：`0005_phase_2c_1`（汇率 + 账户扩展 + 快照）、`0006_phase_2c_2`（投资 + 标签 +
关联表）、`0007_phase_2c_3`（贷款），与 §11 分期一一对应。所有金额
`Numeric(24, 8)`（与现有列一致），日期用 `DATE`（自然日，按家庭时区解释，与
transactions 一致），所有表带 `created_at` / `updated_at`。

### 4.1 `finance.exchange_rates`（2C-1）

| 列 | 类型 | 说明 |
| -- | -- | -- |
| id | UUID PK | |
| household_id | UUID FK core.households | 汇率是家庭记账视角（银行报价），非全局行情 |
| base_currency | CHAR(3) FK core.currencies | |
| quote_currency | CHAR(3) FK core.currencies | `1 base = rate quote` |
| rate | Numeric(24,12) NOT NULL CHECK (rate > 0) | |
| rate_date | DATE NOT NULL | 汇率适用日 |
| source | VARCHAR(20) DEFAULT 'manual' | manual / import / system |
| created_at / updated_at | timestamptz | |

约束：`UNIQUE (household_id, base_currency, quote_currency, rate_date)`；
`CHECK (base_currency <> quote_currency)`；索引 household+日期。

取数规则：`latest(base, quote, date <= 查询日)`；无则查反向 `1/rate`；
再无则报 `EXCHANGE_RATE_NOT_FOUND`。**不提供**三角套算（记录需求不成立时由用户补录）。

### 4.2 `core.accounts` 扩展（2C-1）

- `account_type` CHECK 增加 `'credit'`（信用卡/透支账户）与 `'investment'`
  （证券/理财托管账户）。
- 新增可空列：`annual_rate Numeric(12,8)`（账户年化利率，活期/货基收益）、
  `liquidity VARCHAR(10) CHECK IN ('none','T0','T1','T2','T3')`、
  `credit_limit Numeric(24,8) CHECK (credit_limit >= 0)`。
- credit 账户语义：账面余额允许为负（见 §5.1）；`credit_limit` 仅软校验（可配置关闭），
  `available_credit = credit_limit + balance`（balance 为负）。

### 4.3 `finance.loans`（2C-3）

| 列 | 类型 | 说明 |
| -- | -- | -- |
| id / household_id | UUID | |
| name | VARCHAR(100) NOT NULL | |
| institution | VARCHAR(100) | 银行/机构 |
| principal | Numeric(24,8) NOT NULL CHECK (> 0) | 放款本金（本位币或指定币种） |
| currency | CHAR(3) FK | |
| annual_rate | Numeric(12,8) NOT NULL CHECK (>= 0) | |
| start_date / end_date | DATE / DATE NULL | end_date NULL = 无固定期限 |
| due_day | SMALLINT CHECK (1..31) | 还款日提醒 |
| repayment_type | VARCHAR(30) CHECK IN ('monthly_interest','one_time') | 首版两种（panorama 同款） |
| linked_account_id | UUID NULL FK core.accounts | 还款扣款账户（仅提示用） |
| remaining_principal | Numeric(24,8) NOT NULL CHECK (>= 0) DEFAULT principal | 剩余本金；首版手动维护（§13.3），settle 时置 0（允许提前结清） |
| status | VARCHAR(20) CHECK IN ('active','settled') DEFAULT 'active' | |
| settled_date | DATE NULL | 结清日 |
| remark | VARCHAR(500) | |

索引：household+status。**没有**每期还款表：还款就是一笔普通支出流水
（分类建议「贷款还款」），负债端取 `remaining_principal`（手动维护，默认等于
principal，用户还款后编辑），自动联动见 §13.3 定案。

### 4.4 `finance.investments`（2C-2）

| 列 | 类型 | 说明 |
| -- | -- | -- |
| id / household_id | UUID | |
| name | VARCHAR(100) NOT NULL | |
| investment_type | VARCHAR(20) CHECK IN ('fixed','daily','fund','cash','stock','bond','other') | |
| account_id | UUID NULL FK core.accounts | 持仓所在 investment 账户；本金经转账入该账户 |
| principal | Numeric(24,8) NOT NULL CHECK (>= 0) | 累计投入本金（建仓转账之和） |
| current_value | Numeric(24,8) NOT NULL CHECK (>= 0) | 当前估值（用户/导入更新） |
| currency | CHAR(3) FK | |
| annual_rate | Numeric(12,8) NULL | 预期/约定年化 |
| start_date | DATE NOT NULL | |
| end_date | DATE NULL | 到期日；NULL = 无期限 |
| liquidity | VARCHAR(10) NULL CHECK（同账户枚举） | |
| status | VARCHAR(20) CHECK IN ('active','redeemed') | matured 为查询期派生态，不落库（§13.4 定案） |
| realized_pnl | Numeric(24,8) NULL | 赎回时落定的已实现损益 |
| pre_redeem_value | Numeric(24,8) NULL | 赎回前的 current_value 快照，供冲正回滚（§4.6） |
| remark | VARCHAR(500) | |

约束：`account_id` 指向的账户必须 `account_type = 'investment'`、同 household、
同币种（Service 校验）；`status='redeemed'` 时 `current_value` 冻结为 0 并要求
`realized_pnl IS NOT NULL`。

术语：`account_id` 非空的投资称 **managed**（本金经转账进入投资账户，受 invariant
约束）；`account_id` 为空称 **unmanaged**（纯登记，本金从未进入账户体系）。
两类投资在净资产公式中口径不同（§5.2）。

字段不可变性：managed 投资的 `principal` / `account_id` / `currency` 创建后**不可
PUT 修改**（会破坏 §4.6 关联与 §5.2 invariant）；unmanaged 的 `principal` 可改
（写审计）。`current_value` 的唯一修改入口是 `PUT /investments/{id}/value`，
通用 `PUT /investments/{id}` 仅收窄为元数据（name/type/dates/liquidity/remark/
annual_rate）。

### 4.5 `finance.investment_tags` / `finance.investment_tag_links`（2C-2）

tags：`id, household_id, name VARCHAR(50), color CHAR(7) NULL`，
`UNIQUE (household_id, name)`。links：`investment_id, tag_id` 复合 PK。
删除被引用的 tag 返回 `TAG_IN_USE`（不做级联）。

### 4.6 `finance.investment_transfers`（2C-2）

投资与入金/赎回转账的**强制关联表**（二审新增，没有它则冲正联动不可实现）：

| 列 | 类型 | 说明 |
| -- | -- | -- |
| investment_id | UUID FK finance.investments | |
| transfer_id | UUID FK finance.transfers | |
| direction | VARCHAR(10) CHECK IN ('fund','redeem') | 入金 / 赎回回笼 |

约束：复合 PK `(investment_id, transfer_id)`；`transfer_id` 唯一（一笔转账只服务
一个投资动作）；transfer 与 investment 同 household（Service 校验）。

冲正联动（与 2E 冲正机制咬合，Service 层在 `reverse_transfer` 同事务执行）：

- **冲正入金转账**（direction=fund 且未冲正）：等额调减
  `investment.principal`；调减后 `< 0` 则拒绝冲正（409
  `TRANSFER_LINKED_TO_INVESTMENT`，提示先处理投资）。
- **冲正赎回转账**（direction=redeem）：回滚 `status → active`、清零
  `realized_pnl`、恢复 `current_value`（redeem 时留存的 pre-redeem 快照值，
  存于投资行 `remark` 之外的结构化列 `pre_redeem_value Numeric NULL`）；
  同事务冲正随行衍生 pnl 流水（复用既有 reverse 机制）。
- 投资侧衍生 pnl 流水带 `transfer_id` 关联（复用手续费模式），随转账冲正。

### 4.7 `finance.net_worth_snapshots`（2C-1）

| 列 | 类型 | 说明 |
| -- | -- | -- |
| id / household_id | UUID | |
| snapshot_date | DATE NOT NULL | 家庭时区自然日 |
| base_currency | CHAR(3) | 快照时家庭本位币 |
| total_cash / total_invested / total_liabilities / net_worth | Numeric(24,8) | 本位币折算值；total_invested 覆盖 `status≠redeemed`（含 matured）；net_worth 按 §5.2 唯一公式，分桶仅展示 |
| unrealized_pnl | Numeric(24,8) | Σ_managed, status≠redeemed (current_value − principal)，展示用 |
| unmapped_cash | Numeric(24,8) | Σ投资账户余额 − Σ_managed, status≠redeemed principal（可负，诊断） |
| daily_interest_income / daily_interest_expense | Numeric(24,8) | 见 §5.4 |
| currency_breakdown | JSONB | 分币种明细：`[{currency, cash, invested, liabilities, fx_rate}]` |
| fx_rates_used | JSONB | 快照实际采用的汇率（可追溯） |
| created_at / updated_at | timestamptz | |

约束：`UNIQUE (household_id, snapshot_date)`（upsert 语义）；按 household+日期索引。

## 5. 关键规则

### 5.1 credit 账户与负余额（2C-1）

- 负余额校验改为按账户类型分派：抽取公共守卫 `ensure_withdrawable(account,
  currency, decrease)`，**仅当 `account_type NOT IN ('credit',)` 时拒绝**；
  credit 账户放行。
- 守卫必须替换**全部**现有校验点（二审核对共 5 类）：
  transactions 创建/确认支出、冲正收入（`transactions/service.py`）；
  transfers 创建/确认/冲正（`transfers/service.py`）；
  **imports 确认**（`imports/service.py`）—— 信用卡账单导入是 credit 账户的
  头号用例，漏改则导入路径仍被拒。
- credit 账户开账：`opening_balance` 允许负数（现有机制已支持）。
- `credit_limit` 软校验：透支后 `abs(负余额) > credit_limit` 返回
  `CREDIT_LIMIT_EXCEEDED`（409）；`credit_limit IS NULL` 不校验（存量账户天然
  关闭）。校验点与负余额守卫同点位复用。
- 统计口径：credit 账户负余额计入**负债端**（`total_liabilities` 含信用卡欠款），
  正余额（溢缴款）计入现金。现有 `/statistics/account-balances` 与 `overview` 的
  分币种合计将混入负余额 —— 分币种明细照常返回（含负值），合计处标注含 credit
  欠款；不做静默改动。

### 5.2 投资入金与赎回的会计闭环（2C-2，核心设计）

本金全部走**内部转账**（复用 2E transfers），保证余额可由流水推导。
**币种定案**（二审 H6）：`principal` / `current_value` / `realized_pnl` 一律
`investment.currency`；入金转账 `to_currency = investment.currency`；赎回首版要求
`to_account` 与投资同币种（跨币种赎回随需求再放开）。

1. **建仓 / 追加**：`POST /investments`（建仓）与 `POST /investments/{id}/fund`
   （追加，二审 H5 补充）均接受可选 `fund_transfer: {from_account_id,
   from_amount, exchange_rate?}` —— 服务端同事务创建 `confirmed` 转账
   （现金账户 → 投资账户，to 侧币种 = 投资 currency）、写 `investment_transfers
   (direction='fund')`、`principal += to_amount`。不传则只登记（unmanaged 或
   用户自行转账）。
2. **估值更新**：`PUT /investments/{id}/value {current_value}` 只改估值字段，
   不产生流水（浮盈不计收支）。该端点是估值唯一入口。
3. **赎回**（全额行为，不支持部分赎回）：`POST /investments/{id}/redeem
   {to_account_id, to_amount}`，`to_amount > 0` 且币种 = 投资 currency
   （`to_amount < principal` 即实现亏损）。同事务**固定顺序**（二审 C1 定案）：
   1. 先在**投资账户**落衍生 pnl 流水：`realized_pnl = to_amount − principal`，
      `> 0` 生成衍生收入（分类「投资收益」）、`< 0` 生成衍生支出（「投资亏损」），
      `source='system'`、`transfer_id` 关联（复用手续费模式）——此时投资账户
      余额 = principal + pnl = to_amount，后续转账余额校验自然通过；
   2. 再生成投资账户 → 现金账户的 `confirmed` 转账（回笼 `to_amount`），写
      `investment_transfers (direction='redeem')`；
   3. 置 `status='redeemed'`、落 `realized_pnl`、`current_value=0`、留存
      `pre_redeem_value`（供冲正回滚，§4.6）。
   账面验证：投资账户净变动 = −principal、现金账户 +to_amount、收支统计
   +pnl —— 自洽，且与手续费闭环真正同构（衍生流水先落账、再过转账校验）。
4. **到期**：查询期判定 `end_date <= today(household.timezone)` 的 active 投资
   为「已到期」（派生状态，不物化；redeem 时才落库状态），**计入净资产**
   （见下方公式，二审 M9：panorama 把 matured 排除出总资产是照搬来的瑕疵，
   本设计不沿用），仅从「理财中」分桶移入「已到期」提醒视图；不自动改余额。

**净资产公式（唯一口径，二审 C2 定案；§13.1 原「Σprincipal 为准」建议被否决，
因其会把投资账户内未映射现金丢出净资产）**：

```
net_worth = Σ非investment账户 max(balance, 0)          # 现金（credit 负余额除外）
          + Σ投资账户账面余额                            # 含托管本金与账户内现金
          + Σ_managed, status≠redeemed (current_value − principal)   # managed 浮盈（matured 含）
          + Σ_unmanaged, status≠redeemed current_value              # unmanaged 全额
          − Σ active贷款 remaining_principal
          − Σ credit账户负余额绝对值
```

- 账户余额是 spec §5.4 的唯一事实来源：即使投资账户余额与 Σprincipal 漂移
  （账户内有未映射现金 / 用户自行转账），现金不漏计、浮盈不双计。
- `unrealized_pnl`（快照字段）= Σ_managed, status≠redeemed (current_value −
  principal)，仅展示用。
- 诊断字段 `unmapped_cash` = Σ投资账户余额 − Σ_managed, status≠redeemed
  principal（不截断负值，负值说明本金未到位）—— /assets/summary 返回，
  UI 提示对账。
- 展示分桶（闲置/理财中/已到期）仅为 UI 聚合口径，不参与净值计算。

### 5.3 汇率折算（2C-1）

- 折算仅用于**余额类总额与快照**；分币种明细始终返回（现状不变）。
- 任一所需币种对缺汇率时：快照写入失败返回 `EXCHANGE_RATE_NOT_FOUND`（带缺口清单），
  总览同理 —— 快照宁可失败不可漏项（可追溯完整性优先）。
- 转账已有的 `base_amount` 固化机制不变；新增投资入金转账同样固化。

### 5.4 日利息（快照字段）

```
daily_interest_income  = Σ账户 max(balance,0)×annual_rate/365 + Σ status≠redeemed 投资 current_value×annual_rate/365
daily_interest_expense = Σ active 贷款 remaining_principal×annual_rate/365
```

`annual_rate IS NULL` 的项跳过；credit 负余额不计负利息；365 恒定分母，
该字段仅为快照记录口径（估算值，不产生流水）。

### 5.5 状态机

- loans：`active → settled`（`POST /loans/{id}/settle`，terminal，允许
  `remaining_principal > 0` 的提前结清并置 0）；不可逆。
- investments：`active → redeemed`（redeem 端点，terminal）；`matured` 是查询期
  **派生状态**（`end_date <= today AND status='active'`），不物化，redeem 时落库。
  draft 语义不引入（投资登记即生效，与 panorama 一致）。
- 投资登记删除：`DELETE /investments/{id}` 仅允许 `status='active'` 且**无未冲正的
  关联转账**（经 `investment_transfers` 判定，§4.6）；有关联则返回
  `INVESTMENT_HAS_TRANSFERS`（409），提示先冲正转账（冲正联动自动调减 principal）。

## 6. API 草案（`/api/v1`，统一 envelope，全部 Bearer）

### 6.1 汇率（2C-1）

- `GET /exchange-rates?base=&quote=&date_from=&date_to=` （分页）
- `POST /exchange-rates` `{base_currency, quote_currency, rate, rate_date}`
- `GET /exchange-rates/latest?base=&quote=`（含反向换算来源标记）
- `DELETE /exchange-rates/{id}`

### 6.2 账户（扩展现有端点，2C-1）

`POST/PUT /accounts` 增加可选字段 `annual_rate` / `liquidity` / `credit_limit`；
响应同步带出。负余额规则变化见 §5.1，无新端点。

### 6.3 投资（2C-2）

- `GET /investments?status=active|matured|redeemed&type=&tag_id=&account_id=`
- `POST /investments`（含可选 `fund_transfer`、`tag_ids`）
- `POST /investments/{id}/fund` `{fund_transfer}` —— 追加入金（二审 H5 补充）
- `GET/PUT/DELETE /investments/{id}`（PUT 仅元数据与 unmanaged principal，
  §4.4；DELETE 规则见 §5.5）
- `PUT /investments/{id}/value` —— 估值唯一入口
- `PUT /investments/{id}/tags` `{tag_ids: []}`（全量替换）
- `POST /investments/{id}/redeem`
- `GET/POST /investment-tags`、`DELETE /investment-tags/{id}`

配套约束：`PUT /accounts/{id}` 在账户**已有流水**后禁改 `account_type`
（现有服务允许，需收窄，二审 H8）；`credit_limit` / `annual_rate` / `liquidity`
随时可改。

### 6.4 贷款（2C-3）

- `GET /loans?status=`
- `POST /loans`
- `GET/PUT/DELETE /loans/{id}`（DELETE 仅 active 且无关联还款流水）
- `POST /loans/{id}/settle` `{settled_date}`

### 6.5 总览与快照（2C-1）

- `GET /assets/summary` —— 实时计算（同请求内汇率取 latest）：净资产（§5.2 公式）、
  展示分桶（闲置/理财中/已到期）、负债、日利息、分币种明细、`unmapped_cash`
  诊断值、已到期投资列表。停用账户照常计入并带 `inactive_count` 标记。
- `POST /assets/snapshots` —— 触发**当日**（家庭时区）快照 upsert；
  不接受历史日期补录（panorama 允许补录但写入的是当前值，趋势失真，不沿用，
  二审 M13）。
- `GET /assets/snapshots?date_from=&date_to=` —— 趋势序列。
- `GET /assets/snapshots/monthly?year=` —— 月度聚合（首末快照净资产差、日利息
  合计、快照天数），复用 panorama 的汇总口径。

## 7. 与现有体系的联动

- **收支统计不变**：投资入金/赎回本金 = 转账（不计收支）；赎回损益 = 衍生收支
  （计收支，`source='system'`，`transfer_id` 关联，随转账冲正）；贷款还款 =
  用户自记支出（计收支）。
- **余额核对**：investment 账户与普通账户一致（流水推导账面余额 + 对账快照），
  `account-balances` 自动包含新账户类型；credit 负余额在分币种明细照常呈现，
  合计语义见 §5.1。
- **内置分类兜底**：「投资收益」「投资亏损」「贷款还款」三个分类对 2A 之后
  初始化的存量家庭不存在 —— 照抄 `_fee_category` 的运行时兜底模式
  （`transfers/service.py`：缺失时自动创建系统内置分类）+ `defaults.py`
  预填双通道（二审 M10）。
- **审计**：`loan.create/update/settle/delete`、`investment.create/fund/update/
  value/tags/redeem/delete`、`investment_tag.create/delete`、
  `exchange_rate.create/delete`、`net_worth.snapshot.create/update`（upsert 的
  更新分支单列 action）；衍生 pnl 流水另写 `transaction.create` 审计（带
  `investment_id` 上下文）；冲正联动写 `investment.fund_reverse/redeem_reverse`。
  actor 沿用请求上下文。
- **导入**：暂不扩展（§3 非目标）；但 imports 确认路径的负余额守卫必须随 §5.1
  改造（信用卡账单导入用例）。
- **setup 向导**：新列均可空，向导无需变化；新增内置分类进 defaults.py 预填。

## 8. 错误码草案

| 错误码 | HTTP | 触发 |
| -- | -- | -- |
| EXCHANGE_RATE_NOT_FOUND | 400 | 折算/快照缺汇率（带缺口清单） |
| EXCHANGE_RATE_VALUE_INVALID | 422 | rate ≤ 0 / base=quote（**不占用** transactions 已有的 EXCHANGE_RATE_INVALID=400） |
| EXCHANGE_RATE_DUPLICATE | 409 | 同 household+币对+日期重复录入 |
| CREDIT_LIMIT_EXCEEDED | 409 | credit 透支超额度 |
| ACCOUNT_TYPE_IMMUTABLE | 409 | 已有流水/转账的账户禁改 `account_type`（实施新增，承载 §6.3 H8 收窄） |
| LOAN_NOT_FOUND / NOT_EDITABLE / NOT_DELETABLE / ALREADY_SETTLED | 404/409/409/409 | |
| INVESTMENT_NOT_FOUND / NOT_EDITABLE / NOT_DELETABLE / ALREADY_REDEEMED | 404/409/409/409 | |
| INVESTMENT_ACCOUNT_REQUIRED | 409 | fund/redeem 作用于 unmanaged 投资（实施新增：无托管账户） |
| HOLDING_NOT_FOUND / DUPLICATE | 404/409 | 持股不存在 / 仓位重复（实施新增） |
| HOLDING_NOT_SUPPORTED / CURRENCY_MISMATCH | 422/422 | 非 stock/fund 投资 / 市场币种与投资币种不符（实施新增） |
| QUOTE_PROVIDER_ERROR | 502 | 行情源失败/返回异常（details 带失败代码清单；实施新增） |
| TAG_DUPLICATE | 409 | 同家庭标签重名（实施新增） |
| INVESTMENT_HAS_TRANSFERS | 409 | 删除时存在未冲正关联转账 |
| INVESTMENT_ACCOUNT_INVALID | 422 | account_id 非投资账户/跨家庭/币种不符 |
| REDEEM_AMOUNT_INVALID | 422 | to_amount ≤ 0 或币种不符 |
| TAG_IN_USE / TAG_NOT_FOUND | 409/404 | |
| LOAN_REMAINING_INVALID | 422 | PUT 时 remaining_principal > principal（实施新增） |
| TRANSFER_LINKED_TO_INVESTMENT | 409 | 冲正入金转账会使 principal < 0 |
| SNAPSHOT_DATE_INVALID | 422 | 补录历史日期 |

复用：`ACCOUNT_INACTIVE`、`INSUFFICIENT_BALANCE`、`BASE_EXCHANGE_RATE_REQUIRED`。

## 9. Web UI 规划（2C-4）

- 新增「资产负债」页：总览卡片（净资产/三分资产/负债/日利息）、净资产趋势
  （AreaChart，快照序列）、资产配置（PieChart，按 investment_type 与 tag 双维度）、
  贷款列表（含 due_day 提醒）、投资列表（active/matured/redeemed 分组）。
- 总览页（dashboard）增加净资产卡片与「记录今日快照」按钮。
- 统计页引入 Recharts（月度 Bar 已可顺带升级）。
- 「指南」页：概念说明（净资产口径、为何入金是转账、到期 ≠ 赎回）——
  参考 panorama guide 的最佳实践文案结构。
- 到期提醒：总览页「已到期投资」「7 日内到期贷款还款日」列表。

## 10. 测试计划

- 单元/集成（pytest，沿用 truncate + setup 夹具）：汇率 CRUD 与 latest/反向取数/
  重复日期 409；credit 负余额与额度校验（**覆盖全部 5 类守卫点**：transactions
  创建/确认/冲正、transfers 创建/确认/冲正、imports 确认）；投资建仓与追加入金
  （fund_transfer 同事务性：转账失败则登记回滚）；估值更新；**盈利赎回必须通过**
  （回归 C1：衍生 pnl 先落账再转账，余额校验放行）且账面净变动断言
  （投资账户 −principal、现金 +to_amount、收支 +pnl）；亏损赎回；到期判定与
  matured 计入净资产（回归 M9）；冲正联动（入金冲正调减 principal、赎回冲正
  回滚状态，回归 C3）；贷款 CRUD/settle/提前结清；快照 upsert/趋势/月度聚合/
  汇率缺失失败（带缺口清单）/拒绝历史日期；净资产公式防重复计算回归
  （managed/unmanaged/未映射现金/matured 四象限）；审计断言；错误码映射。
- 统计回归：现有 108 项全量通过；收支口径零变化（入金/赎回本金不出现）。
- 覆盖率 ≥ 80%（CI 门槛不变）；mypy strict / ruff。

## 11. 实施拆分

| 子阶段 | 内容 | 依赖 |
| -- | -- | -- |
| 2C-1 | exchange_rates、accounts 扩展 + credit/透支、净资产快照与 /assets/summary（总额折算） | 无（2A 已就绪） |
| 2C-2 | investments + tags + 入金转账 + 赎回闭环 + 到期视图 | 2C-1 |
| 2C-3 | loans + settle + 负债端并入快照/总览 + 日利息 | 2C-1 |
| 2C-4 | Web：资产负债页、趋势/配置图表、到期提醒、指南页 | 2C-1（图表可先行），2C-2/3（列表） |

每子阶段一次迁移 + 全量测试 + roadmap 记录（沿用 Task 00X 流程）。
2C-1 可独立发布价值（总额折算 + 快照对存量数据立即生效）。

## 12. 风险

- ~~净资产口径歧义~~（已在 v2 定案，§5.2 唯一公式 + `unmapped_cash` 诊断）。
- 快照依赖汇率补全：多币种家庭冷启动时若缺汇率，快照持续失败 ——
  提示引导补录（/assets/summary 返回缺口清单）。
- credit 透支放开后，Phase 1 的负余额测试需系统性改写（按账户类型参数化），
  且守卫点分散在 4 个 service —— 用公共守卫收敛，防止后续新增校验点漏改。
- 冲正联动（§4.6）把 transfers 冲正路径与投资状态耦合：联动逻辑必须与
  `reverse_transfer` 同事务，任何一侧遗漏都会造成 invariant 漂移 ——
  靠 `unmapped_cash` 诊断 + 专项回归兜底。
- valuation 历史不落库（仅快照聚合）—— 个基估值曲线不可回溯（接受）。
- 贷款 remaining_principal 手动维护可能与实际还款漂移（§13.3）。

## 13. 评审定案记录（v2，2026-11-12 独立架构二审）

1. **在投本金口径**：定案 §5.2 唯一公式（账户余额 + managed 浮盈 + unmanaged
   全额）。否决 v1 的「Σprincipal 为准、差额仅提醒」——该方案会把投资账户内
   未映射现金丢出净资产；改为 `unmapped_cash` 诊断字段。
2. **投资登记撤销**：定案「先冲正关联转账才可 DELETE」，并以 `investment_transfers`
   关联表（§4.6）+ 冲正联动（入金冲正自动调减 principal）使规则可实现。
3. **贷款剩余本金联动**：首版手动维护 `remaining_principal`；`settle` 允许
   `remaining_principal > 0` 的提前结清（置 0）。还款流水自动联动留待 2C-3
   上线后按使用情况评估。
4. **matured 物化**：查询期派生判定（`end_date <= today AND status='active'`），
   不引入定时任务；redeem 时落库终态。
5. **credit_limit 软校验**：默认开启；`credit_limit IS NULL` 即关闭（存量账户
   天然关闭）；校验点与负余额守卫统一复用（§5.1，覆盖导入路径）。

## 14. 规格回写

spec §10 的 2C 范围经本设计实质调整（证券交易/股息/持仓明细/market schema 暂缓、
新增 investment/credit 账户类型与 exchange_rates 前移为 2C-1），按附录 A 惯例
在 specification.md 补 v1.4 修订记录，避免规格与实现契约分叉（二审 M15）。

## 15. 2C-2 实施增补（2026-11-14）

用户需求驱动的范围调整（原 §2.2 暂缓项部分提前）：

1. **持股快照提前**：新增 `finance.holdings`（市场/代码/数量/**成本单价**），
   仅挂 stock/fund 投资；市场→币种绑定 SH/SZ→CNY、HK→HKD、US→USD。
   成本单价为展示/对账维度，**不进 §5.2 净资产公式**；加仓/减仓与移动
   加权成本核算仍暂缓（预留 `finance.trades`，holdings 表前向兼容）。
2. **行情估值提前（按需，非后台）**：新增 market 模块与
   `GET /market/quotes`、`POST /investments/{id}/refresh-value`；腾讯免
   key 行情（SH/SZ/HK/US）+ Provider 抽象 + FakeProvider（测试离线）；
   30s 缓存 / 5s 超时 / 可选代理；刷新自动写入 current_value 并带逐股
   breakdown 审计。**不做后台定时拉价**（沿用"无明确运维需求不引入后台
   组件"原则）。
3. 股票推荐路径为 **unmanaged 独立快照**（不关联账户、不产生转账），
   与托管型并存；赎回/入金要求 managed（`INVESTMENT_ACCOUNT_REQUIRED`）。
4. 冲正联动补充定案：投资已 redeemed 时冲正入金转账同样返回
   `TRANSFER_LINKED_TO_INVESTMENT`（先冲正赎回）；`reverse_transfer`
   的衍生流水冲正泛化为全部 confirmed 衍生行（覆盖赎回盈利的收入冲正）。
