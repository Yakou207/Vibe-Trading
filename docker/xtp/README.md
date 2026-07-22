# XTP 仿真容器环境

XTP 官方 Python 封装只提供 CentOS7 + Python 3.9 的 x86_64 预编译 `.so`，macOS 无原生版本，
因此在 Mac 上统一用 linux/amd64 容器运行 XTP 相关脚本。仿真环境部署在阿里云、互联网直连，
容器内可以直接访问。

## 一次性准备（Apple Silicon）

任选一个容器运行时（三选一）：

- Docker Desktop 或 OrbStack：图形安装，自带 Rosetta 加速 amd64 镜像；
- colima（命令行，免 GUI）：

```bash
brew install colima docker && colima start --vm-type vz --vz-rosetta
```

## 构建镜像

```bash
docker build --platform linux/amd64 -t xtp-bridge docker/xtp
```

构建结束时会自动做 `import vnxtptrader, vnxtpquote` 冒烟（镜像默认 CMD）：

```bash
docker run --rm xtp-bridge
```

## 连通性冒烟（需要测试账号邮件里的信息）

```bash
docker run --rm -v "$PWD:/workspace" \
  -e XTP_TRADER_IP=<邮件里的交易服务器IP> \
  -e XTP_TRADER_PORT=<端口> \
  -e XTP_USER=<资金账号> \
  -e XTP_PASSWORD=<密码> \
  -e XTP_SOFTWARE_KEY=<邮件里的软件Key> \
  xtp-bridge python scripts/check_xtp_env.py
```

凭据只通过环境变量传入，不写进任何文件或提交记录。
