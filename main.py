import sys
import os
import json
import time
import random
import requests
import traceback
from urllib.parse import urlparse
from queue import Queue, Empty
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QTextEdit, QLabel, QMessageBox, QGroupBox, QFormLayout, QComboBox
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer

# تأكد من تثبيت gradio_client و playwright-stealth
# pip install gradio_client playwright playwright-stealth requests httpx
from gradio_client import Client as GradioClient
from playwright.sync_api import sync_playwright, Playwright, Browser, Page, BrowserContext, \
    TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError, Locator
import httpx  # استيراد httpx للتعامل مع أخطاء الاتصال
from playwright_stealth import stealth_sync  # تم استيراد stealth_sync
import re  # Added for regular expressions for HTML stripping

# ==============================================================================
# 1. الإعدادات والثوابت
# ==============================================================================

# عنوان البروكسي (قم بتغييره إلى البروكسي الخاص بك)
PROXY_ADDRESS_HTTP_FULL = "http://56c17f936ca45e8b:9qLbCe3s@res.proxy-seller.com:10002"
# عناوين URL المستهدفة
SWAGBUCKS_LOGIN_URL = "https://www.swagbucks.com/p/login"
SWAGBUCKS_DASHBUCKS_URL = "https://www.swagbucks.com/"  # هذا للتحقق اليدوي/التخطي، لن يستخدمه البوت تلقائياً بعد تسجيل الدخول
IP_TEST_URL = "http://ip-api.com/json"

# عناوين URL لخدمات الذكاء الاصطناعي
SELECTOR_AI_URL = "https://serverboot-yourusernamesurveyselectorai.hf.space/"
ANSWER_AI_URL = "https://omran2211-ask.hf.space/"

# مسار حفظ حالة الجلسة
SESSION_STORAGE_PATH = "swagbucks_session_state.json"
SESSION_EXPIRY_HOURS = 4

# إعدادات محاكاة السلوك البشري
TYPING_DELAY_MS = (80, 250)
ACTION_DELAY_MS = (1500, 4000)
SURVEY_NEXT_DELAY_SECONDS = 15

# Viewport Dimensions (أبعاد شاشة عرض عشوائية)
VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1280, "height": 720},
    {"width": 1536, "height": 864},
    {"width": 1024, "height": 768},
]

# User-Agent Strings (سلاسل وكيل مستخدم طبيعية وعناوائية)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
]


# ==============================================================================
# 2. PySide6 Worker Thread
# ==============================================================================

class PlaywrightWorker(QThread):
    status_update = Signal(str)
    browser_ready = Signal(bool)
    login_attempt_complete = Signal(bool)
    survey_ready = Signal(bool)
    error_occurred = Signal(str)
    proxy_test_result = Signal(bool, str)

    def __init__(self, proxy_address, parent=None):
        super().__init__(parent)
        self.proxy_address = proxy_address
        self.command_queue = Queue()
        self._running = True
        self.is_logged_in = False

        # تهيئة عملاء Gradio
        self.selector_ai_client = None
        self.answer_ai_client = None
        self._initialize_gradio_clients()

        self.playwright_instance: Playwright = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        self.page: Page = None
        self.is_survey_automation_active = False
        self.current_persona_id = "01"

    def _initialize_gradio_clients(self):
        """تهيئة أو إعادة تهيئة عملاء Gradio."""
        try:
            if self.selector_ai_client is None:
                self.selector_ai_client = GradioClient(SELECTOR_AI_URL)
                self.status_update.emit(f"✅ تم تهيئة عميل Selector AI بنجاح من: {SELECTOR_AI_URL}")
        except Exception as e:
            self.selector_ai_client = None
            self.error_occurred.emit(f"❌ خطأ مبدئي في تهيئة عميل Selector AI: {e}\n{traceback.format_exc()}")

        try:
            if self.answer_ai_client is None:
                self.answer_ai_client = GradioClient(ANSWER_AI_URL)
                self.status_update.emit(f"✅ تم تهيئة عميل Answer AI بنجاح من: {ANSWER_AI_URL}")
        except Exception as e:
            self.answer_ai_client = None
            self.error_occurred.emit(f"❌ خطأ مبدئي في تهيئة عميل Answer AI: {e}\n{traceback.format_exc()}")

    def run(self):
        self.status_update.emit("خيط Playwright العامل بدأ.")

        try:
            self.playwright_instance = sync_playwright().start()
            self.status_update.emit("Playwright بدأ بنجاح في خيط العامل.")
            self.browser_ready.emit(False)
        except Exception as e:
            self.error_occurred.emit(f"خطأ فادح في بدء Playwright: {e}\n{traceback.format_exc()}")
            self._running = False
            self.browser_ready.emit(False)
            self._close_playwright_resources()
            return

        while self._running:
            try:
                command, args, kwargs = self.command_queue.get(timeout=0.1)

                if command == "shutdown":
                    self._running = False
                    self.status_update.emit("تلقى أمر الإغلاق. جاري إيقاف الخيط.")
                    break

                elif command == "start_browser_session":
                    self._start_browser_session()

                elif command == "navigate_to_url":
                    self._navigate_to_url(*args, **kwargs)

                elif command == "perform_login":
                    self._perform_login(*args, **kwargs)

                elif command == "test_proxy_requests":
                    self._test_http_connection_requests_task(*args, **kwargs)

                elif command == "set_persona_id":
                    self.current_persona_id = args[0]
                    self.status_update.emit(f"تم تعيين Persona ID إلى: {self.current_persona_id}")

                elif command == "confirm_login_and_save_session":
                    self.is_logged_in = True
                    self._save_session_state()
                    self.status_update.emit("✅ تم تأكيد تسجيل الدخول يدوياً وحفظ الجلسة.")
                    self.login_attempt_complete.emit(True)

                elif command == "start_survey_automation":
                    if self.is_logged_in:
                        self._start_survey_automation()
                    else:
                        self.error_occurred.emit("لا يمكن بدء الأتمتة. يرجى تسجيل الدخول وتأكيد الجلسة أولاً.")

                elif command == "stop_survey_automation":
                    self._stop_survey_automation()

                elif command == "answer_survey_question":
                    self._answer_survey_question()

                elif command == "stop_browser_session":
                    self._close_browser_only()
                    self.is_logged_in = False

            except Empty:
                pass
            except Exception as e:
                self.error_occurred.emit(f"خطأ في معالجة الأمر في خيط العامل: {e}\n{traceback.format_exc()}")

            if self.is_survey_automation_active and self.page:
                pass

        self._close_playwright_resources()
        self.status_update.emit("خيط Playwright العامل توقف.")

    def send_command(self, command: str, *args, **kwargs):
        """ترسل أمرًا إلى قائمة انتظار الأوامر الخاصة بخيط العامل."""
        if self._running:
            self.command_queue.put((command, args, kwargs))
        else:
            self.error_occurred.emit(f"لا يمكن إرسال الأمر '{command}'. خيط العامل غير نشط.")

    def _handle_new_page(self, new_page: Page):
        """
        يتم استدعاء هذه الدالة عندما يفتح المتصفح صفحة جديدة (تبويبة).
        تقوم بتحديث مرجع self.page إلى الصفحة الجديدة وتنتظر تحميلها.
        """
        self.status_update.emit(f"⚠️ تم اكتشاف صفحة جديدة (تبويبة). URL: {new_page.url}")
        if self.page and self.page != new_page:
            try:
                self.status_update.emit(f"جاري إغلاق الصفحة القديمة: {self.page.url}")
            except Exception as e:
                self.error_occurred.emit(f"خطأ أثناء إغلاق الصفحة القديمة: {e}")

        self.page = new_page
        self.status_update.emit(f"✅ تم التبديل إلى الصفحة الجديدة: {self.page.url}")
        try:
            self.page.wait_for_load_state('load', timeout=30000)
            self.status_update.emit(f"✅ تم تحميل DOM للصفحة الجديدة: {self.page.url}")
            self.page.wait_for_load_state('networkidle', timeout=30000)
            self.status_update.emit(f"✅ تم استقرار الشبكة للصفحة الجديدة: {self.page.url}")
        except PlaywrightTimeoutError:
            self.error_occurred.emit(f"مهلة انتظار تحميل/استقرار الصفحة الجديدة: {self.page.url}")
        except Error as e:
            self.error_occurred.emit(f"خطأ Playwright أثناء انتظار تحميل الصفحة الجديدة: {e}\n{traceback.format_exc()}")
        except Exception as e:
            self.error_occurred.emit(f"خطأ عام أثناء انتظار تحميل الصفحة الجديدة: {e}\n{traceback.format_exc()}")

    def _start_browser_session(self):
        """يبدأ جلسة Playwright ويجهز المتصفح."""
        self.status_update.emit("جاري بدء جلسة المتصفح...")
        try:
            parsed_proxy = urlparse(self.proxy_address)
            playwright_proxy_config = {
                'server': f"{parsed_proxy.scheme}://{parsed_proxy.hostname}:{parsed_proxy.port}"
            }
            if parsed_proxy.username:
                playwright_proxy_config['username'] = parsed_proxy.username
            if parsed_proxy.password:
                playwright_proxy_config['password'] = parsed_proxy.password

            selected_user_agent = random.choice(USER_AGENTS)
            selected_viewport = random.choice(VIEWPORTS)

            if self.browser:
                self.browser.close()
                self.browser = None
                self.context = None
                self.page = None
                self.is_logged_in = False

            self.browser = self.playwright_instance.firefox.launch(
                headless=False,
                proxy=playwright_proxy_config
            )

            if os.path.exists(SESSION_STORAGE_PATH):
                with open(SESSION_STORAGE_PATH, 'r') as f:
                    session_data = json.load(f)

                saved_timestamp = session_data.get('timestamp')
                if saved_timestamp and (time.time() - saved_timestamp < SESSION_EXPIRY_HOURS * 3600):
                    self.status_update.emit("تم العثور على جلسة سابقة صالحة. جاري تحميلها.")
                    self.context = self.browser.new_context(
                        storage_state=session_data['state'],
                        user_agent=selected_user_agent,
                        viewport=selected_viewport,
                        locale="en-US"
                    )
                    self.is_logged_in = True
                    self.status_update.emit("✅ تم تحميل الجلسة بنجاح، مفترض تسجيل الدخول.")
                else:
                    self.status_update.emit("الجلسة السابقة منتهية الصلاحية أو غير موجودة. جاري بدء جلسة جديدة.")
                    self.context = self.browser.new_context(
                        user_agent=selected_user_agent,
                        viewport=selected_viewport,
                        locale="en-US"
                    )
                    self.is_logged_in = False
            else:
                self.status_update.emit("لم يتم العثور على ملف جلسة. جاري بدء جلسة جديدة.")
                self.context = self.browser.new_context(
                    user_agent=selected_user_agent,
                    viewport=selected_viewport,
                    locale="en-US"
                )
                self.is_logged_in = False

            self.context.on("page", lambda page: self._handle_new_page(page))
            self.status_update.emit("تم إعداد مستمع الصفحات الجديدة.")

            self.page = self.context.new_page()
            self.page.set_default_timeout(60000)

            stealth_sync()
            self.status_update.emit("تم تطبيق تقنيات التخفي Playwright-Stealth.")

            self.browser_ready.emit(True)
            self.status_update.emit("المتصفح جاهز للعمل.")

        except Exception as e:
            self.error_occurred.emit(f"خطأ في بدء جلسة المتصفح: {e}\n{traceback.format_exc()}")
            self.browser_ready.emit(False)
            self.is_logged_in = False

    def _close_browser_only(self):
        """يغلق المتصفح فقط دون إيقاف Playwright instance."""
        self.status_update.emit("جاري إغلاق المتصفح فقط...")
        if self.browser:
            try:
                self.browser.close()
                self.status_update.emit("تم إغلاق المتصفح.")
            except Exception as e:
                self.error_occurred.emit(f"خطأ أثناء إغلاق المتصفح: {e}")
            self.browser = None
            self.context = None
            self.page = None
            self.is_logged_in = False
        self.browser_ready.emit(False)

    def _close_playwright_resources(self):
        """يغلق موارد Playwright (المتصفح والمثيل)."""
        self.status_update.emit("جاري إغلاق موارد Playwright...")
        if self.browser:
            self._close_browser_only()

        if self.playwright_instance:
            try:
                self.playwright_instance.stop()
                self.status_update.emit("تم إيقاف Playwright.")
            except Exception as e:
                self.error_occurred.emit(f"خطأ أثناء إيقاف Playwright: {e}")
            self.playwright_instance = None
        self.browser_ready.emit(False)
        self.is_logged_in = False
        self.status_update.emit("تم إغلاق موارد Playwright.")

    def _navigate_to_url(self, target_url: str):
        """ينتقل إلى URL المستهدف."""
        if not self.page or self.page.is_closed():
            self.error_occurred.emit("Playwright ليس جاهزًا (لا توجد صفحة). يرجى تشغيل المتصفح أولاً.")
            return

        self.status_update.emit(f"جاري الانتقال إلى: {target_url}")
        try:
            self.page.evaluate("window.scrollTo(0, document.body.scrollHeight / 4)")
            time.sleep(random.uniform(0.5, 1.5))

            self.page.goto(target_url, wait_until='domcontentloaded')

            self.page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            time.sleep(random.uniform(0.5, 1.5))

            current_url = self.page.url
            current_title = self.page.title()
            self.status_update.emit(f"✅ تم الوصول إلى URL: {current_url} بنجاح! العنوان: {current_title}")
            time.sleep(random.uniform(*ACTION_DELAY_MS) / 1000)
        except PlaywrightTimeoutError as e:
            self.error_occurred.emit(
                f"خطأ مهلة Playwright أثناء التنقل إلى {target_url}: {e}\nقد يكون البروكسي بطيئًا جدًا أو الموقع لا يستجيب.")
            self.status_update.emit(f"URL الحالي عند المهلة: {self.page.url}")
        except Exception as e:
            self.error_occurred.emit(
                f"حدث خطأ غير متوقع أثناء التنقل بـ Playwright إلى {target_url}: {e}\n{traceback.format_exc()}")
            self.status_update.emit(f"URL الحالي عند الخطأ: {self.page.url}")

    def _test_http_connection_requests_task(self, proxy_address: str):
        self.status_update.emit(f"جاري اختبار اتصال HTTP/HTTPS عبر Requests عبر: {proxy_address}")
        try:
            proxies = {
                "http": proxy_address,
                "https": proxy_address
            }

            response = requests.get(IP_TEST_URL, proxies=proxies, timeout=15)
            response.raise_for_status()

            data = response.json()
            if data.get('status') == 'success':
                self.proxy_test_result.emit(True,
                                            f"✅ نجاح اختبار البروكسي (Requests - HTTP)! IP: {data['query']}, البلد: {data['country']}")
            else:
                self.proxy_test_result.emit(False, f"❌ فشل اختبار البروكسي (Requests - HTTP): {data}")

        except requests.exceptions.ProxyError as pe:
            self.proxy_test_result.emit(False,
                                        f"❌ خطأ في البروكسي (Requests - ProxyError): {pe}\nيرجى التحقق من صحة عنوان البروكسي، المنفذ، واسم المستخدم/كلمة المرور.")
        except requests.exceptions.ConnectionError as ce:
            self.proxy_test_result.emit(False,
                                        f"❌ خطأ في الاتصال (Requests - ConnectionError): {ce}\nقد يكون البروكسي غير متاح أو هناك مشكلة في الشبكة.")
        except requests.exceptions.Timeout:
            self.proxy_test_result.emit(False,
                                        "❌ انتهت مهلة الاتصال بالبروكسي (Requests).\nقد يكون البروكسي بطيئاً جداً أو غير مستجيب.")
        except requests.exceptions.HTTPError as he:
            self.proxy_test_result.emit(False,
                                        f"❌ خطأ HTTP (Requests - HTTPError): {he}\nقد تكون المصادقة غير صحيحة أو البروكسي يرفض الاتصال.")
        except Exception as e:
            self.proxy_test_result.emit(False,
                                        f"❌ حدث خطأ غير متوقع أثناء اختبار البروكسي (Requests - HTTP): {e}\n{traceback.format_exc()}")

    def _save_session_state(self):
        """يحفظ حالة الجلسة (ملفات تعريف الارتباط والتخزين المحلي) إلى ملف."""
        if self.context:
            try:
                state = self.context.storage_state()
                session_data = {
                    'state': state,
                    'timestamp': time.time()
                }
                with open(SESSION_STORAGE_PATH, 'w') as f:
                    json.dump(session_data, f)
                self.status_update.emit("تم حفظ حالة الجلسة بنجاح.")
            except Exception as e:
                self.error_occurred.emit(f"خطأ في حفظ حالة الجلسة: {e}")
        else:
            self.status_update.emit("لا توجد جلسة متصفح لحفظها.")

    def _type_slowly_and_humanlike(self, selector: str, text: str):
        if not self.page or self.page.is_closed():
            self.error_occurred.emit("لا توجد صفحة متصفح نشطة للكتابة فيها.")
            return

        self.status_update.emit(f"جاري الكتابة ببطء في حقل '{selector}'...")
        try:
            element = self.page.wait_for_selector(selector, state='visible', timeout=10000)
            if not element:
                self.error_occurred.emit(f"لم يتم العثور على العنصر '{selector}' للكتابة فيه.")
                return

            bounding_box = element.bounding_box()
            if bounding_box:
                x_center = bounding_box['x'] + bounding_box['width'] / 2
                y_center = bounding_box['y'] + bounding_box['height'] / 2
                x_rand = x_center + random.uniform(-bounding_box['width'] * 0.2, bounding_box['width'] * 0.2)
                y_rand = y_center + random.uniform(-bounding_box['height'] * 0.2, bounding_box['height'] * 0.2)
                self.page.mouse.move(x_rand, y_rand, steps=random.randint(5, 15))
                time.sleep(random.uniform(0.1, 0.5))
                self.page.mouse.click(x_rand, y_rand)
                time.sleep(random.uniform(0.1, 0.3))

            self.page.fill(selector, "")
            for char in text:
                self.page.type(selector, char, delay=random.randint(*TYPING_DELAY_MS))
            self.status_update.emit(f"تم الانتهاء من الكتابة في {selector}.")
            time.sleep(random.uniform(*ACTION_DELAY_MS) / 1000)
        except PlaywrightTimeoutError:
            self.error_occurred.emit(f"مهلة انتظار المحدد '{selector}' أثناء الكتابة.")
        except Exception as e:
            self.error_occurred.emit(f"خطأ أثناء الكتابة ببطء في '{selector}': {e}\n{traceback.format_exc()}")

    def _click_humanlike(self, selector: str, dispatch_change_event: bool = False):
        if not self.page or self.page.is_closed():
            self.error_occurred.emit("لا توجد صفحة متصفح نشطة للنقر فيها.")
            return

        self.status_update.emit(f"جاري النقر بشكل طبيعي على '{selector}'...")
        try:
            element = self.page.wait_for_selector(selector, state='visible', timeout=10000)
            if not element:
                self.error_occurred.emit(f"لم يتم العثور على العنصر '{selector}' للنقر عليه.")
                return

            try:
                element.scroll_into_view_if_needed()
                time.sleep(random.uniform(0.2, 0.5))
            except Exception as scroll_e:
                self.status_update.emit(f"⚠️ فشل التمرير إلى العنصر '{selector}': {scroll_e}")

            bounding_box = element.bounding_box()
            if bounding_box:
                x_center = bounding_box['x'] + bounding_box['width'] / 2
                y_center = bounding_box['y'] + bounding_box['height'] / 2
                x_rand = x_center + random.uniform(-bounding_box['width'] * 0.2, bounding_box['width'] * 0.2)
                y_rand = y_center + random.uniform(-bounding_box['height'] * 0.2, bounding_box['height'] * 0.2)
                self.page.mouse.move(x_rand, y_rand, steps=random.randint(5, 15))
                time.sleep(random.uniform(0.1, 0.5))
                self.page.mouse.click(x_rand, y_rand)
            else:
                element.click()

            if dispatch_change_event:
                try:
                    self.page.evaluate("el => el.dispatchEvent(new Event('change', {bubbles: true}))", element)
                    self.status_update.emit(f"✅ تم إطلاق حدث 'change' للعنصر '{selector}'.")
                except Exception as eval_e:
                    self.status_update.emit(f"⚠️ فشل إطلاق حدث 'change' للعنصر '{selector}': {eval_e}")

            self.status_update.emit(f"✅ تم النقر على '{selector}'.")
            time.sleep(random.uniform(*ACTION_DELAY_MS) / 1000)
        except PlaywrightTimeoutError:
            self.error_occurred.emit(f"مهلة انتظار المحدد '{selector}' أثناء النقر.")
        except Exception as e:
            self.error_occurred.emit(f"خطأ أثناء النقر بشكل طبيعي على '{selector}': {e}\n{traceback.format_exc()}")

    def _perform_login(self, username, password):
        """يقوم بتسجيل الدخول إلى Swagbucks (فقط إدخال البيانات والنقر)."""
        if not self.page or self.page.is_closed():
            self.error_occurred.emit("لا توجد صفحة متصفح نشطة لتسجيل الدخول.")
            self.login_attempt_complete.emit(False)
            return

        self.status_update.emit(f"جاري محاولة إدخال بيانات تسجيل الدخول لـ: {username} على {self.page.url}")
        try:
            if SWAGBUCKS_LOGIN_URL not in self.page.url:
                self.status_update.emit(f"⚠️ لست على صفحة تسجيل الدخول. URL الحالي: {self.page.url}. جاري الانتقال...")
                self._navigate_to_url(SWAGBUCKS_LOGIN_URL)
                self.page.wait_for_load_state('domcontentloaded', timeout=10000)

            self.page.wait_for_selector('input#sbxJxRegEmail', state='visible', timeout=20000)
            self.page.wait_for_selector('input#sbxJxRegPswd', state='visible', timeout=20000)
            self.page.wait_for_selector('button#loginBtn', state='visible', timeout=20000)
            self.status_update.emit("✅ تم العثور على حقول تسجيل الدخول وزر الدخول.")

            self._type_slowly_and_humanlike('input#sbxJxRegEmail', username)
            self._type_slowly_and_humanlike('input#sbxJxRegPswd', password)

            self.status_update.emit("جاري الضغط على زر تسجيل الدخول. يرجى المراقبة يدوياً.")
            self._click_humanlike('button#loginBtn')

            self.status_update.emit("✅ تم إدخال بيانات تسجيل الدخول والنقر على الزر. يرجى التأكيد يدوياً.")
            self.login_attempt_complete.emit(True)
            self.is_logged_in = False

        except PlaywrightTimeoutError:
            self.error_occurred.emit(
                f"مهلة Playwright أثناء إدخال بيانات تسجيل الدخول. URL الحالي: {self.page.url}")
            self.login_attempt_complete.emit(False)
        except Exception as e:
            self.error_occurred.emit(f"خطأ أثناء عملية إدخال بيانات تسجيل الدخول: {e}\n{traceback.format_exc()}")
            self.login_attempt_complete.emit(False)

    def _extract_full_html_content(self) -> str:
        """
        يستخرج كامل محتوى HTML للصفحة الحالية.
        """
        if not self.page or self.page.is_closed():
            self.error_occurred.emit("لا توجد صفحة متصفح نشطة لاستخراج محتوى HTML منها.")
            return ""

        self.status_update.emit(f"جاري استخراج كامل محتوى HTML من الصفحة الحالية: {self.page.url}...")
        try:
            full_html = self.page.content()
            self.status_update.emit("✅ تم استخراج كامل محتوى HTML بنجاح.")
            self.status_update.emit(
                f"--- بداية المحتوى المستخرج ---\n{full_html[:1000]}...\n--- نهاية المحتوى المستخرج ---")
            return full_html
        except PlaywrightError as e:
            self.error_occurred.emit(
                f"خطأ في استخراج كامل محتوى HTML (Playwright): {e}\n{traceback.format_exc()}")
            return ""
        except Exception as e:
            self.error_occurred.emit(f"خطأ عام في استخراج كامل محتوى HTML: {e}\n{traceback.format_exc()}")
            return ""

    def _call_selector_ai(self, page_data: str):
        self.status_update.emit("جاري استدعاء Selector AI...")
        if self.selector_ai_client is None:
            self._initialize_gradio_clients()
            if self.selector_ai_client is None:
                self.error_occurred.emit("عميل Selector AI غير مهيأ. لا يمكن استدعاء API.")
                return {"input_type": "error", "error": "Selector AI client not initialized.", "traceback": ""}

        max_retries = 3
        current_retry = 0
        while current_retry < max_retries:
            try:
                result = self.selector_ai_client.predict(
                    page_data,
                    False,
                    api_name="/identify_selectors"
                )

                selectors = json.loads(result)
                self.status_update.emit(f"✅ تم استلام المحددات من Selector AI: {selectors}")
                return selectors
            except (json.JSONDecodeError, httpx.ConnectTimeout, httpx.RequestError) as e:
                current_retry += 1
                self.error_occurred.emit(
                    f"❌ خطأ في استدعاء Selector AI (المحاولة {current_retry}/{max_retries}): {e}\nالاستجابة الخام: '{result if 'result' in locals() else 'N/A'}'\n{traceback.format_exc()}")
                if current_retry < max_retries:
                    time.sleep(random.uniform(5, 10))
                else:
                    self.error_occurred.emit(f"❌ فشل استدعاء Selector AI بعد {max_retries} محاولات.")
                    return {"input_type": "error", "error": f"Error calling Selector AI: {e}",
                            "traceback": traceback.format_exc()}
            except Exception as e:
                self.error_occurred.emit(f"خطأ في استدعاء Selector AI عبر Gradio Client: {e}\n{traceback.format_exc()}")
                return {"input_type": "error", "error": f"Error calling Selector AI: {e}",
                        "traceback": traceback.format_exc()}

    def _call_answer_ai(self, persona_id: str, question_text: str, options_str: str, question_type: str):
        self.status_update.emit("جاري استدعاء Answer AI...")
        if self.answer_ai_client is None:
            self._initialize_gradio_clients()
            if self.answer_ai_client is None:
                self.error_occurred.emit("عميل Answer AI غير مهيأ. لا يمكن استدعاء API.")
                return None

        question_payload = {
            "questions": [
                {
                    "unescaped_question_text": question_text,
                    "input_type": question_type,
                    "options_labels": [opt.strip() for opt in options_str.split(',') if
                                       opt.strip()] if options_str else []
                }
            ]
        }
        raw_questions_json_to_send = json.dumps(question_payload, ensure_ascii=False, indent=2)

        self.status_update.emit(
            f"--- بداية بيانات Answer AI المرسلة ---\n{raw_questions_json_to_send}\n--- نهاية بيانات Answer AI المرسلة ---")

        max_retries = 3
        current_retry = 0
        while current_retry < max_retries:
            result = None
            try:
                result = self.answer_ai_client.predict(
                    persona_id,
                    raw_questions_json_to_send,
                    api_name="/run_persona_simulation",
                    fn_index=0,
                )

                if not result:
                    self.error_occurred.emit(f"❌ استجابة فارغة من Answer AI. السؤال: {question_text}")
                    return None

                try:
                    answer_data = json.loads(result)
                except json.JSONDecodeError:
                    # إذا فشل التحويل، نفترض أنه نص عادي ونقوم بتحليله يدوياً
                    self.status_update.emit("⚠️ استجابة Answer AI ليست JSON. جاري محاولة تحليلها كنص عادي.")

                    # البحث عن الأجزاء المهمة باستخدام regex
                    question_match = re.search(r'\*\*Question:\*\*\s*(.*?)\s*\*\*Recommended Option\(s\):', result,
                                               re.DOTALL)
                    options_match = re.search(
                        r'\*\*Recommended Option\(s\):\*\*\s*(.*?)\s*\*\*Detailed Persona Answer:', result, re.DOTALL)
                    answer_match = re.search(r'\*\*Detailed Persona Answer:\*\*\s*(.*?)\s*---', result, re.DOTALL)

                    question_text_parsed = question_match.group(1).strip() if question_match else ""
                    recommended_options_parsed = options_match.group(1).strip() if options_match else ""
                    detailed_answer_parsed = answer_match.group(1).strip() if answer_match else ""

                    # بناء قاموس بنفس الهيكل المتوقع
                    answer_data = {
                        "unescaped_question_text": question_text_parsed,
                        "recommended_options": recommended_options_parsed,
                        "detailed_persona_answer": detailed_answer_parsed,
                    }

                self.status_update.emit(f"--- بداية رد Answer AI ---")
                self.status_update.emit(json.dumps(answer_data, indent=2, ensure_ascii=False))
                self.status_update.emit(f"--- نهاية رد Answer AI ---")

                self.status_update.emit(
                    f"✅ تم استلام الإجابة من Answer AI: {answer_data.get('detailed_persona_answer', 'N/A')}")
                return answer_data
            except (httpx.ConnectTimeout, httpx.RequestError) as e:
                current_retry += 1
                self.error_occurred.emit(
                    f"❌ خطأ في استدعاء Answer AI (المحاولة {current_retry}/{max_retries}): {e}\nالاستجابة الخام: '{result if 'result' in locals() else 'N/A'}'\n{traceback.format_exc()}")
                if current_retry < max_retries:
                    time.sleep(random.uniform(5, 10))
                else:
                    self.error_occurred.emit(f"❌ فشل استدعاء Answer AI بعد {max_retries} محاولات.")
                    return None
            except Exception as e:
                self.error_occurred.emit(
                    f"خطأ عام في استدعاء Answer AI عبر Gradio Client: {e}\n{traceback.format_exc()}")
                return None
        return None

    def _get_element_by_text_content(self, page: Page, text_content: str, parent_element: Locator = None, timeout=5000):
        """
        Searches for an element that contains the given text content within its textContent.
        Can search within a parent_element or the entire page.
        Returns a Playwright Locator.
        """
        # Escape special regex characters in the text, but keep spaces flexible.
        escaped_text = re.sub(r'[\-\[\]{}()*+?.,\\^$|#]', r'\\\g<0>', text_content).replace(' ', r'\s*')

        selectors = [
            f"text=/{escaped_text}/i",  # Case-insensitive text match with flexible whitespace
            f"label:has-text('{text_content}')",
            f"span:has-text('{text_content}')",
            f"div:has-text('{text_content}')",
            f"li:has-text('{text_content}')",
            f"*[aria-label*='{text_content}']",  # Check for aria-label containing text
            f"*[title*='{text_content}']",  # Check for title containing text
        ]

        target_element = None
        for sel in selectors:
            self.status_update.emit(f"🔎 Trying selector: '{sel}' to find element with text '{text_content}'")
            try:
                if parent_element:
                    target_element = parent_element.locator(sel).first.wait_for(state='visible', timeout=timeout)
                else:
                    target_element = page.locator(sel).first.wait_for(state='visible', timeout=timeout)
                if target_element:
                    self.status_update.emit(f"✅ Found element for text '{text_content}' using selector: {sel}")
                    return target_element
            except PlaywrightTimeoutError:
                self.status_update.emit(f"❌ Failed to find element with selector: '{sel}'")
                continue
            except Exception as e:
                self.status_update.emit(
                    f"⚠️ Error finding element with selector '{sel}' for text '{text_content}': {e}")
                continue
        self.status_update.emit(
            f"⛔️ Failed to find any visible element for text: '{text_content}' after trying all selectors.")
        return None

    def _answer_survey_question(self):
        if not self.is_logged_in:
            self.error_occurred.emit("لا يمكن الإجابة على الاستبيان. يجب تسجيل الدخول وتأكيد الجلسة أولاً.")
            self.survey_ready.emit(False)
            return

        if not self.page or self.page.is_closed():
            self.error_occurred.emit("لا توجد صفحة متصفح نشطة للإجابة على الاستبيان.")
            self.survey_ready.emit(False)
            if self.is_survey_automation_active:
                QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                  lambda: self.send_command("answer_survey_question"))
            return

        self.status_update.emit(f"جاري معالجة سؤال الاستبيان في URL: {self.page.url}...")
        try:
            page_data = self._extract_full_html_content()

            if not page_data:
                self.error_occurred.emit("فشل استخراج بيانات الصفحة للاستبيان. جاري المحاولة مرة أخرى بعد قليل.")
                self.survey_ready.emit(False)
                QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                  lambda: self.send_command("answer_survey_question"))
                return

            selectors = self._call_selector_ai(page_data)

            if not selectors or selectors.get("input_type") == "error":
                self.error_occurred.emit(
                    f"فشل Selector AI في تحديد العناصر: {selectors.get('error', 'None')}. جاري المحاولة مرة أخرى بعد قليل.")
                self.survey_ready.emit(False)
                QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                  lambda: self.send_command("answer_survey_question"))
                return

            # Check for survey completion/end scenarios
            if selectors.get("input_type") == "end_of_survey":
                self.status_update.emit("🎉 تم اكتشاف نهاية الاستبيان! جاري إيقاف الأتمتة.")
                self._stop_survey_automation()
                return
            if selectors.get("input_type") == "no_questions_found" or not selectors.get('questions'):
                self.status_update.emit("⚠️ Selector AI لم يعثر على أسئلة. قد تكون نهاية الاستبيان أو مشكلة.")
                # Attempt to click any common 'continue' or 'next' button if survey is truly over
                common_continue_selectors = [
                    "button:has-text('Submit')", "button:has-text('Continue')", "button:has-text('Next')",
                    "a:has-text('Submit')", "a:has-text('Continue')", "a:has-text('Next')",
                    "input[type='submit']", "input[type='button']",
                ]
                for sel in common_continue_selectors:
                    try:
                        self.status_update.emit(f"محاولة النقر على زر 'متابعة/إنهاء' محتمل: {sel}")
                        self._click_humanlike(sel)
                        self.status_update.emit("✅ تم النقر على زر 'متابعة/إنهاء'. جاري انتظار تحميل الصفحة التالية.")
                        self.page.wait_for_load_state('domcontentloaded', timeout=10000)
                        QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                          lambda: self.send_command("answer_survey_question"))
                        return
                    except Exception:
                        continue  # Try next selector

                self.error_occurred.emit(
                    "Selector AI لم يعد أي أسئلة صالحة ولم يتم العثور على زر 'متابعة/إنهاء'. قد لا تكون هذه صفحة استبيان أو انتهى الاستبيان. جاري المحاولة مرة أخرى بعد قليل.")
                self.survey_ready.emit(False)
                QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                  lambda: self.send_command("answer_survey_question"))
                return

            first_question_info = selectors.get("questions")[0] if selectors.get("questions") else {}
            question_text_for_ai = first_question_info.get("question_text", "")
            options_from_selector_ai = first_question_info.get("options_labels", [])  # This is crucial
            input_type = first_question_info.get("input_type", "unknown")
            submit_button_selector = selectors.get("submit_button_selector")

            # Prioritize question text from Selector AI
            question_text_from_page = question_text_for_ai
            self.status_update.emit(f"❓ السؤال الذي سيتم إرساله إلى Answer AI: {question_text_from_page}")

            # Prepare options for Answer AI. Use what Selector AI provided.
            options_str_for_ai = ", ".join(options_from_selector_ai)
            self.status_update.emit(f"📝 الخيارات التي تم الحصول عليها من Selector AI: {options_from_selector_ai}")

            answer_data = self._call_answer_ai(self.current_persona_id, question_text_from_page, options_str_for_ai,
                                               input_type)
            if not answer_data:
                self.error_occurred.emit("فشل Answer AI في تقديم إجابة. جاري المحاولة مرة أخرى بعد قليل.")
                self.survey_ready.emit(False)
                QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                  lambda: self.send_command("answer_survey_question"))
                return

            recommended_options_raw = answer_data.get("recommended_options", "").strip()
            detailed_persona_answer = answer_data.get("detailed_persona_answer", "").strip()

            self.status_update.emit(f"نوع السؤال: {input_type}, الإجابة الموصى بها (خام): {recommended_options_raw}")
            self.status_update.emit(f"🤖 إجابة الذكاء الاصطناعي المفصلة: {detailed_persona_answer}")

            def css_escape_for_click(s):
                s = s.replace("'", "\\'").replace('"', '\\"').replace('\\', '\\\\')
                s = s.replace('$', '\\$')
                s = s.replace(',', '\\,')
                s = s.replace('.', '\\.')
                s = s.replace('#', '\\#')
                s = s.replace(':', '\\:')
                s = s.replace(';', '\\;')
                s = s.replace('(', '\\(')
                s = s.replace(')', '\\)')
                s = s.replace('[', '\\[')
                s = s.replace(']', '\\]')
                s = s.replace('=', '\\=')
                s = s.replace('>', '\\>')
                s = s.replace('+', '\\+')
                s = s.replace('~', '\\~')
                s = s.replace('*', '\\*')
                s = s.replace('^', '\\^')
                s = s.replace('|', '\\|')
                s = s.replace('&', '\\&')
                s = s.replace('!', '\\!')
                s = s.replace('@', '\\@')
                s = s.replace('%', '\\%')
                return s

            if input_type in ["text", "number", "textarea"]:
                if detailed_persona_answer:
                    # Attempt to find the input field using selectors provided by Selector AI
                    input_selector_candidates = first_question_info.get("option_input_selector", "").split(',')
                    input_found = False
                    for sel in input_selector_candidates:
                        sel = sel.strip()
                        if not sel: continue
                        try:
                            self.page.wait_for_selector(sel, state='visible', timeout=2000)
                            self._type_slowly_and_humanlike(sel, detailed_persona_answer)
                            input_found = True
                            break
                        except PlaywrightTimeoutError:
                            self.status_update.emit(f"لم يتم العثور على حقل الإدخال باستخدام المحدد: {sel}")
                            continue
                    if not input_found:
                        self.error_occurred.emit(
                            f"لم يتم العثور على حقل إدخال صالح باستخدام أي من المحددات: {input_selector_candidates}. جاري المحاولة مرة أخرى بعد قليل.")
                        QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                          lambda: self.send_command("answer_survey_question"))
                        return
                else:
                    self.error_occurred.emit(
                        "لا توجد إجابة نصية للنوع النصي. جاري المحاولة مرة أخرى بعد قليل.")
                    QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                      lambda: self.send_command("answer_survey_question"))
                    return
            elif input_type in ["single_select", "multi_select"]:
                if recommended_options_raw and recommended_options_raw.lower() not in ['n/a',
                                                                                       'no_selection_applicable']:
                    chosen_options_texts = [opt.strip() for opt in recommended_options_raw.split(',') if opt.strip()]
                    if chosen_options_texts:
                        for chosen_opt_text in chosen_options_texts:
                            self.status_update.emit(f"جاري محاولة النقر على الخيار: '{chosen_opt_text}'")

                            # Attempt to find the element by text first
                            option_element_to_click = self._get_element_by_text_content(self.page, chosen_opt_text,
                                                                                        timeout=10000)

                            if option_element_to_click:
                                try:
                                    # Try to find the actual input (radio/checkbox) associated with the found element
                                    input_to_click = option_element_to_click.query_selector(
                                        'input[type="radio"], input[type="checkbox"]')

                                    if input_to_click and not input_to_click.is_checked():
                                        input_to_click.click()
                                        self.page.evaluate(
                                            "el => el.dispatchEvent(new Event('change', {bubbles: true}))",
                                            input_to_click)
                                        self.status_update.emit(
                                            f"✅ تم النقر على input للخيار: {chosen_opt_text} وإطلاق حدث التغيير.")
                                    elif input_to_click and input_to_click.is_checked():
                                        self.status_update.emit(
                                            f"⚠️ الخيار '{chosen_opt_text}' محدد مسبقًا. لا حاجة للنقر.")
                                    else:
                                        # If no direct input found, click the containing element itself
                                        option_element_to_click.click()
                                        self.page.evaluate(
                                            "el => el.dispatchEvent(new Event('change', {bubbles: true}))",
                                            option_element_to_click)
                                        self.status_update.emit(
                                            f"✅ تم النقر على العنصر الحاوي للخيار: {chosen_opt_text} وإطلاق حدث التغيير.")
                                    time.sleep(random.uniform(1.0, 3.0))
                                except Exception as e:
                                    self.error_occurred.emit(
                                        f"خطأ أثناء النقر على الخيار '{chosen_opt_text}': {e}\n{traceback.format_exc()}. جاري المحاولة مرة أخرى بعد قليل.")
                                    QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                                      lambda: self.send_command("answer_survey_question"))
                                    return
                            else:
                                self.error_occurred.emit(
                                    f"لم يتم العثور على الخيار '{chosen_opt_text}' في الصفحة خلال المهلة باستخدام أي محدد. URL الحالي: {self.page.url}. جاري المحاولة مرة أخرى بعد قليل.")
                                QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                                  lambda: self.send_command("answer_survey_question"))
                                return
                    else:
                        self.status_update.emit(
                            f"⚠️ Answer AI لم يوصِ بخيار محدد لنوع {input_type}. لن يتم النقر على أي خيار. جاري المحاولة مرة أخرى بعد قليل.")
                        QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                          lambda: self.send_command("answer_survey_question"))
                        return
                else:
                    self.status_update.emit(
                        "لا توجد خيارات موصى بها للنوع الاختياري. جاري المحاولة مرة أخرى بعد قليل.")
                    QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                      lambda: self.send_command("answer_survey_question"))
                    return
            elif input_type == "grid":
                if recommended_options_raw:
                    grid_choices = [choice.strip() for choice in recommended_options_raw.split(';') if choice.strip()]
                    for choice_pair in grid_choices:
                        if ':' in choice_pair:
                            row_label, col_label = [p.strip() for p in choice_pair.split(':', 1)]
                            self.status_update.emit(
                                f"جاري محاولة النقر على خيار الشبكة: صف '{row_label}', عمود '{col_label}'")

                            # Find the row element first
                            row_element = self._get_element_by_text_content(self.page, row_label, timeout=10000)

                            if row_element:
                                # Then find the column option within that row
                                col_option_element = self._get_element_by_text_content(self.page, col_label,
                                                                                       parent_element=row_element,
                                                                                       timeout=5000)

                                if col_option_element:
                                    try:
                                        # Try to find the actual input (radio/checkbox) associated with the found element
                                        input_to_click = col_option_element.query_selector(
                                            'input[type="radio"], input[type="checkbox"]')

                                        if input_to_click and not input_to_click.is_checked():
                                            input_to_click.click()
                                            self.page.evaluate(
                                                "el => el.dispatchEvent(new Event('change', {bubbles: true}))",
                                                input_to_click)
                                            self.status_update.emit(
                                                f"✅ تم النقر على input لخيار الشبكة: Row='{row_label}', Column='{col_label}' وإطلاق حدث التغيير.")
                                        elif input_to_click and input_to_click.is_checked():
                                            self.status_update.emit(
                                                f"⚠️ خيار الشبكة '{row_label}', '{col_label}' محدد مسبقًا. لا حاجة للنقر.")
                                        else:
                                            # If no direct input found, click the containing element itself
                                            col_option_element.click()
                                            self.page.evaluate(
                                                "el => el.dispatchEvent(new Event('change', {bubbles: true}))",
                                                col_option_element)
                                            self.status_update.emit(
                                                f"✅ تم النقر على العنصر الحاوي لخيار الشبكة: Row='{row_label}', Column='{col_label}' وإطلاق حدث التغيير.")
                                        time.sleep(random.uniform(1.0, 3.0))
                                    except Exception as e:
                                        self.error_occurred.emit(
                                            f"خطأ أثناء النقر على خيار الشبكة: {e}\n{traceback.format_exc()}. جاري المحاولة مرة أخرى بعد قليل.")
                                        QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                                          lambda: self.send_command("answer_survey_question"))
                                        return
                                else:
                                    self.error_occurred.emit(
                                        f"لم يتم العثور على خيار العمود '{col_label}' في الصف '{row_label}'. جاري المحاولة مرة أخرى بعد قليل.")
                                    QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                                      lambda: self.send_command("answer_survey_question"))
                                    return
                            else:
                                self.error_occurred.emit(
                                    f"لم يتم العثور على عنصر الصف '{row_label}'. جاري المحاولة مرة أخرى بعد قليل.")
                                QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                                  lambda: self.send_command("answer_survey_question"))
                                return
                        else:
                            self.status_update.emit(
                                f"⚠️ تنسيق خيار الشبكة غير صالح: {choice_pair}. يجب أن يكون 'Row:Column'.")

                else:
                    self.status_update.emit(
                        "لا توجد خيارات موصى بها للنوع الشبكي. جاري المحاولة مرة أخرى بعد قليل.")
                    QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                      lambda: self.send_command("answer_survey_question"))
                    return
            else:
                self.error_occurred.emit(
                    f"نوع سؤال غير مدعوم أو غير محدد: {input_type}. جاري المحاولة مرة أخرى بعد قليل.")
                self.survey_ready.emit(False)
                QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                  lambda: self.send_command("answer_survey_question"))
                return

            if submit_button_selector:
                self.status_update.emit("جاري الضغط على زر التالي...")
                try:
                    button_clicked = False
                    for sel in submit_button_selector.split(','):
                        sel = sel.strip()
                        if not sel: continue
                        try:
                            # Wait for the button to be visible AND enabled
                            self.page.wait_for_selector(sel, state='visible', timeout=15000)
                            self.page.wait_for_function(
                                f"document.querySelector('{sel}') && !document.querySelector('{sel}').disabled",
                                timeout=15000)

                            self._click_humanlike(sel)
                            button_clicked = True
                            self.status_update.emit(f"✅ تم الضغط على زر التالي باستخدام المحدد: {sel}.")
                            break
                        except PlaywrightTimeoutError:
                            self.status_update.emit(
                                f"⚠️ زر التالي غير مرئي أو لم يصبح مفعّلاً خلال المهلة باستخدام المحدد: {sel}.")
                            continue
                        except Exception as click_e:
                            self.error_occurred.emit(
                                f"خطأ أثناء النقر أو انتظار الزر التالي باستخدام المحدد '{sel}': {click_e}\n{traceback.format_exc()}")
                            continue

                    if not button_clicked:
                        self.error_occurred.emit(
                            f"لم يتم العثور على زر التالي أو لم يصبح ممكناً باستخدام أي من المحددات: {submit_button_selector}. URL الحالي: {self.page.url}. جاري المحاولة مرة أخرى بعد قليل.")
                        self.survey_ready.emit(False)
                        QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                          lambda: self.send_command("answer_survey_question"))
                        return

                    time.sleep(random.uniform(*ACTION_DELAY_MS) / 1000)
                    # Use a short timeout for networkidle after click to allow the page to transition
                    self.page.wait_for_load_state('networkidle', timeout=30000)
                    self.status_update.emit(f"تم تحميل الصفحة التالية. URL الحالي: {self.page.url}")
                    self.survey_ready.emit(True)  # Signal success, leading to next question if automation active
                except PlaywrightTimeoutError:
                    self.error_occurred.emit(
                        f"مهلة انتظار زر التالي أو لم يصبح ممكناً أو مهلة تحميل الصفحة بعد النقر. URL الحالي: {self.page.url}. جاري المحاولة مرة أخرى بعد قليل.")
                    self.survey_ready.emit(False)
                    QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                      lambda: self.send_command("answer_survey_question"))
                    return
                except Exception as e:
                    self.error_occurred.emit(
                        f"خطأ أثناء الضغط على زر التالي: {e}\n{traceback.format_exc()}. جاري المحاولة مرة أخرى بعد قليل.")
                    self.survey_ready.emit(False)
                    QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                      lambda: self.send_command("answer_survey_question"))
                    return
            else:
                self.error_occurred.emit("لم يتم العثور على محدد لزر التالي. جاري المحاولة مرة أخرى بعد قليل.")
                self.survey_ready.emit(False)
                QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                                  lambda: self.send_command("answer_survey_question"))
                return

        except PlaywrightError as e:
            self.error_occurred.emit(
                f"خطأ Playwright أثناء الإجابة على الاستبيان: {e}\n{traceback.format_exc()}. جاري المحاولة مرة أخرى بعد قليل.")
            self.survey_ready.emit(False)
            self.send_command("answer_survey_question")
        except Exception as e:
            self.error_occurred.emit(
                f"خطأ عام أثناء الإجابة على الاستبيان: {e}\n{traceback.format_exc()}. جاري المحاولة مرة أخرى بعد قليل.")
            self.survey_ready.emit(False)
            self.send_command("answer_survey_question")

    def _start_survey_automation(self):
        self.is_survey_automation_active = True
        self.status_update.emit("بدء أتمتة الاستبيان. جاري انتظار السؤال الأول...")
        self.send_command("answer_survey_question")

    def _stop_survey_automation(self):
        self.is_survey_automation_active = False
        self.status_update.emit("تم إيقاف أتمتة الاستبيان.")

    def _answer_survey_question_loop(self):
        if not self.is_survey_automation_active:
            return

        self._answer_survey_question()
        if self.is_survey_automation_active:
            QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                              lambda: self.worker.send_command("answer_survey_question"))


# ==============================================================================
# 3. واجهة المستخدم (PySide6)
# ==============================================================================

class SwagbucksAutomatorApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Swagbucks Automator")
        self.setFixedSize(800, 600)

        self.worker = PlaywrightWorker(PROXY_ADDRESS_HTTP_FULL)
        self.worker.status_update.connect(self.update_status)
        self.worker.browser_ready.connect(self.on_browser_ready)
        self.worker.login_attempt_complete.connect(self.on_login_attempt_complete)
        self.worker.survey_ready.connect(self.on_survey_ready)
        self.worker.error_occurred.connect(self.show_error_message)
        self.worker.proxy_test_result.connect(self.handle_proxy_test_result)

        self.init_ui()
        self.worker.start()

        self.worker.send_command("set_persona_id", self.persona_id_combo.currentText())
        self.worker.send_command("start_browser_session")

    def init_ui(self):
        main_layout = QVBoxLayout()

        proxy_browser_group = QGroupBox("التحكم بالبروكسي والمتصفح")
        proxy_browser_layout = QFormLayout()

        self.proxy_address_label = QLabel(f"عنوان البروكسي: {PROXY_ADDRESS_HTTP_FULL}")
        proxy_browser_layout.addRow(self.proxy_address_label)

        self.connect_proxy_btn = QPushButton("اختبار اتصال البروكسي (Requests)")
        self.connect_proxy_btn.clicked.connect(self.test_proxy_connection)
        proxy_browser_layout.addRow(self.connect_proxy_btn)

        self.launch_browser_btn = QPushButton("تشغيل المتصفح والانتقال لصفحة تسجيل الدخول")
        self.launch_browser_btn.clicked.connect(self.launch_browser_and_go_login)
        self.launch_browser_btn.setEnabled(False)
        proxy_browser_layout.addRow(self.launch_browser_btn)

        self.close_browser_btn = QPushButton("إغلاق المتصفح")
        self.close_browser_btn.clicked.connect(self.close_browser)
        self.close_browser_btn.setEnabled(False)
        proxy_browser_layout.addRow(self.close_browser_btn)

        proxy_browser_group.setLayout(proxy_browser_layout)
        main_layout.addWidget(proxy_browser_group)

        login_group = QGroupBox("تسجيل الدخول إلى Swagbucks")
        login_layout = QFormLayout()

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("أدخل بريدك الإلكتروني")
        login_layout.addRow("البريد الإلكتروني:", self.email_input)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("أدخل كلمة المرور")
        login_layout.addRow("كلمة المرور:", self.password_input)

        self.login_btn = QPushButton("تسجيل الدخول (إدخال البيانات فقط)")
        self.login_btn.clicked.connect(self.start_login_process)
        self.login_btn.setEnabled(False)
        login_layout.addRow(self.login_btn)

        self.confirm_login_btn = QPushButton("تأكيد تسجيل الدخول يدوياً وحفظ الجلسة")
        self.confirm_login_btn.clicked.connect(self.confirm_login_manually)
        self.confirm_login_btn.setEnabled(False)
        login_layout.addRow(self.confirm_login_btn)

        self.skip_login_btn = QPushButton("تخطي تسجيل الدخول (إذا كانت الجلسة محفوظة)")
        self.skip_login_btn.clicked.connect(self.skip_login_process)
        self.skip_login_btn.setEnabled(False)
        login_layout.addRow(self.skip_login_btn)

        login_group.setLayout(login_layout)
        main_layout.addWidget(login_group)

        survey_group = QGroupBox("أتمتة الاستبيان")
        survey_layout = QVBoxLayout()

        persona_selection_layout = QHBoxLayout()
        self.persona_id_label = QLabel("اختيار الشخصية (Persona ID):")
        self.persona_id_combo = QComboBox()
        self.persona_id_combo.addItems([f"{i:02d}" for i in range(1, 11)])
        self.persona_id_combo.setCurrentText("01")
        self.persona_id_combo.currentIndexChanged.connect(self.on_persona_id_changed)
        persona_selection_layout.addWidget(self.persona_id_label)
        persona_selection_layout.addWidget(self.persona_id_combo)
        survey_layout.addLayout(persona_selection_layout)

        self.answer_now_btn = QPushButton("أجب الآن (بدء الأتمتة)")
        self.answer_now_btn.clicked.connect(self.start_survey_automation)
        self.answer_now_btn.setEnabled(False)
        survey_layout.addWidget(self.answer_now_btn)

        self.stop_automation_btn = QPushButton("إيقاف الأتمتة")
        self.stop_automation_btn.clicked.connect(self.stop_survey_automation)
        self.stop_automation_btn.setEnabled(False)
        survey_layout.addWidget(self.stop_automation_btn)

        survey_group.setLayout(survey_layout)
        main_layout.addWidget(survey_group)

        self.status_label = QLabel("الحالة: جاهز.")
        main_layout.addWidget(self.status_label)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("سجل النشاطات يظهر هنا...")
        main_layout.addWidget(self.log_output)

        self.setLayout(main_layout)

    def update_status(self, message: str):
        self.status_label.setText(f"الحالة: {message}")
        self.log_output.append(message)

    def show_error_message(self, message: str):
        QMessageBox.critical(self, "خطأ", message)
        self.log_output.append(f"<span style='color:red;'>خطأ: {message}</span>")

    def test_proxy_connection(self):
        self.update_status("جاري اختبار اتصال البروكسي (Requests)...")
        self.worker.send_command("test_proxy_requests", PROXY_ADDRESS_HTTP_FULL)

    def handle_proxy_test_result(self, success: bool, message: str):
        if success:
            self.update_status(message)
        else:
            self.show_error_message(message)

    def launch_browser_and_go_login(self):
        self.update_status("جاري الانتقال لصفحة تسجيل الدخول...")
        self.worker.send_command("navigate_to_url", SWAGBUCKS_LOGIN_URL)

    def close_browser(self):
        self.update_status("جاري إغلاق المتصفح...")
        self.worker.send_command("stop_browser_session")
        self.confirm_login_btn.setEnabled(False)
        self.answer_now_btn.setEnabled(False)

    def on_browser_ready(self, ready: bool):
        self.launch_browser_btn.setEnabled(ready)
        self.close_browser_btn.setEnabled(ready)
        self.login_btn.setEnabled(ready)
        self.persona_id_combo.setEnabled(ready)

        if ready:
            if os.path.exists(SESSION_STORAGE_PATH):
                try:
                    with open(SESSION_STORAGE_PATH, 'r') as f:
                        session_data = json.load(f)
                    saved_timestamp = session_data.get('timestamp')
                    if saved_timestamp and (time.time() - saved_timestamp < SESSION_EXPIRY_HOURS * 3600):
                        self.skip_login_btn.setEnabled(True)
                        self.update_status("تم الكشف عن جلسة محفوظة صالحة. يمكنك تخطي تسجيل الدخول.")
                        self.answer_now_btn.setEnabled(True)
                    else:
                        self.skip_login_btn.setEnabled(False)
                        self.update_status("الجلسة المحفوظة منتهية الصلاحية أو غير صالحة. لا يمكن تخطي تسجيل الدخول.")
                        self.answer_now_btn.setEnabled(False)
                except Exception as e:
                    self.skip_login_btn.setEnabled(False)
                    self.show_error_message(f"خطأ في قراءة ملف الجلسة: {e}")
                    self.answer_now_btn.setEnabled(False)
            else:
                self.skip_login_btn.setEnabled(False)
                self.update_status("لم يتم العثور على ملف جلسة محفوظة. لا يمكن تخطي تسجيل الدخول.")
                self.answer_now_btn.setEnabled(False)
            self.confirm_login_btn.setEnabled(False)
        else:
            self.update_status("المتصفح مغلق أو غير جاهز.")
            self.answer_now_btn.setEnabled(False)
            self.stop_automation_btn.setEnabled(False)
            self.skip_login_btn.setEnabled(False)
            self.confirm_login_btn.setEnabled(False)

    def start_login_process(self):
        username = self.email_input.text()
        password = self.password_input.text()

        if not username or not password:
            self.show_error_message("الرجاء إدخال البريد الإلكتروني وكلمة المرور.")
            return

        self.update_status("جاري بدء عملية تسجيل الدخول (إدخال البيانات فقط)...")
        self.login_btn.setEnabled(False)
        self.confirm_login_btn.setEnabled(True)
        self.worker.send_command("perform_login", username, password)

    def confirm_login_manually(self):
        """تأكيد تسجيل الدخول يدوياً وحفظ الجلسة."""
        self.update_status("جاري تأكيد تسجيل الدخول يدوياً وحفظ الجلسة...")
        self.confirm_login_btn.setEnabled(False)
        self.answer_now_btn.setEnabled(True)
        self.worker.send_command("confirm_login_and_save_session")

    def on_login_attempt_complete(self, success: bool):
        if success:
            self.update_status(
                "عملية إدخال بيانات تسجيل الدخول والنقر اكتملت. يرجى المراجعة يدوياً وتأكيد تسجيل الدخول.")
        else:
            self.status_update("فشل في إدخال بيانات تسجيل الدخول. يرجى المحاولة مرة أخرى.")
            self.login_btn.setEnabled(True)
            self.confirm_login_btn.setEnabled(False)

    def skip_login_process(self):
        """يقوم بتخطي عملية تسجيل الدخول وينتقل مباشرة إلى لوحة التحكم."""
        self.update_status("جاري تخطي تسجيل الدخول والتوجه إلى لوحة التحكم...")
        self.worker.send_command("navigate_to_url", SWAGBUCKS_DASHBUCKS_URL)
        self.worker.is_logged_in = True
        self.answer_now_btn.setEnabled(True)
        self.login_btn.setEnabled(False)
        self.skip_login_btn.setEnabled(False)
        self.confirm_login_btn.setEnabled(False)

    def on_persona_id_changed(self, index):
        selected_persona_id = self.persona_id_combo.currentText()
        self.worker.send_command("set_persona_id", selected_persona_id)

    def start_survey_automation(self):
        if self.worker.is_logged_in:
            self.update_status("بدء أتمتة الاستبيان...")
            self.answer_now_btn.setEnabled(False)
            self.stop_automation_btn.setEnabled(True)
            self.worker.send_command("start_survey_automation")
        else:
            self.show_error_message("لا يمكن بدء الأتمتة. يرجى تسجيل الدخول وتأكيد الجلسة يدوياً أولاً.")

    def stop_survey_automation(self):
        self.update_status("جاري إيقاف أتمتة الاستبيان...")
        self.answer_now_btn.setEnabled(True)
        self.stop_automation_btn.setEnabled(False)
        self.worker.send_command("stop_survey_automation")

    def on_survey_ready(self, ready: bool):
        if self.worker.is_survey_automation_active and ready:
            QTimer.singleShot(SURVEY_NEXT_DELAY_SECONDS * 1000,
                              lambda: self.worker.send_command("answer_survey_question"))
        else:
            self.answer_now_btn.setEnabled(True)
            self.stop_automation_btn.setEnabled(False)

    def closeEvent(self, event):
        self.worker.send_command("shutdown")
        self.worker.wait(5000)
        if self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
        event.accept()


# ==============================================================================
# 4. نقطة بدء التنفيذ الرئيسية
# ==============================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SwagbucksAutomatorApp()
    window.show()
    sys.exit(app.exec())
