# 一键启动脚本

Windows 下可直接双击根目录 `start.bat` 启动网页端。脚本会自动完成以下步骤：

```text
1. 进入项目目录
2. 创建或复用 `.venv` 本地 Python 环境
3. 安装 `requirements.txt` 依赖
4. 打开浏览器访问 `http://127.0.0.1:8080`
5. 启动 `web.py`
```

默认监听 `127.0.0.1:8080`。如需改监听地址或端口，可在启动前设置环境变量：

```bat
set PAYPAL_WEB_HOST=0.0.0.0
set PAYPAL_WEB_PORT=8080
start.bat
```

停止服务时，在启动窗口按 `Ctrl+C`。
