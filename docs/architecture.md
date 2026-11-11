# Architecture

> 详细规格见 [specification.md](specification.md)（v1.3）。本文只描述已实现部分与结构约定。

## 总体

模块化单体（Modular Monolith）：单进程 FastAPI 应用 + 单 PostgreSQL 实例。不拆微服务；NATS / Worker / Grafana 属于第二阶段。

```
Client ──> uvicorn (FastAPI app)
             ├── app/api/health.py      横切路由（/health /ready，envelope 之外）
             ├── app/modules/<domain>/  业务路由（Phase 1.1 起，挂 /api/v1）
             ├── app/core/              配置 / 日志 / DB 会话 / 异常 / 统一响应
             └── SQLAlchemy async engine (asyncpg) ──> PostgreSQL
```

## 模块与 schema 映射

| app/modules/ | PostgreSQL schema | 阶段 |
| -- | -- | -- |
| households / accounts / currencies / balances | core | Phase 1.1 |
| categories / transactions / transfers | finance | Phase 1.1–1.3 |
| audit | system | Phase 1.2 |
| statistics | （跨 schema 只读聚合） | Phase 1.4 |

每个业务模块内部：`router.py`（只做请求/响应/依赖注入）、`schemas.py`（Pydantic）、`service.py`（业务逻辑，事务边界）、`models.py`（ORM）。

## 请求流与统一响应

- 业务端点统一前缀 `/api/v1`（Phase 1.1 起挂载）。
- 成功：`{"success": true, "data": ..., "message": null}`；列表的 `data` 为 `{items, total, page, page_size}`。
- 失败：`{"success": false, "data": null, "message": "...", "error_code": "..."}`，由全局异常处理器产出：
  - `AppError` 及子类 → 业务错误码（4xx）
  - `RequestValidationError` → `VALIDATION_ERROR`（422）
  - Starlette `HTTPException` → 按状态码映射（404→`NOT_FOUND` 等）
  - 未捕获异常 → `INTERNAL_ERROR`（500，细节不外泄）
- `/health`（进程存活）与 `/ready`（`SELECT 1` 数据库探活）是基础设施探针，不走 envelope；compose healthcheck 用 `/ready`。

## 日志

structlog：开发环境 Console 渲染，生产（`APP_ENV=production`）JSON。经 `ProcessorFormatter` 桥接 uvicorn/sqlalchemy 的标准库日志。

## 已知范围（Task 001）

无认证、无业务端点、无业务表（仅 core/finance/system 三个 schema 基线）。第一阶段的完整范围与暂缓项见规格 §0。
