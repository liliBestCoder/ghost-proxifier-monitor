# Ghost Proxifier Monitor 监控看板

![License](https://img.shields.io/badge/License-MIT-blue.svg)
![Python Version](https://img.shields.io/badge/Python-3.8%2B-brightgreen.svg)
![Status](https://img.shields.io/badge/Status-Active-success.svg)

**Ghost Proxifier Monitor** 是专门为 **Ghost Proxifier Pro** 客户端项目设计的高性能、轻量级实时数据监控看板与数据采集后台。系统采用纯 Python 无第三方 Web 框架（零依赖标准库 HTTP 服务器 + SQLite3）实现，整合了 **GitHub API** 与 **百度统计 API**，提供客户端软件下载量、GitHub Stars 增长趋势、实时访客 IP、活跃用户数 (DAU) 及访客地理分布可视化大屏。

---

## 🌟 核心功能特性

- 📊 **GitHub 软件指标监控**
  - **Stars 增长追踪**：实时监控 GitHub Star 总数，精准计算 30 分钟 / 24 小时增量变化。
  - **MSI 下载量统计**：自动追踪指定版本（如 `v1.1.5`）及全版本的 Release 安装包下载总量。
- 📈 **百度统计 Web 流量与访客分析**
  - **OAuth 2.0 自动鉴权**：支持百度开放平台 OAuth 换码与 Access Token / Refresh Token 自动无感刷新。
  - **活跃用户 (DAU / 24h 活跃)**：自动统计过去 24 小时与各时段活跃访客趋势。
  - **地理分布与海外分类**：智能识别访客 IP 归属地（省份级别解析与海外流量识别）。
  - **黑名单与数据清洗**：支持配置 IP 黑名单过滤无效攻击流量，保持统计精准度。
- 🖥️ **暗黑极客风可视化大屏 (`web/`)**
  - 现代化 Glassmorphism 玻璃拟态设计，自带实时状态 Pulse Dot 脉冲动画。
  - 基于 Chart.js 动态绘制 24 小时活跃用户曲线图与访客省份/境内外分布图。
  - 内置交互式**配置中心 Modal**，支持前端直接在线修改密钥、API Token 及黑名单并即时生效。
- 🛠️ **配套运维与诊断工具链**
  - **历史数据补全 (`sync_history.py`)**：支持从百度统计 API 增量拉取过去 N 天的历史访客日志补齐至 SQLite3 数据库。
  - **Token 换取助手 (`get_token.py`)**：命令行快速完成百度 OAuth Code 到 Access Token 的兑换。
  - **自检诊断脚本 (`verify_apis.py`)**：一键校验 SQLite 数据库、GitHub API Rate Limit、百度 API 数据解析逻辑。

---

## 🏗️ 目录结构与架构

```
ghost-proxifier-monitor/
├── monitor_server.py      # 主后台服务 (HTTPServer + SQLite3 + 后台轮询线程)
├── get_token.py           # 百度 OAuth 2.0 Authorization Code 兑换 Token 工具
├── sync_history.py        # 百度统计历史访客日志增量同步/补全脚本
├── verify_apis.py         # 系统连通性与 API 接口诊断工具
├── config.json.example    # 配置文件模板
├── web/                   # 前端大屏静态资源
│   ├── index.html         # 主界面 HTML 结构
│   ├── app.css            # 暗黑大屏样式 (Glassmorphism & 响应式)
│   ├── app.js             # 视图渲染、Chart.js 图表交互与 REST API 请求逻辑
│   ├── chart.js            # Chart.js 本地图表渲染库
│   └── fonts/             # 预置字体资源
└── monitor.db             # SQLite3 本地数据库 (启动后自动生成)
```

---

## 🚀 快速开始

### 1. 环境要求
项目后端仅依赖 Python 3.8+ 标准库（`urllib`, `sqlite3`, `threading`, `http.server` 等），零额外第三方 Web 框架依赖。

### 2. 配置文件初始化
复制配置文件模板：
```bash
cp config.json.example config.json
```
在 `config.json` 中按需填写各项配置项：
```json
{
    "github_token": "YOUR_GITHUB_PAT_TOKEN",
    "msi_version": "v1.1.5",
    "baidu_site_id": "YOUR_BAIDU_SITE_ID",
    "baidu_username": "",
    "baidu_password": "",
    "baidu_token": "",
    "baidu_access_token": "YOUR_BAIDU_ACCESS_TOKEN",
    "baidu_refresh_token": "YOUR_BAIDU_REFRESH_TOKEN",
    "baidu_client_id": "YOUR_BAIDU_API_KEY",
    "baidu_client_secret": "YOUR_BAIDU_SECRET_KEY",
    "ip_blacklist": [
        "106.225.235.246"
    ]
}
```
*提示：亦可在监控前端大屏右上角的「配置中心」中在线填写并直接保存。*

### 3. 启动监控服务
执行以下命令启动后台 HTTP 服务（默认端口 `8000`）：
```bash
python monitor_server.py
```
启动完成后，在浏览器访问 `http://localhost:8000/` 即可打开监控大屏。

---

## 🔧 辅助工具脚本

### 🔑 百度 Token 兑换工具 ([get_token.py](file:///c:/Users/admin/Desktop/ghost-proxifier-monitor/get_token.py))
在百度开放平台获取 Authorization Code 后，运行：
```bash
python get_token.py <YOUR_AUTHORIZATION_CODE>
```
脚本将自动向百度 API 换取 `access_token` 和 `refresh_token` 并自动写入 [config.json](file:///c:/Users/admin/Desktop/ghost-proxifier-monitor/config.json.example)。

### 🔄 历史访客日志同步 ([sync_history.py](file:///c:/Users/admin/Desktop/ghost-proxifier-monitor/sync_history.py))
拉取百度统计过去 14 天的历史访客日志并增量补全写入本地 SQLite 数据库：
```bash
python sync_history.py
```

### 🩺 系统健康诊断 ([verify_apis.py](file:///c:/Users/admin/Desktop/ghost-proxifier-monitor/verify_apis.py))
在部署或配置变更后运行系统自检：
```bash
python verify_apis.py
```
检查项包括：SQLite3 数据库读写、GitHub Star 与 Release 下载量 API 连通性、百度统计 JSON 解析器测试。

---

## 📡 后端 API 接口

| HTTP 方法 | 接口路径 | 描述 |
| :--- | :--- | :--- |
| `GET` | `/api/stats` | 获取大屏聚合数据（GitHub Stars、MSI 下载量、DAU、时段趋势图数据） |
| `GET` | `/api/config` | 查询当前服务器配置（脱敏显示） |
| `POST` | `/api/config` | 更新保存系统配置 |
| `POST` | `/api/refresh` | 手动触发一次 API 轮询与指标刷新 |
| `GET` | `/api/baidu_auth_url` | 获取百度 OAuth2.0 登录授权 URL |
| `GET` | `/api/visitor_logs` | 查询访客日志记录 |
| `GET` | `/api/area_stats` | 获取访客省份地理分布统计 |

---
