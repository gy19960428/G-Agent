# WMS Backend

Flask API 后端基线。本机开发默认 SQLite，服务器路线预留 Linux + Docker + PostgreSQL + HTTPS。

## 本机运行

```bash
cd wms_fullstack/backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
flask --app run.py init-db
python run.py
```

健康检查：

```bash
curl http://127.0.0.1:5000/api/health
```

## 测试

```bash
cd wms_fullstack/backend
. .venv/bin/activate
pytest
```

## 已实现 API

- `GET /api/health`
- `GET /api/dashboard`
- `GET /api/products`
- `POST /api/products`
- `GET /api/orders`
- `POST /api/orders`
- `POST /api/produce`
- `GET /api/boxes`
- `GET /api/boxes/<box_no>`
- `POST /api/ship`
- `POST /api/returns`
- `GET /api/stock-moves.csv`
