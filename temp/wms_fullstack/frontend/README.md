# WMS Frontend

当前本机环境未安装 Node/npm，因此第一版 Web 管理后台采用免构建静态前端：`index.html` + `styles.css` + `app.js`。

## 本机运行

先启动后端：

```bash
cd wms_fullstack/backend
. .venv/bin/activate
flask --app run.py init-db
python3 run.py
```

再启动前端静态服务：

```bash
cd wms_fullstack/frontend
python3 -m http.server 5173
```

浏览器打开：

```text
http://127.0.0.1:5173
```

如从其他电脑访问，把 `app.js` 里的 `API_BASE` 改为服务器或本机局域网地址。

## 后续升级

服务器验收前可继续使用静态前端；如果后续安装 Node LTS，再升级为 Vue 3 + Vite + Element Plus。
