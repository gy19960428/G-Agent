# WMS 本机部署演练

本演练用于在真正上公司服务器前，确认 Docker Compose、PostgreSQL、初始化、备份恢复流程可跑通。

## 1. 准备环境

```bash
cd wms_fullstack/deploy
cp .env.example .env
```

编辑 `.env`，至少修改：

```text
POSTGRES_PASSWORD=replace-with-strong-password
WMS_SECRET_KEY=replace-with-random-secret
WMS_CORS_ORIGINS=http://127.0.0.1:5173,https://wms.example.com,https://servicewechat.com
```

## 2. 启动服务

```bash
docker compose up -d --build
docker compose ps
```

## 3. 初始化数据库

```bash
docker compose exec backend flask --app run.py init-db
```

## 4. 健康检查

```bash
curl http://127.0.0.1:5000/api/health
```

期望返回 JSON 中包含：

```json
{"ok": true}
```

## 5. 业务烟测

按顺序验证：

1. 创建产品。
2. 创建订单。
3. 生产装箱。
4. 查询箱号。
5. 确认出货。
6. 退回复检。

## 6. 备份与恢复演练

```bash
chmod +x backup_postgres.sh restore_postgres.sh
./backup_postgres.sh
ls -lh backups/
```

恢复演练必须在测试库或全新演练环境执行，避免覆盖正式数据：

```bash
./restore_postgres.sh backups/wms_xxx.sql.gz
```

## 7. 停止演练环境

```bash
docker compose down
```

如果需要删除演练数据库卷：

```bash
docker compose down -v
```
