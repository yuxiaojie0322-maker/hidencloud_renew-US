# HidenCloud 自动续期增强版

基于 GitHub Actions 的 [HidenCloud](https://hidencloud.com) 云服务全自动续期方案。

### 🌟 核心特性与优化亮点

- **智能双登录引擎**：优先注入 `remember_web` Cookie 免密登录，Cookie 失效或未配置时自动平滑回退至账号密码登录。
- **深度防检测 (Stealth)**：内置高级浏览器指纹伪装，有效绕过 Cloudflare 5秒盾，自动识别并点击 Turnstile 人机验证复选框。
- **多服务器自动巡检与批量续期**：自动扫描当前账户下的所有有效服务器并依次尝试续期，无需手动抓取服务器 ID；也支持指定单个 `SERVER_ID`。
- **智能发票结清**：自动识别 0 元免费服务器账单与余额抵扣，一键完成支付结算。
- **丰富的通知渠道**：支持 Telegram Bot、Bark (iOS)、Pushplus (微信推送)、Server酱 (Turbo) 以及通用 Webhook (企业微信/飞书/钉钉/Discord)。
- **故障排查可视化**：当登录失败、验证码超时或续费异常时，自动截屏并上传至 GitHub Actions Artifacts，便于直接下载排查。

---

## ⚙️ 仓库配置

在仓库 `Settings → Secrets and variables → Actions` 中添加以下 Secrets：

### 1. 登录凭据（二选一或同时配置）

| Secret 名称 | 是否必填 | 说明 | 示例 |
|---|---|---|---|
| `COOKIE_VALUE` | 推荐必填 | `remember_web` Cookie 的值（支持纯值、`key=val` 或完整 Cookie 字符串），有效期常大于1年 | `eyJpdiI...` |
| `EMAIL` | 可选/备用 | HidenCloud 登录邮箱（Cookie 失效时备用登录，通知中会打码展示） | `user@example.com` |
| `PASSWORD` | 可选/备用 | HidenCloud 登录密码 | `your_password` |
| `COOKIE_NAME` | ❌可选 | 自定义 Cookie 键名（默认已预设官方哈希键） | `remember_web_59ba36...` |

> **提示**：`COOKIE_VALUE` 的获取方法：登录 HidenCloud 控制台后按 F12 打开开发者工具，切换至「应用程序/Application」或「存储/Storage」→「Cookies」→ 找到 `remember_web_...` 复制其 Value 即可。

### 2. 服务器与运行偏好（可选）

| Secret 名称 | 是否必填 | 说明 | 示例 |
|---|---|---|---|
| `SERVER_NAME` | ❌可选 | 服务器备注名称，用于通知消息展示 | `美区免费节点1号` |
| `SERVER_ID` | ❌可选 | 指定续期的服务器数字 ID（不填则自动扫描账户下所有服务器并批量续期） | `218079` |
| `NOTIFY_ON_NOT_TIME` | ❌可选 | 未到续期时间时是否也发送提醒，默认 `true`（填 `false` 可在未到期时静默） | `false` |

### 3. 多渠道通知推送（可选）

| Secret 名称 | 适用平台 | 说明 |
|---|---|---|
| `TG_BOT_TOKEN` | Telegram | Telegram 机器人 Token (如 `123456:ABC...`) |
| `TG_CHAT_ID` | Telegram | 接收通知的 Telegram 用户 ID 或频道 ID |
| `BARK_KEY` | iOS Bark | Bark 推送 Device Key 或完整自定义推送 URL |
| `PUSHPLUS_TOKEN` | 微信 Push+ | Pushplus 平台个人 Token |
| `SERVERCHAN_KEY` | Server酱 | Server酱 SendKey (Turbo 版) |
| `WEBHOOK_URL` | 通用 Webhook | 企业微信机器人、飞书自定义机器人、钉钉或 Discord Webhook URL |

### 4. 代理节点设置（可选，建议使用独享节点）

| Secret 名称 | 说明 |
|---|---|
| `NODE_LINK` | 支持 `vless://`、`vmess://`、`trojan://`、`hysteria2://`、`tuic://`、`socks5://` 格式的节点分享链接。留空则直接走 GitHub Actions 官方网络直连。 |

---

## 🚀 使用方法

1. **Fork 本仓库** 到个人 GitHub 账号。
2. 进入仓库 **Settings → Secrets and variables → Actions**，按需添加上述 Secrets。
3. 进入 **Actions** 标签页，在左侧选择 `Auto Renew HidenCloud`，点击 **Run workflow** 手动测试一次运行。
4. **调整定时计划**：
   - 默认配置为每周一 UTC 时间 05:30（北京时间 13:30）执行。
   - 文件路径：[`.github/workflows/renew.yml`](.github/workflows/renew.yml)
   - 可在 `schedule.cron` 中根据到期时间灵活调整（例如服务是每月 20 号到期，提前 7 天即可续期）。

---

## 🔍 故障排查

若工作流执行异常，可进入对应失败的 Action 运行页面，在底部的 **Artifacts** 区域下载 `hidencloud-debug-screenshots` 压缩包，即可查看程序自动保存的现场截图（如 `login_failed.png`、`cf_timeout.png`、`renew_restricted.png` 等），快速定位原因。

---

**⚠️ 免责声明**：本脚本仅供学习与个人管理服务使用，请遵守相关服务商的使用条款。
