# WMS 服务器版架构决策

## 背景

当前已有 `wms_mvp` 单体 Flask + SQLite 原型，已经覆盖注塑件生产装箱、箱号库存、标签打印、扫码/手输出货、退回复检、流水导出等核心流程。

新目标是建设可部署到公司服务器的版本：后端 API、Web 前端、微信小程序三端分离；先本机开发验收，验收后部署到公司服务器。

## 第一版推荐架构

```text
wms_fullstack/
  backend/       后端 API 服务
  frontend/      Web 管理后台
  miniprogram/   微信小程序端
  docs/          架构、部署、验收、迁移、备份文档
```

## 技术选择

### 后端

第一阶段建议使用 Flask API 化，而不是立刻换 FastAPI。

理由：

- 现有 MVP 已经是 Flask，业务规则可以快速迁移。
- 公司场景规模不大，Flask 足够支撑第一版。
- 可以先把接口、权限、数据库、部署做稳，避免同时重写框架和业务。
- 后续如果并发、文档、类型约束需求增强，再迁 FastAPI 成本可控。

后端第一版需要补齐：

- 登录/账号/角色权限。
- 产品、订单、生产装箱、箱号库存、出货、退回、统计、导出 API。
- 统一 JSON 响应和错误码。
- 数据库初始化、迁移、备份脚本。
- 部署启动脚本和日志。

### 数据库

本机开发期可以继续 SQLite。

服务器验收期有两种路线：

1. 保守上线：SQLite + 文件级自动备份。
2. 正式上线：PostgreSQL 或 MySQL。

如果公司多人同时操作较多，建议正式服务器直接用 PostgreSQL；如果只是少量电脑和小程序扫码，SQLite 可以先跑，但必须做自动备份。

### Web 前端

建议 Vue 3 + Vite + Element Plus。

理由：

- 后台系统表格、表单、弹窗、分页、筛选都成熟。
- 打印标签页面可以单独做浏览器打印样式。
- 后端只提供 API，未来小程序和 Web 共用接口。

当前本机环境没有检测到 Node/npm，可使用 Docker 或安装 Node LTS 后开发前端。

### 微信小程序

沿用已有原生小程序代码，迁移到 `wms_fullstack/miniprogram` 后扩展。

第一版小程序职责：

- 扫码查询箱号。
- 确认出货。
- 手输箱号兜底。
- 后续可扩展库存查询、生产确认、退回复检。

扫码使用微信官方 `wx.scanCode`，不需要第三方扫码库。

## 业务模块边界

### 管理后台 Web

- 产品档案。
- 年度/批次订单。
- 生产装箱。
- 标签打印。
- 箱号库存。
- 出货记录。
- 退回复检。
- 统计看板。
- CSV/Excel 导出。
- 账号权限。

### 小程序

- 扫码出货。
- 箱号查询。
- 手输箱号出货。
- 移动端库存查询。

### 后端 API

- 负责所有业务校验和状态流转。
- Web 和小程序都不直接操作数据库。

## 状态流转建议

箱号状态第一版保留三类：

```text
in_stock -> shipped -> returned -> in_stock/shipped
```

后续如果质检流程更细，可以扩展为：

```text
produced -> qc_passed -> in_stock -> shipped -> returned -> recheck -> in_stock/shipped/scrapped
```

## 本机开发方式

第一阶段推荐：

- 后端运行在 `http://127.0.0.1:5000`。
- Web 前端运行在 `http://127.0.0.1:5173`，通过代理访问后端 API。
- 小程序开发者工具访问本机局域网地址，例如 `http://192.168.x.x:5000`。

## 服务器部署预案

需要根据公司服务器系统最终定：

- Linux + Docker：优先 Docker Compose，部署最规整。
- Linux 无 Docker：systemd + Nginx + Python venv。
- Windows Server：NSSM/计划任务 + Nginx/Caddy + Python venv。

小程序若要正式发布，通常还需要 HTTPS 域名、备案、微信后台配置合法域名。

## 下一步

1. 确认服务器系统、是否 Docker、是否外网访问、小程序是否正式发布。
2. 新建 `backend` API 基线，迁移现有表结构和核心业务。
3. 新建 `frontend` 管理后台基线。
4. 迁移 `miniprogram` 并改成统一 API 配置。
