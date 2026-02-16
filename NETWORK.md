# 网络配置指南

本项目运行在 Hyper-V VM 中，vLLM 服务运行在宿主机 WSL2 里。由于 Hyper-V 外部交换机存在宿主机与 VM 二层隔离的已知问题，需要通过内部交换机建立专用通道。

## 网络拓扑

```
VM (auto-quant)                    宿主机 (ALIVE)
┌──────────────┐                  ┌──────────────────────────┐
│  10.0.0.2    │◄── HostOnly ──► │  10.0.0.1                │
│  (内部网卡)   │    内部交换机     │  (vEthernet HostOnly)    │
│              │                  │         │                │
│  192.168.1.5 │◄── quant ────► │         │ portproxy      │
│  (外部网卡)   │    外部交换机     │         ▼                │
│              │                  │  172.25.200.209:8000     │
│  FastAPI     │                  │  (WSL2 Ubuntu)           │
│  :8100       │                  │  vLLM + OpenCUA-7B       │
└──────────────┘                  └──────────────────────────┘
```

## 访问路径

```
VM FastAPI(:8100) → http://10.0.0.1:8000 → portproxy → WSL2(172.25.200.209:8000) → vLLM
```

## 配置步骤

### 1. 宿主机：创建内部交换机

```powershell
New-VMSwitch -Name "HostOnly" -SwitchType Internal
```

### 2. 宿主机：配置 IP

```powershell
$idx = (Get-NetAdapter -Name "vEthernet (HostOnly)").ifIndex
New-NetIPAddress -InterfaceIndex $idx -IPAddress 10.0.0.1 -PrefixLength 24
```

### 3. 宿主机：给 VM 添加内部网卡

```powershell
Add-VMNetworkAdapter -VMName "auto-quant" -SwitchName "HostOnly"
```

### 4. 宿主机：配置端口转发

将 `10.0.0.1:8000` 转发到 WSL2 的 vLLM 服务：

```powershell
netsh interface portproxy add v4tov4 listenport=8000 listenaddress=10.0.0.1 connectport=8000 connectaddress=172.25.200.209
```

> 注意：WSL2 每次重启后 IP 可能变化，需要更新 `connectaddress`。在 WSL2 中用 `ip addr show eth0 | grep inet` 查看当前 IP。

### 5. 宿主机：防火墙放行

```powershell
New-NetFirewallRule -DisplayName "vLLM HostOnly 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow -Profile Any
```

### 6. VM：配置内部网卡 IP

在 VM 中找到新增的网卡并配置 IP：

```powershell
# 查看网卡列表，找到新增的 Hyper-V Network Adapter
Get-NetAdapter | Format-Table Name, Status, InterfaceIndex, InterfaceDescription

# 给新网卡配 IP（替换 <InterfaceIndex> 为实际值）
New-NetIPAddress -InterfaceIndex <InterfaceIndex> -IPAddress 10.0.0.2 -PrefixLength 24
```

### 7. 验证

```powershell
# VM 中测试
ping 10.0.0.1
curl http://10.0.0.1:8000/v1/models
```

## WSL2 vLLM 启动

vLLM 必须绑定 `0.0.0.0`，否则 portproxy 无法转发：

```bash
vllm serve /path/to/OpenCUA-7B --host 0.0.0.0 --port 8000
```

## 故障排查

| 现象 | 原因 | 解决 |
|------|------|------|
| VM ping 不通 10.0.0.1 | 内部交换机未创建或 IP 未配置 | 重新执行步骤 1-2 |
| ping 通但 HTTP 超时 | portproxy 未配置或 WSL2 IP 变了 | `netsh interface portproxy show all` 检查，更新 WSL2 IP |
| HTTP 连接被拒绝 | vLLM 未启动或绑定了 127.0.0.1 | 确认 vLLM 用 `--host 0.0.0.0` 启动 |
| VM ping 不通 192.168.1.36 | Hyper-V 外部交换机二层隔离（已知问题） | 不要走外部网络，使用内部交换机 |

## 为什么不用外部交换机直连？

Hyper-V 外部交换机将宿主机物理网卡绑定到虚拟交换机后，宿主机的 IP 应迁移到 `vEthernet` 适配器上。但实际环境中该适配器可能只获得 APIPA 地址（169.254.x.x），导致 VM 和宿主机之间二层不通。这是 Hyper-V 的已知问题，使用内部交换机建立专用通道是最可靠的解决方案。
