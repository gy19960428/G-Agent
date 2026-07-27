# WMS 服务器部署验收清单

本清单用于公司服务器正式上线前验收。默认路线：Linux + Docker + PostgreSQL + Nginx/Caddy HTTPS。

## 服务器基础项

- 操作系统：Linux x86_64，建议 Ubuntu Server LTS 或 Debian Stable。
- Docker 与 Docker Compose 可用：`docker version`、`docker compose version`。
- 服务器时间同步正常：`timedatectl` 显示 NTP active。
- 防火墙只开放必要端口：`80/tcp`、`443/tcp`、必要时 `22/tcp`。
- 后端容器端口只绑定本机：`127.0.0.1:5000:5000`，不直接暴露公网。

## 域名与 HTTPS

- 域名解析到服务器公网 IP。
- HTTPS 证书已签发并自动续期。
- 浏览器访问 `https://你的域名/` 能打开 Web 管理后台。
- `curl https://你的域名/api/health` 返回 `ok: true`。
- 小程序后台已配置 request 合法域名：`https://你的域名`。

## 数据库与备份

- `.env` 已设置强密码：`POSTGRES_PASSWORD`、`WMS_SECRET_KEY`。
- PostgreSQL 容器健康：`docker compose ps` 显示 healthy。
- 已执行初始化：`docker compose exec backend flask --app run.py init-db`。
- 已执行一次备份：`./backup_postgres.sh`。
- 已在测试环境执行一次恢复演练：`./restore_postgres.sh backups/xxx.sql.gz`。
- 备份目录定期复制到服务器外部位置，例如 NAS、移动硬盘或云备份桶。

## 业务验收

- 新增产品成功。
- 新增订单成功。
- 生产装箱成功，生成箱号。
- Web 能查询库存箱、已出货箱、退回箱。
- 小程序真机扫码能查询箱号。
- 小程序确认出货后，Web 库存与出货数量同步变化。
- 小程序退回复检后，Web 状态同步为退回。
- CSV 流水导出可下载并用 Excel 打开。

## 上线前必须确认

- 已把小程序 `app.js` 中 `apiBase` 改成 `https://你的域名/api`。
- 已把 Web 前端默认 API 地址改成正式域名，或现场保存正式地址。
- 标签打印纸张尺寸、边距、条码可扫性已现场确认。
- 管理员知道备份文件位置和恢复步骤。
