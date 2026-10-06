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

## EdgeOne CDN 缓存刷新

前端文件修改并同步到服务目录后，可以调用腾讯云 EdgeOne API 主动刷新缓存：

```bash
cd wms_fullstack/deploy
cp .env.example .env
# 在 .env 中填写 TENCENTCLOUD_SECRET_ID、TENCENTCLOUD_SECRET_KEY、EDGEONE_ZONE_ID
./purge_edgeone_cache.sh
```

默认刷新目标：

- `https://wms.sky-clemon.top/`
- `https://wms.sky-clemon.top/index.html`
- `https://wms.sky-clemon.top/styles.css`
- `https://wms.sky-clemon.top/app.js`

如需修改刷新范围，调整 `.env` 中的 `EDGEONE_PURGE_TARGETS`。真实密钥只写入本机 `deploy/.env`，不要提交到 Git。

## 备份与恢复

```bash
chmod +x backup_postgres.sh restore_postgres.sh purge_edgeone_cache.sh
./backup_postgres.sh
./restore_postgres.sh backups/wms_xxx.sql.gz
```

恢复命令会覆盖目标库，正式环境恢复前先确认备份文件和目标数据库。

## 验收文档

- 服务器上线前清单：`../docs/deployment_acceptance.md`
- 本机 Docker/PostgreSQL 演练：`../docs/deployment_drill.md`
