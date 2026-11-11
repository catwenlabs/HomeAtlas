# HomeAtlas

自托管的家庭数据中心。第一阶段：家庭收支管理后端 API（Python 3.12 + FastAPI + PostgreSQL 17 + SQLAlchemy 2.x async + Alembic），模块化单体，Docker Compose 部署。

> 规格说明书：[Specification v1.3（issue #1 评论）](https://github.com/catwenlabs/HomeAtlas/issues/1#issuecomment-6788969821)，本地镜像 `docs/specification.md`。

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
├── docs/              # architecture / database / development-roadmap / specification
└── .github/workflows/ # CI
```

## 文档

- [architecture.md](docs/architecture.md) — 架构与请求流
- [database.md](docs/database.md) — schema 与迁移策略
- [development-roadmap.md](docs/development-roadmap.md) — 阶段计划与当前进度
