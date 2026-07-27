# WMS Deploy

默认部署路线：Linux + Docker + PostgreSQL，正式 HTTPS 由 Nginx/Caddy 在外层终止后反代到后端。

## 配置

```bash
cd wms_fullstack/deploy
cp .env.example .env
# 修改 POSTGRES_PASSWORD、WMS_SECRET_KEY、WMS_CORS_ORIGINS
```

## 启动

```bash
docker compose up -d --build
```

初始化数据库：

```bash
docker compose exec backend flask --app run.py init-db
```

健康检查：

```bash
curl http://127.0.0.1:5000/api/health
```

## HTTPS 预留

生产部署时建议：

- 后端容器只绑定 `127.0.0.1:5000`。
- Nginx/Caddy 监听 `443`，配置 HTTPS 证书。
- `/api/` 反代到 `http://127.0.0.1:5000/api/`。
- 前端静态文件由 Nginx/Caddy 直接托管。

Nginx 示例见：`nginx.wms.example.conf`。

## 备份与恢复

```bash
chmod +x backup_postgres.sh restore_postgres.sh
./backup_postgres.sh
./restore_postgres.sh backups/wms_xxx.sql.gz
```

恢复命令会覆盖目标库，正式环境恢复前先确认备份文件和目标数据库。

## 验收文档

- 服务器上线前清单：`../docs/deployment_acceptance.md`
- 本机 Docker/PostgreSQL 演练：`../docs/deployment_drill.md`
