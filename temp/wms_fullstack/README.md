# WMS Fullstack

服务器版 WMS 项目，目标是后端 API、Web 管理后台、微信小程序三端分离。

当前处于本机开发验收阶段，现有业务基线来自 `../wms_mvp`。

## 目录

```text
backend/       后端 API 服务
frontend/      Web 管理后台
miniprogram/   微信小程序端
docs/          架构、部署、验收、迁移、备份文档
```

## 当前决策

- 后端第一阶段基于 Flask API 化，降低从 MVP 迁移的风险。
- 数据库开发期先 SQLite，服务器期根据并发和维护能力决定 SQLite/PostgreSQL。
- Web 前端建议 Vue 3 + Vite + Element Plus。
- 小程序沿用原生微信小程序并扩展。

详细说明见 `docs/architecture.md`。
