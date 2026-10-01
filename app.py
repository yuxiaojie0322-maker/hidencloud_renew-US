#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os,re,sys,time,random,requests
try:
    import sitecustomize
except Exception:
    pass
,json
from playwright.sync_api import sync_playwright

# --- 环境变量 ---
COOKIE_VALUE = os.environ.get('COOKIE_VALUE') or ""    # remember_web cookie 值，必填
EMAIL        = os.environ.get('EMAIL') or ""           # 登录邮箱,可选，作为备用,TG通知需要填写
PASSWORD     = os.environ.get('PASSWORD') or ""        # 登录密码,可选，作为备用
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN') or ""    # Telegram Bot Token,可选
TG_CHAT_ID   = os.environ.get('TG_CHAT_ID') or ""      # Telegram Chat ID,可选
SERVER_NAME  = os.environ.get('SERVER_NAME') or ""      # 服务器备注/名称,可选

BASE_URL = "https://dash.hidencloud.com"
LOGIN_URL = f"{BASE_URL}/auth/login"

# --- 代理配置（由工作流 shell 脚本写入 $GITHUB_ENV）---
IS_PROXY      = os.environ.get('IS_PROXY', 'false').lower() == 'true'
PROXY_SERVER  = os.environ.get('PROXY_SERVER') or "socks5://127.0.0.1:1080"
REQUESTS_PROXIES = {"http": PROXY_SERVER, "https": PROXY_SERVER} if IS_PROXY else None

# 日志
def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
"""

def get_current_ip(proxy_server=None):
    """获取当前出口IP"""
    proxies = {"http": proxy_server, "https": proxy_server} if (proxy_server and IS_PROXY) else None
    try:
        resp = requests.get("https://api.ip.sb/ip", proxies=proxies, timeout=15)
        if resp.status_code == 200:
            return resp.text.strip()
        return "获取失败"
    except Exception as e:
        log(f"❌ 获取出口IP失败: {e}")
        return "获取失败"

def send_telegram_notification(status, old_due, new_due):
    """发送 Telegram 通知"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        log("⚠️ Telegram 未配置，跳过通知")
        return False
    
    local_time = time.gmtime(time.time() + 8 * 3600)
    now = time.strftime("%Y-%m-%d %H:%M:%S", local_time)
    if '@' in EMAIL:
        name, domain = EMAIL.split('@', 1)
        if len(name) > 4:
            masked_email = f"{name[:2]}****{name[-2:]}@{domain}"
        else:
            masked_email = f"{name}@{domain}"
    else:
        masked_email = EMAIL[:2] + '****' 

    server_info = f"🖥️ 服务器: {SERVER_NAME}\n" if SERVER_NAME else ""
    text = (
        f"📢 HidenCloud 续期通知\n\n"
        f"{status}\n"
        f"{server_info}"
        f"👤 账号: {masked_email}\n"
        f"📅 续期前到期：{old_due}\n"
        f"📅 续期后到期：{new_due}\n"
        f"🕒 续期时间：{now}"
    )
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, json=payload, timeout=10, proxies=REQUESTS_PROXIES)
        if resp.status_code == 200:
            log("✅ Telegram 通知发送成功")
            return True
        else:
            log(f"❌ Telegram 通知失败: {resp.text}")
            return False
    except Exception as e:
        log(f"❌ Telegram 通知异常: {e}")
        return False

def handle_cloudflare(page):
    time.sleep(1.5)
    def is_cf():
        try:
            title = page.title().lower()
            if "just a moment" in title or "security verification" in title:
                return True
            if page.locator('iframe[src*="challenges.cloudflare.com"], iframe[src*="cloudflare.com"]').count() > 0:
                return True
        except Exception:
            pass
        return False

    if not is_cf():
        return True

    log("⚠️ 检测到 Cloudflare 验证...")
    start_time = time.time()
    last_click = 0
    while time.time() - start_time < 60:
        if not is_cf():
            log("✅ Cloudflare 验证通过！")
            return True
        
        now = time.time()
        if now - last_click > 3.5:
            last_click = now
            try:
                cf_iframe = page.locator('iframe[src*="challenges.cloudflare.com"], iframe[src*="cloudflare.com"]').first
                if cf_iframe.count() > 0 and cf_iframe.is_visible():
                    box = cf_iframe.bounding_box()
                    if box and box["width"] > 40:
                        page.mouse.click(box["x"] + min(28, box["width"] / 4), box["y"] + box["height"] / 2)
                        log("🖱️ 点击验证复选框坐标...")
                
                frame = page.frame_locator('iframe[src*="challenges.cloudflare.com"]').first
                checkbox = frame.locator('input[type="checkbox"]').first
                if checkbox.count() > 0 and checkbox.is_visible():
                    checkbox.click(force=True)
            except Exception:
                pass
        time.sleep(1)

    if not is_cf():
        log("✅ Cloudflare 验证通过！")
        return True
    log("❌ 验证超时。")
    return False

def login(page):
    # 1. Cookie 登录尝试
    if COOKIE_VALUE:
        log("📇 尝试 Cookie 登录...")
        try:
            c_name = 'remember_web_59ba36addc2b2f9401580f014c7f58ea4e30989d'
            c_val = COOKIE_VALUE
            if '=' in COOKIE_VALUE and ';' not in COOKIE_VALUE:
                c_name, c_val = COOKIE_VALUE.split('=', 1)
            page.context.add_cookies([{
                'name': c_name.strip(),
                'value': c_val.strip(),
                'domain': 'dash.hidencloud.com',
                'path': '/',
                'expires': int(time.time()) + 3600 * 24 * 365,
                'httpOnly': True,
                'secure': True,
                'sameSite': 'Lax'
            }])
            page.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded", timeout=60000)
            handle_cloudflare(page)
            page_title = page.title()
            log(f"📝 当前Title: {page_title}")
            if "auth/login" not in page.url and ("/dashboard" in page.url or "/service" in page.url):
                log(f"✅ Cookie 登录成功！当前已到达dashboard页面")
                return True
            log("❌ Cookie 失效，请更换")
        except Exception as e:
            log(f"⚠️ Cookie 登录异常: {e}")

    # 2. 账号密码登录
    if not EMAIL or not PASSWORD:
        return False
    log("💣 尝试账号密码登录...")
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        page.fill('input[name="email"], input[type="email"]', EMAIL)
        page.fill('input[name="password"], input[type="password"]', PASSWORD)
        time.sleep(0.5)
        handle_cloudflare(page)
        page.click('button[type="submit"]')
        time.sleep(3)
        handle_cloudflare(page)
        page.wait_for_url(f"{BASE_URL}/*", timeout=30000)
        page.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        page_title = page.title()
        log(f"📝 当前Title: {page_title}")
        if "auth/login" in page.url:
            log("❌ 登录失败。")
            return False
        log(f"✅ 账号密码登录成功！当前已到达dashboard页面")
        return True
    except Exception as e:
        log(f"❌ 登录异常: {e}")
        page.screenshot(path="login_fail.png")
        return False

def get_server_id(page):
    try:
        handle_cloudflare(page)
        time.sleep(3)
        html = page.content()
        log(f"📝 页面长度: {len(html)}, URL: {page.url}")

        matches = re.findall(r'/service/(\d+)/manage', html)
        if matches:
            server_id = matches[0]
            log(f"✅ 从链接中获取到 Server ID: {server_id}")
            return server_id

        matches = re.findall(r'#(\d{4,})', html)
        if matches:
            server_id = matches[0]
            log(f"✅ 从文本 #号中获取到 Server ID: {server_id}")
            return server_id

        log("❌ 所有 URL 均未找到 Server ID")
        return None
    except Exception as e:
        log(f"❌ 获取 Server ID 失败: {e}")
        page.screenshot(path="server_id_error.png")
        return None

def get_due_date(page):
    try:
        if SERVICE_URL not in page.url:
            page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        body_text = page.locator("body").inner_text()
        patterns = [
            r"Due date\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",
            r"Due date\s*\n\s*(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",
            r"Due date.*?(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",
            r"(?:Due\s*date|到期时间|到期日)\s*[:：]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
            r"(?:Due\s*date|到期时间|到期日)\s*[:：]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})"
        ]
        for pattern in patterns:
            match = re.search(pattern, body_text, re.IGNORECASE | re.DOTALL)
            if match:
                due_date = match.group(1).strip()
                log(f"📅 获取到Due Date: {due_date}")
                return due_date
    except Exception as e:
        log(f"❌ 获取Due Date失败: {e}")
    return "未知"

def pay_invoice_thoroughly(page, invoice_url):
    """在发票页面彻底完成支付与校验"""
    log(f"💳 正在进入发票页面进行支付: {invoice_url}")
    page.goto(invoice_url, wait_until="domcontentloaded", timeout=60000)
    handle_cloudflare(page)
    time.sleep(3)

    # 1. 检查是否已经是已支付状态
    body_text = page.locator("body").inner_text()
    if ("paid" in body_text.lower() and "unpaid" not in body_text.lower()) or "status: paid" in body_text.lower():
        log("✅ 发票已经是 Paid (已支付) 状态！")
        return True

    # 2. 打印发票页面表单结构供诊断
    try:
        form_info = page.evaluate('''() => {
            const forms = Array.from(document.querySelectorAll('form')).map(f => ({
                action: f.action,
                method: f.method,
                inputs: Array.from(f.querySelectorAll('input')).map(i => ({ name: i.name, type: i.type, value: i.value, checked: i.checked }))
            }));
            const buttons = Array.from(document.querySelectorAll('button, a')).map(b => b.textContent.trim()).filter(t => t.length > 0 && t.length < 40);
            return { forms, buttons };
        }''')
        log(f"📝 发票页面元素: {json.dumps(form_info, ensure_ascii=False)}")
    except Exception:
        pass

    # 3. 滚动到页面底部
    page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
    time.sleep(1)

    # 4. 勾选支付网关单选框与复选框
    page.evaluate('''() => {
        const radios = document.querySelectorAll('input[type="radio"]');
        if (radios.length > 0 && !Array.from(radios).some(r => r.checked)) {
            const pref = Array.from(radios).find(r => /credit|balance|free/i.test(r.value || r.name || r.id)) || radios[0];
            pref.checked = true;
            pref.click();
        }
        const cbs = document.querySelectorAll('input[type="checkbox"]');
        cbs.forEach(cb => {
            if (!cb.checked) {
                cb.checked = true;
                cb.click();
            }
        });
    }''')
    time.sleep(1)

    # 5. 点击支付按钮与真实表单提交
    pay_btn_locators = [
        page.locator('button:has-text("Pay Now")').last,
        page.locator('button:has-text("Pay the Free Invoice")').last,
        page.locator('button:has-text("Pay")').last,
        page.locator('input[type="submit"][value*="Pay"]').last
    ]
    
    clicked = False
    for p_loc in pay_btn_locators:
        if p_loc.count() > 0:
            try:
                p_loc.scroll_into_view_if_needed(timeout=2000)
                box = p_loc.bounding_box()
                if box and box["width"] > 10:
                    log(f"🖱️ 真实鼠标点击 Pay 按钮坐标 ({box['x'] + box['width']/2:.1f}, {box['y'] + box['height']/2:.1f})...")
                    page.mouse.click(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                    clicked = True
                    break
            except Exception as e:
                log(f"⚠️ 坐标点击异常: {e}")

    # 原生 JS requestSubmit 兜底触发真实提交
    page.evaluate('''() => {
        const payBtn = Array.from(document.querySelectorAll('button, input[type="submit"]')).find(el => /pay now|pay/i.test(el.textContent || el.value));
        if (payBtn) {
            const form = payBtn.closest('form');
            if (form) {
                if (typeof form.requestSubmit === 'function') {
                    form.requestSubmit(payBtn);
                } else {
                    payBtn.click();
                    form.submit();
                }
            } else {
                payBtn.click();
            }
        }
    }''')
    log("✅ 支付提交指令已全量发送！")

    # 6. 等待支付确认与状态回写 (拉长为 30 秒)
    log("⏳ 等待支付完成确认（等待 30 秒）...")
    time.sleep(30)
    handle_cloudflare(page)

    # 7. 刷新发票页验证结果
    page.reload(wait_until="domcontentloaded")
    handle_cloudflare(page)
    time.sleep(2)
    after_text = page.locator("body").inner_text()
    if ("paid" in after_text.lower() and "unpaid" not in after_text.lower()) or "status: paid" in after_text.lower():
        log("🎉 验证成功：发票状态已明确变更为 Paid！")
        return True

    log("ℹ️ 发票页面未直接显示 Paid，将在返回管理页后通过到期时间验证。")
    return True

def renew_service_single_attempt(page, server_id, attempt_num, old_due):
    """单次尝试执行完整的续费流程"""
    log(f"\n👉 [第 {attempt_num} 次全流程尝试] 正在进入服务管理页...")
    if page.url != SERVICE_URL:
        page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
    handle_cloudflare(page)
    time.sleep(2)

    # 1. 预检：如果已有未支付的发票，优先尝试结算并验证时间是否变化
    if server_id:
        try:
            unpaid_check_url = f"{BASE_URL}/service/{server_id}/invoices?where=unpaid"
            page.goto(unpaid_check_url, wait_until="domcontentloaded", timeout=30000)
            handle_cloudflare(page)
            time.sleep(2)
            found_invoices = re.findall(r'href=["\']([^"\']*(?:/invoice/|/payment/invoice/)[^"\']*)["\']', page.content(), re.I)
            valid_invoices = [lk for lk in found_invoices if 'download' not in lk.lower() and 'pdf' not in lk.lower()]
            if valid_invoices:
                inv_url = valid_invoices[0]
                target_url = inv_url if inv_url.startswith("http") else f"{BASE_URL}{inv_url if inv_url.startswith('/') else '/' + inv_url}"
                log(f"⚡ 发现已存在未支付发票: {target_url}，进入支付流程...")
                pay_invoice_thoroughly(page, target_url)

                # 结清后返回服务页，校验到期时间是否发生变化
                page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
                handle_cloudflare(page)
                time.sleep(3)
                check_due = get_due_date(page)
                if check_due != old_due and check_due != "未知":
                    log(f"🎉 支付现有未支付账单后，到期时间已成功更新: {old_due} -> {check_due}")
                    return True
                else:
                    log(f"⚠️ 现有发票结算后到期时间仍为 {check_due}，继续执行续费弹窗与新账单流程...")
        except Exception as e:
            log(f"⚠️ 预检发票跳过: {e}")

        if page.url != SERVICE_URL:
            page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
            handle_cloudflare(page)

    # 2. 定位并点击 Renew
    log("🖱️ 准备点击 'Renew' 按钮...")
    renew_btn = page.locator('button:has-text("Renew")')
    create_btn = page.locator('button:has-text("Create Invoice")')

    modal_opened = False
    for sub_i in range(3):
        try:
            renew_btn.wait_for(state="visible", timeout=10000)
            renew_btn.scroll_into_view_if_needed()
            renew_btn.click()
            time.sleep(2)

            page_text = page.locator("body").inner_text()
            if "Renewal Restricted" in page_text or "can only renew" in page_text.lower():
                log("⚠️ 未到续期时间，无法续期。")
                page.screenshot(path="renew_not_allowed.png")
                return "NOT_TIME"

            try:
                create_btn.wait_for(state="visible", timeout=6000)
                modal_opened = True
                log("✅ 弹窗已成功弹出！")
                break
            except:
                page.evaluate('() => { const b = Array.from(document.querySelectorAll("button")).find(el => el.textContent.includes("Renew")); if (b) b.click(); }')
                time.sleep(2)
                if create_btn.is_visible():
                    modal_opened = True
                    log("✅ JS点击成功弹出弹窗！")
                    break
        except Exception as e:
            log(f"⚠️ 弹窗尝试异常: {e}")
            time.sleep(2)

    if not modal_opened:
        log("❌ 弹窗未响应，当前尝试失败。")
        return False

    handle_cloudflare(page)
    log("🖱️ 点击 'Create Invoice'...")
    try:
        create_btn.click(force=True, timeout=5000)
    except Exception:
        page.evaluate('() => { const b = Array.from(document.querySelectorAll("button")).find(el => el.textContent.includes("Create Invoice")); if (b) b.click(); }')

    new_invoice_url = None
    start_wait = time.time()
    initial_pages_count = len(page.context.pages)
    while time.time() - start_wait < 35:
        if "/payment/invoice/" in page.url or "/invoice/" in page.url:
            new_invoice_url = page.url
            log(f"🎉 页面已跳转: {new_invoice_url}")
            break
        if len(page.context.pages) > initial_pages_count:
            new_tab = page.context.pages[-1]
            if "/invoice/" in new_tab.url or "/payment/" in new_tab.url:
                page = new_tab
                new_invoice_url = new_tab.url
                log(f"🎉 检测到新标签页打开: {new_invoice_url}")
                break
        if page.locator('iframe[src*="challenges.cloudflare.com"]').count() > 0:
            handle_cloudflare(page)
        time.sleep(1)

    # 3. 兜底查询未支付发票
    if not new_invoice_url and server_id:
        log("⚠️ 页面未自动跳转，主动前往未支付发票列表查询...")
        try:
            page.goto(f"{BASE_URL}/service/{server_id}/invoices?where=unpaid", wait_until="domcontentloaded", timeout=30000)
            handle_cloudflare(page)
            time.sleep(2)
            found = re.findall(r'href=["\']([^"\']*(?:/invoice/|/payment/invoice/)[^"\']*)["\']', page.content(), re.I)
            valid = [lk for lk in found if 'download' not in lk.lower() and 'pdf' not in lk.lower()]
            if valid:
                new_invoice_url = valid[0] if valid[0].startswith("http") else f"{BASE_URL}{valid[0] if valid[0].startswith('/') else '/' + valid[0]}"
                log(f"🎯 主动匹配到未支付发票: {new_invoice_url}")
        except Exception as e:
            log(f"⚠️ 主动查询发票异常: {e}")

    if not new_invoice_url:
        log("❌ 未能获取到发票 URL。")
        page.screenshot(path="renew_stuck_invoice.png")
        return False

    # 4. 执行发票支付
    pay_invoice_thoroughly(page, new_invoice_url)

    # 5. 返回服务详情页，确认续费后到期时间
    page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
    handle_cloudflare(page)
    time.sleep(3)
    final_due = get_due_date(page)
    if final_due != old_due and final_due != "未知":
        log(f"🎉 到期时间已成功增加: {old_due} -> {final_due}")
        return True
    else:
        log(f"⚠️ 续费操作已执行，但到期时间仍显示为 {final_due}")
        return False

def renew_service(page):
    """外层封装：完整的 5 次重试保护机制"""
    m = re.search(r'/service/(\d+)', SERVICE_URL)
    server_id = m.group(1) if m else ""

    old_due = get_due_date(page)
    log(f"📆 续费前基准到期时间: {old_due}")

    log("➡ 进入续期流程 (最多重试 5 次)...")
    for attempt in range(1, 6):
        log(f"\n==================== 🔄 第 {attempt}/5 次续期全流程尝试 ====================")
        try:
            res = renew_service_single_attempt(page, server_id, attempt, old_due)
            if res == "NOT_TIME":
                return "NOT_TIME"
            if res is True:
                log(f"🎉 第 {attempt} 次全流程续费成功并确认到期时间已更新！")
                return True
        except Exception as e:
            log(f"❌ 第 {attempt} 次尝试异常: {e}")
            page.screenshot(path=f"renew_attempt_{attempt}_error.png")

        if attempt < 5:
            log(f"⚠️ 第 {attempt} 次未确认成功，等待 5 秒后进行第 {attempt+1} 次全流程重试...")
            time.sleep(5)

    log("❌ 经过 5 次完整重试，到期时间未能成功增加。")
    return False

def main():
    if not COOKIE_VALUE and not (EMAIL and PASSWORD):
        log("❌ 缺少登录凭证")
        sys.exit(1)

    global SERVICE_URL

    with sync_playwright() as p:
        try:
            if IS_PROXY:
                log(f"⚙️ 代理已启用: {PROXY_SERVER}")
            else:
                log("🌐 直连模式（未使用代理）")
            
            current_ip = get_current_ip(PROXY_SERVER)
            log(f"🎯 当前出口IP: {current_ip}")

            log("🚀 启动浏览器...")
            browser = p.chromium.launch(
                channel="chrome",
                headless=False,
                args=['--no-sandbox', '--disable-blink-features=AutomationControlled', '--disable-infobars']
            )
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
                proxy={"server": PROXY_SERVER} if IS_PROXY else None
            )
            page = context.new_page()
            page.add_init_script(STEALTH_JS)

            if not login(page):
                sys.exit(1)

            server_id = get_server_id(page)
            if not server_id:
                log("❌ 无法获取 Server ID，退出。")
                sys.exit(1)
            SERVICE_URL = f"{BASE_URL}/service/{server_id}/manage"

            old_due = get_due_date(page)
            log(f"📆 续费前到期时间：{old_due}")

            renew_result = renew_service(page)

            new_due = get_due_date(page)
            log(f"📆 续费后到期时间：{new_due}")

            if renew_result == "NOT_TIME":
                log("⏳ 未到续期时间，目前无法续期")
                status = "⏳ 未到续期时间"
            elif renew_result is False or (new_due == old_due and new_due != "未知"):
                log(f"❌ 续费未生效：续期前后到期时间均为 {new_due}")
                status = "❌ 续期未生效 (到期时间未变)"
            else:
                status = "✅ 续期成功"

            send_telegram_notification(status, old_due, new_due)

            if renew_result == "NOT_TIME":
                sys.exit(0)
            elif status == "✅ 续期成功":
                sys.exit(0)
            else:
                sys.exit(1)
        except Exception as e:
            log(f"❌ 浏览器启动出错: {e}")
            sys.exit(1)
        finally:
            if 'browser' in locals() and browser:
                browser.close()
                
if __name__ == "__main__":
    main()
