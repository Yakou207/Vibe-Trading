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

### 已知问题：容器内 DNS

colima 默认把容器 DNS 指向 8.8.8.8，在内地网络下不可达，构建会报
`Temporary failure resolving`。修复（本机 2026-07-22 已执行过；`colima delete` 后需重做）：

```bash
colima ssh -- sh -c 'sudo mkdir -p /etc/docker; printf "{\"dns\": [\"223.5.5.5\", \"114.114.114.114\"]}\n" | sudo tee /etc/docker/daemon.json; sudo systemctl restart docker'
```

## 构建镜像

先把 boost 1.80.0 源码包放进本目录（约 138MB，不入 git；国内网络直连 boost 官网极慢，
可走本机代理，如 Shadowrocket 的 127.0.0.1:1082）：

```bash
curl -C - -x http://127.0.0.1:1082 -o docker/xtp/boost_1_80_0.tar.gz https://archives.boost.io/release/1.80.0/source/boost_1_80_0.tar.gz
```

然后构建：

```bash
docker build --platform linux/amd64 -t xtp-bridge docker/xtp
```

注意：官方 `.so` 是 CentOS 7（旧 C++ ABI）编译的，Dockerfile 里用
`_GLIBCXX_USE_CXX11_ABI=0` 编 boost 才能匹配；改动这里会导致所有 API 调用报
`ArgumentError` 类型不匹配。

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

## 已知问题（2026-07-27 实测）

1. **进程退出可能挂死**：成功登录并收到回调后，进程结束阶段（含 `os._exit`）在 Rosetta
   模拟下可能挂住；`api.logout()` 必挂（断线回调 GIL 死锁），已在脚本中移除。约定：所有
   桥接脚本以**写出结果文件**（如 `broker_state.json`）为成功信号，外层调用方设超时并
   `docker rm -f` 清理容器；进程退出码不作为成功依据。
2. **client_id 会话独占**：同一资金账号同一 `client_id` 的旧会话未过期时，新登录返回 0
   （失败）。容器被强杀后服务端需要一段时间才释放会话。桥接脚本应对登录失败做等待重试，
   或按运行日选用不同 `client_id`。
