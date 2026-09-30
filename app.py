#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HidenCloud 自动续期脚本 (优化增强版)
- 支持 Cookie 免密登录 & 账号密码自动登录
- 支持多服务器自动检测与批量续期 / 指定单个服务器续期
- 深度抗检测 (Stealth) 与智能 Cloudflare Turnstile 验证处理
- 适应多种到期时间格式与多语言界面
- 解决 "Create Invoice 超时" 问题：
  * 自动处理未跳转、新标签页打开、URL格式差异 (/invoice/ vs /payment/invoice/)
  * 预检与后置轮询未支付发票 (/service/{id}/invoices?where=unpaid)
  * 支持 0 元免单 "Pay the Free Invoice"
- 多渠道推送通知 (Telegram, Bark, Pushplus, Server酱, 自定义 Webhook)
- 自动异常捕获与失败截图保存
"""

import os
import re
import sys
import time
import random
import json
from typing import List, Dict, Tuple, Optional
import requests

try:
    from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
except ImportError:
    print("❌ 未检测到 playwright，请运行: pip install playwright && python -m playwright install --with-deps chrome")
    sys.exit(1)

# ==================== 配置与环境变量 ====================
BASE_URL = os.environ.get('BASE_URL', 'https://dash.hidencloud.com').rstrip('/')
LOGIN_URL = f"{BASE_URL}/auth/login"

COOKIE_VALUE = os.environ.get('COOKIE_VALUE', '').strip()
COOKIE_NAME  = os.environ.get('COOKIE_NAME', 'remember_web_59ba36addc2b2f9401580f014c7f58ea4e30989d').strip()
EMAIL        = os.environ.get('EMAIL', '').strip()
PASSWORD     = os.environ.get('PASSWORD', '').strip()

SERVER_NAME  = os.environ.get('SERVER_NAME', '').strip()
TARGET_SERVER_ID = os.environ.get('SERVER_ID', '').strip()

# 通知配置
TG_BOT_TOKEN   = os.environ.get('TG_BOT_TOKEN', '').strip()
TG_CHAT_ID     = os.environ.get('TG_CHAT_ID', '').strip()
BARK_KEY       = os.environ.get('BARK_KEY', '').strip()
PUSHPLUS_TOKEN = os.environ.get('PUSHPLUS_TOKEN', '').strip()
SERVERCHAN_KEY = os.environ.get('SERVERCHAN_KEY', '').strip()
WEBHOOK_URL    = os.environ.get('WEBHOOK_URL', '').strip()

# 运行时选项
HEADLESS_MODE  = os.environ.get('HEADLESS', 'false').lower() in ('true', '1', 'yes')
NOTIFY_ON_NOT_TIME = os.environ.get('NOTIFY_ON_NOT_TIME', 'true').lower() in ('true', '1', 'yes')

# 代理配置
IS_PROXY      = os.environ.get('IS_PROXY', 'false').lower() == 'true'
PROXY_SERVER  = os.environ.get('PROXY_SERVER') or "socks5://127.0.0.1:1080"
REQUESTS_PROXIES = {"http": PROXY_SERVER, "https": PROXY_SERVER} if IS_PROXY else None

# ==================== 日志与脱敏工具 ====================
def log(msg: str):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

def mask_email(email: str) -> str:
    if not email:
        return "未知账号"
    if '@' in email:
        name, domain = email.split('@', 1)
        if len(name) > 3:
            masked_name = f"{name[:2]}****{name[-1:]}"
        else:
            masked_name = f"{name[:1]}****"
        return f"{masked_name}@{domain}"
    return f"{email[:2]}****"

# ==================== 高级 Stealth 注入脚本 ====================
STEALTH_JS = """
// 隐藏 webdriver 属性
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// 模拟正常的 chrome runtime
window.chrome = {
    app: { isInstalled: false, InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }, RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' } },
    runtime: {
        OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' },
        OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
        PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
        PlatformNaclArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
        PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' },
        RequestUpdateCheckStatus: { NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' }
    }
};

// 模拟正常的 plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const ChromePDFPlugin = { description: "Portable Document Format", filename: "internal-pdf-viewer", name: "Chrome PDF Plugin" };
        const ChromePDFViewer = { description: "", filename: "mhjfbmdgcfjbbpaeojofohoefgiehjai", name: "Chrome PDF Viewer" };
        const NativeClient = { description: "", filename: "internal-nacl-plugin", name: "Native Client" };
        const plugins = [ChromePDFPlugin, ChromePDFViewer, NativeClient];
        plugins.item = (i) => plugins[i];
        plugins.namedItem = (name) => plugins.find(p => p.name === name);
        plugins.refresh = () => {};
        return plugins;
    }
});

// 模拟 languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en', 'zh-CN', 'zh']
});

// 模拟 permissions 查询
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);
"""

# ==================== 出口 IP 获取 ====================
def get_current_ip() -> str:
    """获取当前出口 IP，增加超时与重试"""
    urls = [
        "https://api.ip.sb/ip",
        "https://api.ipify.org",
        "https://icanhazip.com"
    ]
    for url in urls:
        try:
            resp = requests.get(url, proxies=REQUESTS_PROXIES, timeout=8)
            if resp.status_code == 200:
                ip = resp.text.strip()
                if ip:
                    return ip
        except Exception:
            continue
    return "获取失败 (网络异常)"

# ==================== 多渠道通知系统 ====================
def send_notification(status: str, results: List[Dict[str, str]], outgoing_ip: str):
    """
    统一多渠道通知发送器
    results 格式: [{"server_id": "...", "server_name": "...", "status": "...", "old_due": "...", "new_due": "..."}]
    """
    account_str = mask_email(EMAIL) if EMAIL else "Cookie 认证账号"
    local_time = time.gmtime(time.time() + 8 * 3600)
    now_str = time.strftime("%Y-%m-%d %H:%M:%S", local_time)

    server_details = []
    for r in results:
        s_id = r.get("server_id", "未知")
        s_name = r.get("server_name") or SERVER_NAME or f"Server #{s_id}"
        s_status = r.get("status", "")
        old_due = r.get("old_due", "未知")
        new_due = r.get("new_due", "未知")
        detail = (
            f"🔹 <b>{s_name}</b> (ID: {s_id})\n"
            f"   状态: {s_status}\n"
            f"   续期前到期: {old_due}\n"
            f"   续期后到期: {new_due}"
        )
        server_details.append(detail)
    
    servers_block = "\n\n".join(server_details) if server_details else "无服务器操作记录"

    html_text = (
        f"<b>📢 HidenCloud 自动续期报告</b>\n\n"
        f"<b>总体状态：</b>{status}\n"
        f"<b>账号：</b><code>{account_str}</code>\n"
        f"<b>出口 IP：</b><code>{outgoing_ip}</code>\n\n"
        f"{servers_block}\n\n"
        f"🕒 执行时间: {now_str} (UTC+8)"
    )

    plain_lines = [
        f"【HidenCloud 续期报告】",
        f"状态: {status}",
        f"账号: {account_str}",
        f"出口 IP: {outgoing_ip}",
        "",
        "--- 服务器详情 ---"
    ]
    for r in results:
        s_name = r.get("server_name") or SERVER_NAME or f"Server #{r.get('server_id', '')}"
        plain_lines.append(f"{s_name}: {r.get('status')} (前: {r.get('old_due')} -> 后: {r.get('new_due')})")
    plain_lines.append(f"\n执行时间: {now_str}")
    plain_text = "\n".join(plain_lines)

    # 1. Telegram
    if TG_BOT_TOKEN and TG_CHAT_ID:
        try:
            tg_url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": TG_CHAT_ID,
                "text": html_text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            resp = requests.post(tg_url, json=payload, timeout=12, proxies=REQUESTS_PROXIES)
            if resp.status_code == 200:
                log("✅ Telegram 通知发送成功")
            else:
                log(f"❌ Telegram 通知失败: {resp.text}")
        except Exception as e:
            log(f"❌ Telegram 发送异常: {e}")

    # 2. Bark
    if BARK_KEY:
        try:
            bark_url = BARK_KEY.rstrip('/')
            if not bark_url.startswith("http"):
                bark_url = f"https://api.day.app/{bark_url}"
            payload = {
                "title": f"HidenCloud 续期: {status}",
                "body": plain_text,
                "group": "HidenCloud",
                "icon": "https://dash.hidencloud.com/favicon.ico"
            }
            resp = requests.post(bark_url, json=payload, timeout=10)
            if resp.status_code == 200:
                log("✅ Bark 通知发送成功")
            else:
                log(f"❌ Bark 通知失败: {resp.text}")
        except Exception as e:
            log(f"❌ Bark 发送异常: {e}")

    # 3. Pushplus
    if PUSHPLUS_TOKEN:
        try:
            pp_url = "http://www.pushplus.plus/send"
            payload = {
                "token": PUSHPLUS_TOKEN,
                "title": f"HidenCloud 续期报告 - {status}",
                "content": html_text.replace("\n", "<br/>"),
                "template": "html"
            }
            resp = requests.post(pp_url, json=payload, timeout=10)
            if resp.status_code == 200:
                log("✅ Pushplus 通知发送成功")
            else:
                log(f"❌ Pushplus 通知失败: {resp.text}")
        except Exception as e:
            log(f"❌ Pushplus 发送异常: {e}")

    # 4. Server 酱
    if SERVERCHAN_KEY:
        try:
            sc_url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
            payload = {
                "title": f"HidenCloud 续期: {status}",
                "desp": plain_text
            }
            resp = requests.post(sc_url, data=payload, timeout=10)
            if resp.status_code == 200:
                log("✅ Server酱通知发送成功")
            else:
                log(f"❌ Server酱通知失败: {resp.text}")
        except Exception as e:
            log(f"❌ Server酱发送异常: {e}")

    # 5. 通用 Webhook
    if WEBHOOK_URL:
        try:
            payload = {
                "msg_type": "text",
                "text": {"content": plain_text},
                "content": plain_text
            }
            resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
            log(f"✅ 自定义 Webhook 发送完成 (HTTP {resp.status_code})")
        except Exception as e:
            log(f"❌ 自定义 Webhook 发送异常: {e}")

# ==================== Cloudflare Turnstile 验证处理 ====================
def handle_cloudflare(page: Page, max_wait: int = 50) -> bool:
    """
    智能处理 Cloudflare 5秒盾、Security Verification 与 Turnstile 验证码
    """
    start_time = time.time()
    time.sleep(1.5)  # 等待页面与 iframe 开始加载

    def is_cf_present():
        try:
            title = page.title().lower()
            if "just a moment" in title or "security verification" in title:
                return True
            body = page.locator("body").inner_text().lower()
            if "verify you are human" in body or "validating security" in body or "security verification" in body:
                return True
        except Exception:
            pass
        if page.locator('iframe[src*="cloudflare.com"], iframe[src*="challenges"]').count() > 0:
            return True
        return False

    if not is_cf_present():
        return True

    log("⚠️ 检测到 Cloudflare / Security Verification 验证，正在自动处理...")

    last_click_time = 0
    while time.time() - start_wait_cf < max_wait if 'start_wait_cf' in locals() else time.time() - start_time < max_wait:
        if not is_cf_present():
            log("✅ Cloudflare 验证已成功通过！")
            time.sleep(2)
            return True

        now = time.time()
        # 每隔 3.5 秒尝试定位并点击一次复选框
        if now - last_click_time > 3.5:
            last_click_time = now
            try:
                # 方案 1: 根据 iframe 坐标点击左侧复选框 (最有效，绕过跨域安全限制)
                cf_iframe = page.locator('iframe[src*="challenges.cloudflare.com"], iframe[src*="cloudflare.com"]').first
                if cf_iframe.count() > 0 and cf_iframe.is_visible():
                    box = cf_iframe.bounding_box()
                    if box and box["width"] > 40 and box["height"] > 25:
                        click_x = box["x"] + min(28, box["width"] / 4)
                        click_y = box["y"] + box["height"] / 2
                        log(f"🖱️ 模拟点击 Turnstile 复选框坐标 ({click_x:.1f}, {click_y:.1f})...")
                        page.mouse.move(click_x, click_y, steps=5)
                        time.sleep(random.uniform(0.1, 0.25))
                        page.mouse.down()
                        time.sleep(random.uniform(0.05, 0.12))
                        page.mouse.up()

                # 方案 2: frame_locator 点击
                if cf_iframe.count() > 0:
                    frame = page.frame_locator('iframe[src*="challenges.cloudflare.com"]').first
                    checkbox = frame.locator('input[type="checkbox"], .ctp-checkbox-label, #cf-stage, span.mark').first
                    if checkbox.count() > 0 and checkbox.is_visible():
                        checkbox.click(force=True)
            except Exception:
                pass

        time.sleep(1)

    if not is_cf_present():
        log("✅ Cloudflare 验证通过！")
        return True

    log("❌ Cloudflare 验证超时。")
    page.screenshot(path="cf_timeout.png")
    return False

# ==================== 登录逻辑 ====================
def parse_cookie_input(raw_cookie: str, default_name: str) -> List[Dict]:
    cookies = []
    raw = raw_cookie.strip()
    if not raw:
        return cookies

    if ';' in raw:
        pairs = raw.split(';')
        for p in pairs:
            if '=' in p:
                k, v = p.strip().split('=', 1)
                k, v = k.strip(), v.strip()
                if k:
                    cookies.append({
                        'name': k,
                        'value': v,
                        'domain': 'dash.hidencloud.com',
                        'path': '/',
                        'httpOnly': True,
                        'secure': True,
                        'sameSite': 'Lax'
                    })
        return cookies

    if '=' in raw:
        k, v = raw.split('=', 1)
        cookies.append({
            'name': k.strip(),
            'value': v.strip(),
            'domain': 'dash.hidencloud.com',
            'path': '/',
            'httpOnly': True,
            'secure': True,
            'sameSite': 'Lax'
        })
        return cookies

    cookies.append({
        'name': default_name,
        'value': raw,
        'domain': 'dash.hidencloud.com',
        'path': '/',
        'httpOnly': True,
        'secure': True,
        'sameSite': 'Lax'
    })
    return cookies

def login(page: Page) -> bool:
    if COOKIE_VALUE:
        log("📇 正在注入 Cookie 尝试快捷登录...")
        try:
            cookie_list = parse_cookie_input(COOKIE_VALUE, COOKIE_NAME)
            page.context.add_cookies(cookie_list)
            page.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded", timeout=60000)
            handle_cloudflare(page)
            time.sleep(2)

            log(f"📝 当前页面标题: {page.title()}, URL: {page.url}")
            if "auth/login" not in page.url and ("/dashboard" in page.url or "/service" in page.url):
                log("✅ Cookie 验证成功！已直接进入控制面板")
                return True
            log("⚠️ Cookie 已失效或未能通过认证，将尝试账号密码登录...")
        except Exception as e:
            log(f"⚠️ Cookie 登录过程出错: {e}")

    if not EMAIL or not PASSWORD:
        log("❌ 缺少有效账号密码，且 Cookie 登录未通过，无法继续。")
        page.screenshot(path="login_no_credentials.png")
        return False

    log(f"🔑 正在使用账号密码登录: {mask_email(EMAIL)}...")
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)

        email_input = page.locator('input[name="email"], input[type="email"]')
        email_input.wait_for(state="visible", timeout=20000)
        email_input.fill(EMAIL)

        pass_input = page.locator('input[name="password"], input[type="password"]')
        pass_input.fill(PASSWORD)
        time.sleep(random.uniform(0.5, 1.0))

        handle_cloudflare(page, max_wait=15)

        submit_btn = page.locator('button[type="submit"], button:has-text("Login"), button:has-text("登录")').first
        submit_btn.click()
        log("🖱️ 已提交登录表单，等待重定向...")

        start_wait = time.time()
        while time.time() - start_wait < 30:
            handle_cloudflare(page, max_wait=5)
            if "auth/login" not in page.url:
                break
            time.sleep(1)

        if "dashboard" not in page.url:
            page.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded", timeout=60000)
            handle_cloudflare(page)

        time.sleep(2)
        log(f"📝 登录后页面: {page.title()}, URL: {page.url}")

        if "auth/login" in page.url:
            error_el = page.locator('.alert-danger, .error-message, [role="alert"]')
            error_msg = error_el.inner_text() if error_el.count() > 0 else "账号或密码错误"
            log(f"❌ 账号密码登录失败: {error_msg}")
            page.screenshot(path="login_failed.png")
            return False

        log("✅ 账号密码登录成功！已成功进入控制面板")
        return True

    except Exception as e:
        log(f"❌ 账号密码登录异常: {e}")
        page.screenshot(path="login_exception.png")
        return False

# ==================== 服务器识别 ====================
def discover_servers(page: Page) -> List[Dict[str, str]]:
    servers = []
    try:
        if "/dashboard" not in page.url:
            page.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        time.sleep(2)

        html = page.content()
        matches = re.findall(r'/service/(\d+)/manage', html)
        unique_ids = list(dict.fromkeys(matches))

        if not unique_ids:
            text_matches = re.findall(r'#(\d{4,})', html)
            unique_ids = list(dict.fromkeys(text_matches))

        if TARGET_SERVER_ID:
            log(f"🎯 指定目标 Server ID: {TARGET_SERVER_ID}")
            if TARGET_SERVER_ID not in unique_ids:
                unique_ids.insert(0, TARGET_SERVER_ID)
            else:
                unique_ids = [TARGET_SERVER_ID]

        for s_id in unique_ids:
            name = SERVER_NAME or f"Server #{s_id}"
            servers.append({"id": s_id, "name": name})

        log(f"📋 发现服务器数量: {len(servers)} 个: {[s['id'] for s in servers]}")
        return servers

    except Exception as e:
        log(f"❌ 发现服务器失败: {e}")
        page.screenshot(path="discover_servers_error.png")
        return servers

# ==================== 到期时间提取 ====================
def extract_due_date(page: Page, service_url: str) -> str:
    try:
        if page.url != service_url:
            page.goto(service_url, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        time.sleep(1.5)

        body_text = page.locator("body").inner_text()

        patterns = [
            r"(?:Due\s*date|Next\s*Due|到期时间|到期日)\s*[:：]?\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
            r"(?:Due\s*date|Next\s*Due|到期时间|到期日)\s*[:：]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
            r"(?:Due\s*date|Next\s*Due|到期时间|到期日)\s*[:：]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})",
            r"(?:Due\s*date|Next\s*Due)\s*\n\s*([0-9A-Za-z\s,/ -]{8,25})"
        ]

        for p in patterns:
            match = re.search(p, body_text, re.IGNORECASE)
            if match:
                due_str = match.group(1).strip()
                if len(due_str) >= 6 and any(char.isdigit() for char in due_str):
                    return due_str

        candidate = page.locator('text=/Due\\s*date/i >> xpath=..').first
        if candidate.count() > 0:
            return candidate.inner_text().replace('\n', ' ').strip()

    except Exception as e:
        log(f"⚠️ 解析到期时间出错: {e}")

    return "未知"

# ==================== 发票检测与支付工具 ====================
def check_unpaid_invoices(page: Page, server_id: str) -> List[str]:
    """
    检查指定服务器下的未支付发票链接
    访问: /service/{server_id}/invoices?where=unpaid
    """
    invoice_links = []
    unpaid_url = f"{BASE_URL}/service/{server_id}/invoices?where=unpaid"
    try:
        log(f"🔎 正在主动查询未支付发票列表: {unpaid_url}")
        page.goto(unpaid_url, wait_until="domcontentloaded", timeout=30000)
        handle_cloudflare(page)
        time.sleep(2)

        html = page.content()
        # 查找所有指向 /invoice/ 或 /payment/invoice/ 的链接，忽略 download 链接
        matches = re.findall(r'href=["\']([^"\']*(?:/invoice/|/payment/invoice/)[^"\']*)["\']', html, re.I)
        for link in matches:
            if 'download' in link.lower() or 'pdf' in link.lower():
                continue
            full_link = link if link.startswith("http") else f"{BASE_URL}{link if link.startswith('/') else '/' + link}"
            if full_link not in invoice_links:
                invoice_links.append(full_link)

        log(f"📑 发现未支付发票链接: {invoice_links}")
    except Exception as e:
        log(f"⚠️ 查询未支付发票异常: {e}")
    return invoice_links

def pay_invoice_page(page: Page, invoice_url: str) -> bool:
    """
    在发票详情页执行支付（特别适配 0元发票 "Pay the Free Invoice" 与通用结清）
    """
    try:
        log(f"💳 正在进入发票页面进行结算: {invoice_url}")
        if page.url != invoice_url:
            page.goto(invoice_url, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        time.sleep(2)

        # 检查是否已经是已支付状态
        body_content = page.locator("body").inner_text()
        if any(w in body_content for w in ["Paid", "PAID", "已支付", "Payment Received"]):
            log("✅ 发票已处于 Paid (已支付) 状态，无需重复结算！")
            return True

        # 定位各类支付按钮（特别支持 HidenCloud 专属的 "Pay the Free Invoice"）
        pay_btn_selectors = [
            'button:has-text("Pay the Free Invoice")',
            'button:has-text("Pay Free Invoice")',
            'a:has-text("Pay the Free Invoice")',
            'button:has-text("Pay")',
            'a:has-text("Pay"):visible',
            'button:has-text("Pay Now")',
            'button:has-text("支付")',
            'button:has-text("立即支付")',
            'button:has-text("Complete Order")',
            'button:has-text("Confirm Payment")',
            'button[type="submit"]:has-text("Pay")'
        ]

        pay_btn = None
        for sel in pay_btn_selectors:
            target = page.locator(sel)
            if target.count() > 0 and target.first.is_visible():
                pay_btn = target.first
                log(f"🎯 匹配到支付按钮: {sel}")
                break

        # 如果没有直接找到文本按钮，尝试查找包含 invoice 或 payment 的表单内提交按钮
        if not pay_btn:
            form_btn = page.locator('form[action*="invoice"] button[type="submit"], form[action*="payment"] button[type="submit"]').first
            if form_btn.count() > 0 and form_btn.is_visible():
                pay_btn = form_btn
                log("🎯 匹配到支付表单提交按钮")

        if pay_btn:
            log("🖱️ 正在点击支付确认按钮...")
            pay_btn.scroll_into_view_if_needed()
            pay_btn.click()
            time.sleep(4)
            handle_cloudflare(page)
            log("✅ 支付请求已发送完成！")
            return True
        else:
            log("⚠️ 未在发票页找到可点击的支付按钮，检查是否为只读或已被自动扣减。")
            page.screenshot(path="invoice_pay_button_missing.png")
            return False

    except Exception as e:
        log(f"❌ 支付发票时出错: {e}")
        page.screenshot(path="pay_invoice_error.png")
        return False

# ==================== 核心续期流程 ====================
def renew_single_server(page: Page, server_info: Dict[str, str]) -> Tuple[str, str, str]:
    """
    对单个服务器执行完整的续期操作
    返回: (status_code, old_due, new_due)
    """
    server_id = server_info["id"]
    service_url = f"{BASE_URL}/service/{server_id}/manage"
    log(f"\n==================== 🔄 开始处理服务器 #{server_id} ====================")

    try:
        # 步骤 0: 预检清理 —— 检查是否已经存在此前未支付的发票
        unpaid_invoices = check_unpaid_invoices(page, server_id)
        if unpaid_invoices:
            log(f"⚡ 预检发现该服务器已有未支付发票，优先执行账单结算...")
            for inv_url in unpaid_invoices:
                pay_invoice_page(page, inv_url)
            # 结清后返回管理页刷新状态
            page.goto(service_url, wait_until="domcontentloaded", timeout=60000)
            handle_cloudflare(page)

        # 步骤 1: 访问管理页，获取旧到期时间与检查续期条件
        if page.url != service_url:
            page.goto(service_url, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        time.sleep(2)

        old_due = extract_due_date(page, service_url)
        log(f"📅 当前到期时间: {old_due}")

        # 检查页面源码是否包含 showRenewAlert(days_until, threshold, is_free)
        page_html = page.content()
        alert_match = re.search(r'showRenewAlert\((\d+),\s*(\d+),\s*(true|false)\)', page_html)
        if alert_match:
            days_until = int(alert_match.group(1))
            threshold = int(alert_match.group(2))
            is_free = alert_match.group(3) == 'true'
            log(f"ℹ️ 检测到续期阈值逻辑: 剩余天数={days_until}, 需低于阈值={threshold}天 (免费服务={is_free})")
            if days_until > threshold:
                log(f"⏳ 暂未到达续期时间: 剩余 {days_until} 天，需剩余低于 {threshold} 天时才可续期。")
                return "NOT_TIME", old_due, old_due

        # 步骤 2: 定位并点击 Renew 按钮
        renew_selectors = [
            'button:has-text("Renew")',
            'a:has-text("Renew")',
            'button:has-text("续费")',
            'button:has-text("续期")',
            '[data-action="renew"]'
        ]

        renew_btn = None
        for sel in renew_selectors:
            target = page.locator(sel)
            if target.count() > 0 and target.first.is_visible():
                renew_btn = target.first
                break

        if not renew_btn:
            log(f"❌ 未找到服务器 #{server_id} 的 'Renew' 续费按钮")
            page.screenshot(path=f"renew_btn_not_found_{server_id}.png")
            return "FAILED", old_due, old_due

        modal_opened = False
        create_btn_selectors = [
            'button:has-text("Create Invoice")',
            'button:has-text("Generate Invoice")',
            'button:has-text("创建发票")',
            'button:has-text("Confirm")',
            'button:has-text("Renew")',
            'button[type="submit"]'
        ]

        for attempt in range(1, 4):
            log(f"🖱️ 第 {attempt} 次点击 'Renew' 按钮...")
            renew_btn.scroll_into_view_if_needed()
            renew_btn.click()
            time.sleep(2)

            # 检测是否提示未到续期时间
            page_text = page.locator("body").inner_text()
            if any(kw in page_text for kw in [
                "Renewal Restricted",
                "can only renew",
                "Not eligible for renewal",
                "Cannot renew yet",
                "未到续期时间"
            ]):
                log(f"⏳ 页面提示：未到续期时间，当前无法续期。")
                page.screenshot(path=f"renew_restricted_{server_id}.png")
                return "NOT_TIME", old_due, old_due

            for c_sel in create_btn_selectors:
                modal_btn = page.locator(f'.modal {c_sel}, [role="dialog"] {c_sel}, {c_sel}').first
                if modal_btn.count() > 0 and modal_btn.is_visible():
                    log("🖲️ 续费确认弹窗已成功展开！")
                    modal_opened = True
                    break

            if modal_opened:
                break
            time.sleep(2)

        if not modal_opened:
            log(f"❌ 经过多次尝试，续费确认弹窗未响应。")
            page.screenshot(path=f"modal_failed_{server_id}.png")
            return "FAILED", old_due, old_due

        # 步骤 3: 点击生成发票
        handle_cloudflare(page)
        target_create_btn = None
        for c_sel in create_btn_selectors:
            b = page.locator(f'.modal {c_sel}, [role="dialog"] {c_sel}, {c_sel}').first
            if b.count() > 0 and b.is_visible():
                target_create_btn = b
                break

        # 记录当前已打开的页面数，用于检测是否新标签页打开
        initial_pages_count = len(page.context.pages)

        if target_create_btn:
            log("🖱️ 正在点击 'Create Invoice' 生成发票...")
            target_create_btn.click()
        else:
            log("⚠️ 未明确找到生成发票按钮，尝试使用 Enter 键提交")
            page.keyboard.press("Enter")

        # 步骤 4: 智能发票页面捕获 (避免死等90秒超时！)
        log("⏳ 正在等待发票生成...")
        target_invoice_url = None
        current_active_page = page

        # 轮询 12 秒，监测 URL 跳转或新标签页
        for _ in range(12):
            time.sleep(1)
            # 1. 检查是否打开了新标签页
            if len(page.context.pages) > initial_pages_count:
                new_tab = page.context.pages[-1]
                log(f"📑 检测到新标签页打开: {new_tab.url}")
                current_active_page = new_tab
                target_invoice_url = new_tab.url
                break

            # 2. 检查当前页 URL 是否发生跳转
            if re.search(r'/(?:payment/)?invoice(?:s)?/\d+', page.url, re.I):
                target_invoice_url = page.url
                log(f"🎉 页面已直接跳转至发票详情页: {target_invoice_url}")
                break

            # 3. 检查页面上是否出现了发票链接
            inv_links = page.locator('a[href*="/invoice/"]').all()
            if inv_links:
                for a in inv_links:
                    href = a.get_attribute("href") or ""
                    if "download" not in href:
                        target_invoice_url = href if href.startswith("http") else f"{BASE_URL}{href}"
                        log(f"🔗 从当前页面抓取到新发票链接: {target_invoice_url}")
                        break
            if target_invoice_url:
                break

        # 如果没有自动跳转，则主动查询未支付账单列表！
        if not target_invoice_url:
            log("⚠️ 点击 'Create Invoice' 后页面未自动重定向，主动转入未支付发票列表查询...")
            pending_invoices = check_unpaid_invoices(page, server_id)
            if pending_invoices:
                target_invoice_url = pending_invoices[0]
                log(f"🎯 主动匹配到生成的未支付发票: {target_invoice_url}")

        if not target_invoice_url:
            # 再次检查是否有错误提示
            page_text = page.locator("body").inner_text()
            if any(err_kw in page_text for err_kw in ["already", "unpaid invoice", "existing invoice", "已有未支付"]):
                log("ℹ️ 提示已有正在处理的发票，重新拉取所有发票列表...")
                pending_invoices = check_unpaid_invoices(page, server_id)
                if pending_invoices:
                    target_invoice_url = pending_invoices[0]

        if not target_invoice_url:
            log("❌ 未能获取到发票 URL，超时退出。")
            page.screenshot(path=f"renew_stuck_invoice_{server_id}.png")
            return "FAILED", old_due, old_due

        # 步骤 5: 执行发票支付
        pay_success = pay_invoice_page(current_active_page, target_invoice_url)
        if not pay_success:
            log("⚠️ 发票支付未成功完成，记录现场截图...")
            current_active_page.screenshot(path=f"pay_failed_{server_id}.png")

        # 步骤 6: 验证续期后的最新到期时间
        log("🔄 重新拉取服务详情页，确认续期后到期时间...")
        page.goto(service_url, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        time.sleep(3)

        new_due = extract_due_date(page, service_url)
        log(f"📆 续期后到期时间: {new_due}")

        return "SUCCESS", old_due, new_due

    except Exception as e:
        log(f"❌ 处理服务器 #{server_id} 时发生异常: {e}")
        page.screenshot(path=f"renew_exception_{server_id}.png")
        return "FAILED", old_due if 'old_due' in locals() else "未知", "未知"

# ==================== 主入口函数 ====================
def main():
    log("==================================================")
    log("✨ HidenCloud 自动续期任务启动")
    log("==================================================")

    if not COOKIE_VALUE and not (EMAIL and PASSWORD):
        log("❌ 错误: 未提供任何登录凭证！请在 Secrets 中配置 COOKIE_VALUE 或 EMAIL + PASSWORD")
        sys.exit(1)

    if IS_PROXY:
        log(f"⚙️ 代理已启用: {PROXY_SERVER}")
    else:
        log("🌐 直连模式运行 (未启用代理)")

    outgoing_ip = get_current_ip()
    log(f"🎯 任务出口 IP: {outgoing_ip}")

    overall_exit_code = 0
    all_results = []
    has_success = False
    has_failure = False
    all_not_time = True

    with sync_playwright() as p:
        browser: Optional[Browser] = None
        context: Optional[BrowserContext] = None

        try:
            log("🚀 启动浏览器引擎...")
            launch_args = [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--disable-dev-shm-usage',
                '--window-size=1920,1080'
            ]
            try:
                browser = p.chromium.launch(
                    channel="chrome",
                    headless=HEADLESS_MODE,
                    args=launch_args
                )
                log("✅ 成功启动 Google Chrome 浏览器")
            except Exception:
                log("⚠️ 未检测到系统 Chrome，自动回退至标准 Chromium 引擎...")
                browser = p.chromium.launch(
                    headless=HEADLESS_MODE,
                    args=launch_args
                )
                log("✅ 成功启动 Chromium 浏览器")

            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
                proxy={"server": PROXY_SERVER} if IS_PROXY else None,
                locale='en-US',
                timezone_id='Asia/Shanghai'
            )

            page = context.new_page()
            page.add_init_script(STEALTH_JS)

            if not login(page):
                log("❌ 登录失败，终止执行")
                send_notification(
                    status="❌ 登录失败 (Cookie 失效或账密错误)",
                    results=[],
                    outgoing_ip=outgoing_ip
                )
                sys.exit(1)

            server_list = discover_servers(page)
            if not server_list:
                log("❌ 未能识别到任何可用服务器，请检查控制台是否有正在运行的实例")
                send_notification(
                    status="❌ 未找到有效服务器",
                    results=[],
                    outgoing_ip=outgoing_ip
                )
                sys.exit(1)

            for s_info in server_list:
                status_code, old_due, new_due = renew_single_server(page, s_info)

                if status_code == "SUCCESS":
                    s_status_text = "✅ 续期成功"
                    has_success = True
                    all_not_time = False
                elif status_code == "NOT_TIME":
                    s_status_text = "⏳ 未到续期时间"
                else:
                    s_status_text = "❌ 续期失败"
                    has_failure = True
                    all_not_time = False

                all_results.append({
                    "server_id": s_info["id"],
                    "server_name": s_info["name"],
                    "status": s_status_text,
                    "old_due": old_due,
                    "new_due": new_due
                })

            if has_failure:
                summary_status = "⚠️ 部分或全部服务器续期失败"
                overall_exit_code = 1
            elif has_success:
                summary_status = "🎉 服务器续期成功"
                overall_exit_code = 0
            elif all_not_time:
                summary_status = "⏳ 所有服务器均未到续期时间"
                overall_exit_code = 0
            else:
                summary_status = "ℹ️ 执行完毕"
                overall_exit_code = 0

            log(f"\n==================== 📊 执行汇总: {summary_status} ====================")

            if all_not_time and not NOTIFY_ON_NOT_TIME:
                log("ℹ️ 当前均未到续期时间，按配置跳过日常未到期通知")
            else:
                send_notification(summary_status, all_results, outgoing_ip)

        except Exception as e:
            log(f"💥 运行遭遇未捕获致命异常: {e}")
            send_notification(
                status=f"💥 脚本异常: {str(e)[:100]}",
                results=all_results,
                outgoing_ip=outgoing_ip
            )
            overall_exit_code = 1

        finally:
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass

    log("🏁 脚本执行结束")
    sys.exit(overall_exit_code)

if __name__ == "__main__":
    main()
