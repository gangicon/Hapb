import sys
import os
import threading
import time
import traceback
import logging
import re
import json
import random
from datetime import datetime
import sqlite3
from collections import deque # لاستخدام قائمة الانتظار

# استيراد PySide6
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
    QPushButton, QLineEdit, QCheckBox, QLabel, QProgressBar,
    QListWidget, QListWidgetItem, QDialog, QFormLayout, QRadioButton, QButtonGroup, QMessageBox,
    QGridLayout, QScrollArea, QSizePolicy, QTextEdit, QTabWidget,
    QTextBrowser, QSpinBox, QSlider, QComboBox # لتسجيل الأحداث وعدادات الأرقام، QSlider لشريط التمرير، QComboBox للغة

)
from PySide6.QtCore import Qt, QObject, Signal, QTimer, QThread, QPropertyAnimation, QEasingCurve, QRect, QSize, QEvent, QTranslator, QAbstractAnimation # QEvent لأحداث الماوس، QTranslator للغة، QAbstractAnimation للرسوم المتحركة
from PySide6.QtGui import QIcon, QColor, QFont, QTextCursor

# استيراد qt-material لتطبيق الثيم
from qt_material import apply_stylesheet

# استيراد مكتبات الواجهة الخلفية
from gradio_client import Client
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import Error as PlaywrightError
import httpx
import requests
from bs4 import BeautifulSoup

# استيرادات جديدة للمتطلبات
import google.generativeai as genai # لتكامل Gemini
import platform # للحصول على معلومات الجهاز
from getmac import get_mac_address as gma # للحصول على عنوان MAC
from cryptography.fernet import Fernet # للتشفير

# ==============================================================================
# --- 1. Settings and Constants - الإعدادات والثوابت ---
# ==============================================================================
DB_FILE = "personas_database.db"
LOGS_DIR = "logs"
PROFILES_DIR = "playwright_profiles"
NUM_PERSONAS = 30
BASE_URL = "https://account.yougov.com/gb-en"
SCREENSHOTS_DIR = "screenshots"
AI_SETTINGS_PASSWORD = "o0m9r3a1n6" # كلمة سر إعدادات الذكاء الاصطناعي

# ثوابت تيليجرام لتتبع تشغيل التطبيق
TELEGRAM_BOT_TOKEN = "7415284784:AAE-qMK0b_ql80YmGFN_g3qGAv-iBII0qb4"
TELEGRAM_CHAT_ID = "5961507746"

# مفتاح التشفير (هام: في بيئة إنتاجية، يجب أن يأتي هذا من متغير بيئة أو ملف آمن)
# يمكنك توليد مفتاح جديد مرة واحدة باستخدام: Fernet.generate_key().decode()
# ثم قم بتعيينه كمتغير بيئة باسم APP_ENCRYPTION_KEY
_encryption_key = os.getenv("APP_ENCRYPTION_KEY", "3aUPfMezAaiRHrjOWWpElNtvadRoCFI9uzpEIkBrHt4=").encode()
_cipher_suite = Fernet(_encryption_key)


# محددات أولية/احتياطية لعناصر YouGov
YOUGOV_EMAIL_INPUT_SELECTOR = "#emailInput"
YOUGOV_NEXT_BUTTON_SELECTOR = "button.button-element.primary.medium.basic:has-text('Next')"
YOUGOV_CODE_INPUT_SELECTOR = "#loginCode"
YOUGOV_ACCEPT_COOKIES_BUTTON_SELECTOR = "#onetrust-accept-btn-handler"

# محددات عامة لأسئلة الاستبيان في YouGov (FALLBACKS)
YOUGOV_DEFAULT_QUESTION_TEXT_SELECTOR = ".question-text, h1.question__title, div[data-test='question-text'], legend.question-text, p.question-label"
YOUGOV_DEFAULT_OPTION_CONTAINER_SELECTOR = "div.response-label-container, label.response-label, li.survey-answer-item, div.answer-option, tr.grid-row, div.response-button, div.question-response-item.w-choice-base"
YOUGOV_DEFAULT_OPTION_LABEL_SELECTOR = "span.label-text, .label-content, label span, div.text-label, th.grid-item-text-left, div.response-button, span.answer-option-label, span.text"
YOUGOV_DEFAULT_OPTION_INPUT_SELECTOR = "input[type='radio'], input[type='checkbox'], [role='radio'], [role='checkbox'], .response-button-input"
YOUGOV_DEFAULT_TEXT_AREA_INPUT_SELECTOR = "textarea, input[type='text'], input[type='number']"
YOUGOV_DEFAULT_SUBMIT_BUTTON_SELECTOR = "button[type='submit'], button:has-text('Next'), button:has-text('Submit'), button:has-text('Continue'), button:has-text('Done'), a.button-next, button.button-primary, #next_button, button.question-next"

# ==============================================================================
# --- 2. Logging Setup - إعداد التسجيل ---
# ==============================================================================
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

# إعداد المسجل الرئيسي للتطبيق
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler(os.path.join(LOGS_DIR, 'app_main.log'), encoding='utf-8'),
                        logging.StreamHandler(sys.stdout)
                    ])

class QTextEditLogger(QObject, logging.Handler):
    """
    مُعالج تسجيل مخصص لإرسال رسائل السجل إلى QTextEdit.
    """
    log_signal = Signal(str, str) # message, level_name

    def __init__(self, text_edit, parent=None):
        QObject.__init__(self, parent)
        logging.Handler.__init__(self)
        self.text_edit = text_edit
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.log_signal.connect(self.append_log_message)

    def emit(self, record):
        msg = self.format(record)
        self.log_signal.emit(msg, record.levelname)

    def append_log_message(self, message, level_name):
        color = "white"
        if level_name == "INFO":
            color = "#A0A0A0" # Light grey
        elif level_name == "WARNING":
            color = "#FFC107" # Amber
        elif level_name == "ERROR":
            color = "#F44336" # Red
        elif level_name == "CRITICAL":
            color = "#B71C1C" # Dark Red
        
        self.text_edit.append(f"<span style='color: {color};'>{message}</span>")
        self.text_edit.verticalScrollBar().setValue(self.text_edit.verticalScrollBar().maximum())


def setup_persona_logger(persona_id):
    """
    يقوم بإعداد مسجل لكل شخصية.
    لكل شخصية ملف سجل خاص بها لتتبع العمليات والأخطاء.
    """
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    log_file = os.path.join(LOGS_DIR, f"persona_{persona_id}_latest.log")
    handler = logging.FileHandler(log_file, encoding='utf-8')
    handler.setFormatter(log_formatter)
    logger = logging.getLogger(f"Persona_{persona_id}")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    # لا نضيف StreamHandler هنا لتجنب تكرار السجلات في الكونسول
    return logger


# ==============================================================================
# --- 3. Database Helper Functions - دوال مساعدة لقاعدة البيانات ---
# ==============================================================================

# دوال التشفير وفك التشفير
def encrypt_data(data):
    """تشفير البيانات باستخدام Fernet."""
    if data is None or data == '':
        return ''
    try:
        return _cipher_suite.encrypt(data.encode()).decode()
    except Exception as e:
        logging.error(f"Encryption failed: {e}")
        return data # إرجاع البيانات غير مشفرة في حالة الفشل

def decrypt_data(data):
    """فك تشفير البيانات باستخدام Fernet."""
    if data is None or data == '':
        return ''
    try:
        return _cipher_suite.decrypt(data.encode()).decode()
    except Exception as e:
        logging.warning(f"Decryption failed for data (might be unencrypted or corrupt): {e}")
        return data # إرجاع البيانات كما هي إذا فشل فك التشفير (قد تكون غير مشفرة)


def setup_database():
    """
    يهيئ قاعدة بيانات SQLite وينشئ جدول 'personas' إذا لم يكن موجوداً.
    يضيف إدخالات شخصية افتراضية إذا لم تكن موجودة.
    ينشئ أيضاً جدولاً لتخزين المحددات المتعلمة ديناميكياً من الذكاء الاصطناعي.
    """
    os.makedirs(PROFILES_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS personas (
            id INTEGER PRIMARY KEY,
            email TEXT DEFAULT '',
            password TEXT DEFAULT '',
            proxy TEXT DEFAULT '',
            kick_count INTEGER DEFAULT 0,
            api_key TEXT DEFAULT '',
            proxy_type TEXT DEFAULT 'none'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS dynamic_selectors (
            url_pattern TEXT PRIMARY KEY,
            question_selector TEXT,
            option_container_selector TEXT,
            option_label_selector TEXT,
            option_input_selector TEXT,
            submit_button_selector TEXT,
            input_type TEXT,
            last_updated TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            persona_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS app_settings (
            setting_name TEXT PRIMARY KEY,
            setting_value TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS omran2_selector_knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            selector_description TEXT,
            selector_value TEXT NOT NULL,
            ai_explanation TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    for i in range(1, NUM_PERSONAS + 1):
        cursor.execute("INSERT OR IGNORE INTO personas (id) VALUES (?)", (i,))

    # إعدادات الذكاء الاصطناعي الافتراضية
    cursor.execute("INSERT OR IGNORE INTO app_settings (setting_name, setting_value) VALUES (?, ?)",
                    ("question_ai_url", "https://omran2211-ask.hf.space/"))
    cursor.execute("INSERT OR IGNORE INTO app_settings (setting_name, setting_value) VALUES (?, ?)",
                    ("selector_ai_url", "https://serverboot-yourusernamesurveyselectorai.hf.space/"))
    cursor.execute("INSERT OR IGNORE INTO app_settings (setting_name, setting_value) VALUES (?, ?)",
                    ("gemini_api_key", "")) # مفتاح Gemini API الجديد
    # **جديد**: إعدادات حجم البطاقة الافتراضية
    cursor.execute("INSERT OR IGNORE INTO app_settings (setting_name, setting_value) VALUES (?, ?)",
                    ("persona_card_width", "200"))
    cursor.execute("INSERT OR IGNORE INTO app_settings (setting_name, setting_value) VALUES (?, ?)",
                    ("persona_card_height", "220")) # ارتفاع أكبر قليلاً لاستيعاب الأزرار
    
    # إعدادات التأخير الافتراضية
    cursor.execute("INSERT OR IGNORE INTO app_settings (setting_name, setting_value) VALUES (?, ?)",
                    ("min_delay_seconds", "2"))
    cursor.execute("INSERT OR IGNORE INTO app_settings (setting_name, setting_value) VALUES (?, ?)",
                    ("max_delay_seconds", "5"))
    
    # إعدادات اللغة الافتراضية
    cursor.execute("INSERT OR IGNORE INTO app_settings (setting_name, setting_value) VALUES (?, ?)",
                    ("current_language", "ar")) # اللغة الافتراضية العربية

    conn.commit()
    conn.close()


def get_persona_data(persona_id):
    """يسترجع بيانات شخصية محددة من قاعدة البيانات، مع فك التشفير."""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT email, password, proxy, kick_count, api_key, proxy_type FROM personas WHERE id = ?",
                   (persona_id,))
    data = cursor.fetchone()
    conn.close()
    if data:
        # فك التشفير عند الجلب
        decrypted_password = decrypt_data(data[1])
        decrypted_proxy = decrypt_data(data[2])
        decrypted_api_key = decrypt_data(data[4])
        return (data[0], decrypted_password, decrypted_proxy, data[3], decrypted_api_key, data[5])
    return ('', '', '', 0, '', 'none')


def save_persona_credentials(persona_id, email, password):
    """يحفظ بيانات اعتماد الشخصية في قاعدة البيانات، مع تشفير كلمة المرور."""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    encrypted_password = encrypt_data(password) # تشفير كلمة المرور
    cursor.execute("UPDATE personas SET email = ?, password = ? WHERE id = ?", (email, encrypted_password, persona_id))
    conn.commit()
    conn.close()


def save_persona_proxy(persona_id, proxy, proxy_type):
    """يحفظ إعدادات البروكسي للشخصية في قاعدة البيانات، مع تشفير عنوان البروكسي."""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    encrypted_proxy = encrypt_data(proxy) # تشفير البروكسي
    cursor.execute("UPDATE personas SET proxy = ?, proxy_type = ? WHERE id = ?", (encrypted_proxy, proxy_type, persona_id))
    conn.commit()
    conn.close()


def save_api_key(persona_id, api_key):
    """يحفظ مفتاح API للشخصية في قاعدة البيانات، مع تشفير المفتاح."""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    encrypted_api_key = encrypt_data(api_key) # تشفير مفتاح API
    cursor.execute("UPDATE personas SET api_key = ? WHERE id = ?", (encrypted_api_key, persona_id))
    conn.commit()
    conn.close()


def increment_kick_count(persona_id):
    """يزيد 'kick_count' لشخصية محددة."""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("UPDATE personas SET kick_count = kick_count + 1 WHERE id = ?", (persona_id,))
    conn.commit()
    conn.close()


def save_dynamic_selectors(url_pattern, selectors_data):
    """
    يحفظ المحددات التي تعلمها الذكاء الاصطناعي لنمط URL معين في قاعدة البيانات.
    هذا يجعل المحددات دائمة ومتاحة لجميع الشخصيات التي تزور نفس نمط الرابط.
    """
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute(
        """INSERT OR REPLACE INTO dynamic_selectors
           (url_pattern, question_selector, option_container_selector, option_label_selector, option_input_selector, submit_button_selector, input_type, last_updated)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (url_pattern, selectors_data.get('question_selector', ''),
         selectors_data.get('option_container_selector', ''),
         selectors_data.get('option_label_selector', ''),
         selectors_data.get('option_input_selector', ''),
         selectors_data.get('submit_button_selector', ''),
         selectors_data.get('input_type', 'unknown'),
         now)
    )
    conn.commit()
    conn.close()


def get_dynamic_selectors(url_pattern):
    """
    يسترجع المحددات المحفوظة لنمط URL معين من قاعدة البيانات.
    """
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT question_selector, option_container_selector, option_label_selector, option_input_selector, submit_button_selector, input_type FROM dynamic_selectors WHERE url_pattern = ?",
        (url_pattern,))
    data = cursor.fetchone()
    conn.close()
    if data:
        return {
            'question_selector': data[0],
            'option_container_selector': data[1],
            'option_label_selector': data[2],
            'option_input_selector': data[3],
            'submit_button_selector': data[4],
            'input_type': data[5]
        }
    return None


def save_to_persona_history_global(persona_id, question, answer):
    _conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    _cursor = _conn.cursor()
    try:
        _cursor.execute("INSERT INTO conversation_history (persona_id, question, answer) VALUES (?, ?, ?)",
                        (str(persona_id), question, answer))
        _conn.commit()
    except Exception as e:
        logging.error(f"ERROR saving history for persona {persona_id}: {e}")
    finally:
        _conn.close()

def get_app_setting(setting_name, default_value=None):
    """يسترجع إعداد تطبيق معين من قاعدة البيانات، مع فك التشفير للقيم الحساسة."""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT setting_value FROM app_settings WHERE setting_name = ?", (setting_name,))
    result = cursor.fetchone()
    conn.close()
    if result:
        # فك التشفير إذا كانت الإعدادات حساسة (مثل مفتاح Gemini API)
        if setting_name in ["gemini_api_key"]:
            return decrypt_data(result[0])
        return result[0]
    return default_value

def set_app_setting(setting_name, setting_value):
    """يحفظ إعداد تطبيق معين في قاعدة البيانات، مع تشفير القيم الحساسة."""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    # تشفير القيمة إذا كانت الإعدادات حساسة
    if setting_name in ["gemini_api_key"]:
        encrypted_value = encrypt_data(setting_value)
    else:
        encrypted_value = setting_value
    cursor.execute('INSERT OR REPLACE INTO app_settings (setting_name, setting_value) VALUES (?, ?)', (setting_name, encrypted_value))
    conn.commit()
    conn.close()

def save_omran2_selector_knowledge(url, description, selector_value, ai_explanation):
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO omran2_selector_knowledge (url, selector_description, selector_value, ai_explanation)
        VALUES (?, ?, ?, ?)
    ''', (url, description, selector_value, ai_explanation))
    conn.commit()
    conn.close()
    logging.info(f"Omran saved selector knowledge: URL={url}, Selector={selector_value}")

def get_omran2_selector_knowledge(url=None, description=None):
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    query = "SELECT url, selector_description, selector_value, ai_explanation FROM omran2_selector_knowledge WHERE 1=1"
    params = []
    if url:
        query += " AND url LIKE ?"
        params.append(f"%{url}%")
    if description:
        query += " AND selector_description LIKE ?"
        params.append(f"%{description}%")
    query += " ORDER BY timestamp DESC LIMIT 5" # Get most recent 5 relevant entries
    cursor.execute(query, tuple(params))
    results = cursor.fetchall()
    conn.close()
    return results

def get_conversation_history(persona_id=None):
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    if persona_id:
        cursor.execute("SELECT timestamp, question, answer FROM conversation_history WHERE persona_id = ? ORDER BY timestamp DESC LIMIT 100", (str(persona_id),))
    else:
        cursor.execute("SELECT timestamp, question, answer FROM conversation_history ORDER BY timestamp DESC LIMIT 100")
    history = cursor.fetchall()
    conn.close()
    return history


def extract_visible_html(html_content):
    """
    يستخدم BeautifulSoup لتحليل HTML واستخراج المحتوى الذي يحتمل أن يكون مرئياً للمستخدم.
    يزيل عناصر script, style, head, meta, والعناصر المخفية صراحة بواسطة CSS أو سمة 'hidden'.
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    for tag in soup(["style", "script", "head", "meta", "[document]"]):
        tag.decompose()

    for el in soup.select('[style*="display:none"], [style*="visibility:hidden"], [hidden]'):
        el.decompose()

    return str(soup.body) if soup.body else str(soup)

# دالة إرسال رسالة Telegram
def send_telegram_message(message):
    """يرسل رسالة إلى بوت تيليجرام المحدد."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message
    }
    try:
        response = requests.post(url, data=payload, timeout=5)
        response.raise_for_status() # رفع استثناء للأخطاء HTTP
        logging.info(f"Telegram message sent successfully: {message}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send Telegram message to {TELEGRAM_CHAT_ID}: {e}")
    except Exception as e:
        logging.error(f"Unexpected error sending Telegram message: {e}")


# ==============================================================================
# --- 4. Automation Bot Class (AutomationThread) - فئة بوت الأتمتة (مع Signals للـ UI) ---
# ==============================================================================
class WorkerSignals(QObject):
    """
    الإشارات المتاحة من خيط عامل قيد التشغيل إلى واجهة المستخدم الرسومية.
    """
    # لإرسال تحديثات الحالة: persona_id, text, color_name (string)
    status_updated = Signal(int, str, str)
    # لتحديث مؤشر المخاطرة: persona_id
    risk_updated = Signal(int)
    # لتشغيل صوت: لا توجد وسيطات
    play_sound = Signal()
    # لإرسال إشارة النقر على زر "Answer Now" في الواجهة: persona_id, delay_seconds
    trigger_ui_answer_now = Signal(int, int)
    # للإشارة إلى أن الشخصية بدأت في معالجة AI
    ai_started_processing = Signal(int)
    # للإشارة إلى أن الشخصية انتهت من معالجة AI
    ai_finished_processing = Signal(int)
    # لإجبار البوت على تعلم المحددات من AI
    force_learn_selectors = Signal(int)
    # إشارة جديدة لإرسال رسائل الأخطاء إلى Omran Chat
    omran_error_message = Signal(str, int) # error_message, persona_id
    # إشارة لإرسال استجابات AI المحددات إلى واجهة Omran Chat
    omran_selector_ai_response = Signal(str, str, str) # url, question, response

class AutomationThread(threading.Thread):
    def __init__(self, persona_id, headless_mode, proxy_to_use,
                 question_ai_url, selector_ai_url, save_to_persona_history_func,
                 main_window_signals: WorkerSignals): # استلام إشارات الواجهة الرئيسية
        super().__init__(daemon=True)
        self.persona_id = persona_id
        self.signals = main_window_signals # تخزين مرجع للإشارات
        self.logger = setup_persona_logger(persona_id)
        self.headless = headless_mode
        self.proxy = proxy_to_use
        self.is_running = True # علم للتحكم في حلقة التشغيل
        self.force_answer_now = False # يتم تعيينه بواسطة UI لبدء الإجابة
        self.force_selector_learning = False # علم لفرض تعلم المحددات من AI

        self.email, self.password, self.saved_proxy_str, self.kick_count_val, self.api_key, self.proxy_type_db = get_persona_data(
            self.persona_id)
        if self.proxy_type_db in ['regular', 'home'] and self.saved_proxy_str:
            self.proxy = {'server': self.saved_proxy_str}
        else:
            self.proxy = None

        self.question_ai_client = None
        self.selector_ai_client = None
        self.question_ai_url = question_ai_url
        self.selector_ai_url = selector_ai_url

        self.browser = None
        self.context = None
        self.page = None

        self.save_to_persona_history = save_to_persona_history_func

        self.current_page_selectors = {
            'question_selector': YOUGOV_DEFAULT_QUESTION_TEXT_SELECTOR,
            'option_container_selector': YOUGOV_DEFAULT_OPTION_CONTAINER_SELECTOR,
            'option_label_selector': YOUGOV_DEFAULT_OPTION_LABEL_SELECTOR,
            'option_input_selector': YOUGOV_DEFAULT_OPTION_INPUT_SELECTOR,
            'submit_button_selector': YOUGOV_DEFAULT_SUBMIT_BUTTON_SELECTOR,
            'input_type': 'unknown'
        }
        
        # تحميل إعدادات التأخير من قاعدة البيانات
        self.min_delay = int(get_app_setting("min_delay_seconds", "2"))
        self.max_delay = int(get_app_setting("max_delay_seconds", "5"))

    def _human_like_type(self, locator, text):
        self.logger.info(f"Persona {self.persona_id}: Typing '{text}' character by character...")
        for char in text:
            locator.type(char)
            time.sleep(random.uniform(0.05, 0.2))
        time.sleep(random.uniform(self.min_delay, self.max_delay)) # استخدام إعدادات التأخير
        self.logger.info(f"Persona {self.persona_id}: Successfully simulated typing into field.")

    def stop(self):
        """
        يطلب من الخيط التوقف عن العمل.
        يتم استدعاؤها من الخيط الرئيسي.
        """
        self.is_running = False
        self.logger.info(f"Persona {self.persona_id}: Stop requested. Setting is_running to False.")
        time.sleep(0.5) 

    def solve_recaptcha(self, sitekey, page_url, api_key):
        self.logger.info(f"Persona {self.persona_id}: Attempting to solve reCAPTCHA. Sitekey: {sitekey}, URL: {page_url} (جاري محاولة حل الكباتشا.)")
        self.signals.status_updated.emit(self.persona_id, self.tr("Solving CAPTCHA... - جاري حل الكباتشا..."), "deep_orange_accent")

        if not api_key:
            self.logger.error(f"Persona {self.persona_id}: 2Captcha API key is missing. Cannot solve reCAPTCHA automatically. (مفتاح API لـ 2Captcha مفقود. لا يمكن حل الكباتشا تلقائيًا.)")
            self.signals.status_updated.emit(self.persona_id, self.tr("CAPTCHA: Manual Solving Needed! - الكباتشا: مطلوب حل يدوي!"), "orange")
            self.signals.omran_error_message.emit(f"Persona {self.persona_id}: CAPTCHA API key missing. Manual CAPTCHA solving needed.", self.persona_id)
            return None

        try:
            params = {
                'key': api_key,
                'method': 'userrecaptcha',
                'googlekey': sitekey,
                'pageurl': page_url,
                'json': 1
            }
            self.logger.info(f"Persona {self.persona_id}: Sending CAPTCHA request to 2Captcha API. (جاري إرسال طلب الكباتشا إلى 2Captcha API.)")
            response = requests.get('http://2captcha.com/in.php', params=params, timeout=30)
            response.raise_for_status()

            resp_data = response.json()
            if resp_data['status'] == 0:
                self.logger.error(f"Persona {self.persona_id}: 2Captcha API error: {resp_data['request']} (خطأ في 2Captcha API.)")
                self.signals.status_updated.emit(self.persona_id, self.tr(f"CAPTCHA API Error: {resp_data['request']}! - خطأ في API الكباتشا!"), "red")
                self.signals.omran_error_message.emit(f"Persona {self.persona_id}: CAPTCHA API Error: {resp_data['request']}", self.persona_id)
                return None

            request_id = resp_data['request']
            self.logger.info(f"Persona {self.persona_id}: 2Captcha request ID: {request_id}. Waiting for result... (معرف طلب 2Captcha. جاري انتظار النتيجة.)")

            for i in range(1, 21):
                time.sleep(self.min_delay) # استخدام إعدادات التأخير
                self.logger.info(f"Persona {self.persona_id}: Polling 2Captcha for result (attempt {i}/20). (جاري استطلاع 2Captcha للحصول على النتيجة.)")
                params_res = {
                    'key': api_key,
                    'action': 'get',
                    'id': request_id,
                    'json': 1
                }
                response_res = requests.get('http://2captcha.com/res.php', params=params_res, timeout=30)
                response_res.raise_for_status()

                resp_data_res = response_res.json()
                if resp_data_res['status'] == 1:
                    self.logger.info(f"Persona {self.persona_id}: reCAPTCHA solved successfully by 2Captcha. (تم حل الكباتشا بواسطة 2Captcha بنجاح.)")
                    self.signals.status_updated.emit(self.persona_id, self.tr("CAPTCHA Solved! - تم حل الكباتشا!"), "light_green_700")
                    return resp_data_res['request']
                elif resp_data_res['request'] == 'CAPCHA_NOT_READY':
                    self.logger.info(f"Persona {self.persona_id}: CAPTCHA not ready yet, retrying... (الكباتشا ليست جاهزة بعد، جاري إعادة المحاولة.)")
                    continue
                else:
                    self.logger.error(f"Persona {self.persona_id}: 2Captcha API error during result retrieval: {resp_data_res['request']} (خطأ في 2Captcha API أثناء استرجاع النتيجة.)")
                    self.signals.status_updated.emit(self.persona_id, self.tr(f"CAPTCHA Result Error: {resp_data_res['request']}! - خطأ في API الكباتشا!"), "red")
                    self.signals.omran_error_message.emit(f"Persona {self.persona_id}: CAPTCHA Result Error: {resp_data_res['request']}", self.persona_id)
                    return None

            self.logger.error(f"Persona {self.persona_id}: 2Captcha polling timed out. (انتهت مهلة استطلاع 2Captcha.)")
            self.signals.status_updated.emit(self.persona_id, self.tr("CAPTCHA Timeout! - مهلة الكباتشا!"), "red")
            self.signals.omran_error_message.emit(f"Persona {self.persona_id}: CAPTCHA polling timed out.", self.persona_id)
            return None

        except requests.exceptions.RequestException as req_e:
            self.logger.error(f"Persona {self.persona_id}: Network error during 2Captcha API call: {req_e} {traceback.format_exc()} (خطأ في الشبكة أثناء استدعاء 2Captcha API.)")
            self.signals.status_updated.emit(self.persona_id, self.tr("CAPTCHA Network Error! - خطأ شبكة الكباتشا!"), "red")
            self.signals.omran_error_message.emit(f"Persona {self.persona_id}: CAPTCHA Network Error: {req_e}", self.persona_id)
            return None
        except Exception as e:
            self.logger.error(f"Persona {self.persona_id}: Unexpected error in solve_recaptcha: {traceback.format_exc()} (خطأ غير متوقع في solve_recaptcha.)")
            self.signals.status_updated.emit(self.persona_id, self.tr("CAPTCHA Unknown Error! - خطأ كباتشا غير معروف!"), "red")
            self.signals.omran_error_message.emit(f"Persona {self.persona_id}: CAPTCHA Unknown Error: {e}", self.persona_id)
            return None

    def _find_and_navigate_to_survey_link(self):
        """
        يقوم بمسح الصفحة الحالية بحثاً عن روابط/أزرار استبيان نشطة وينتقل إلى أول رابط يتم العثور عليه.
        """
        self.logger.info(self.tr(f"Persona {self.persona_id}: Attempting to find and navigate to a survey link. Current URL: {self.page.url}"))
        self.signals.status_updated.emit(self.persona_id, self.tr("Searching for Surveys... - جاري البحث عن استبيانات..."), "blue_500")

        try:
            survey_locators = [
                self.page.locator("a[href*='/survey']").first,
                self.page.locator("a[href*='/profiler']").first,
                self.page.locator("button:has-text('Take Survey')"),
                self.page.locator("a:has-text('Take Survey')"),
                self.page.locator("button.call-to-action:has-text('Start Survey')"),
                self.page.locator("div.survey-card a").first,
                self.page.locator("a[aria-label*='survey']").first,
                self.page.locator("div.button-element.primary.medium.basic:has-text('Take survey')").first
            ]

            for locator in survey_locators:
                if locator.count() > 0:
                    found_element = locator.first
                    if found_element.is_visible() and not found_element.is_disabled():
                        self.logger.info(self.tr(f"Persona {self.persona_id}: Found visible and enabled survey link: '{found_element.text_content() or found_element.get_attribute('href')}'. Clicking. (تم العثور على رابط استبيان. جاري النقر.)"))
                        found_element.click(timeout=15000)
                        self.page.wait_for_load_state('domcontentloaded', timeout=30000)
                        self.logger.info(self.tr(f"Persona {self.persona_id}: Clicked survey link. New URL: {self.page.url}"))
                        return True

            self.logger.info(self.tr(f"Persona {self.persona_id}: No active survey links found on the current page. (لم يتم العثور على روابط استبيان نشطة.)"))
            return False

        except PlaywrightTimeoutError as e:
            self.logger.warning(self.tr(f"Persona {self.persona_id}: Timeout while searching for or clicking survey links: {e}"))
            self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Timeout finding survey link: {e}", self.persona_id)
            return False
        except Exception as e:
            self.logger.error(self.tr(f"Persona {self.persona_id}: Error finding/clicking survey link: {traceback.format_exc()}"))
            self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Error finding survey link: {e}", self.persona_id)
            return False

    def perform_semi_auto_login(self):
        self.logger.info(self.tr(f"Persona {self.persona_id}: Navigating to YouGov login page: {BASE_URL}/login/email (جاري الانتقال لصفحة تسجيل الدخول في YouGov)"))
        self.signals.status_updated.emit(self.persona_id, self.tr("Navigating to Login... - جاري الانتقال لتسجيل الدخول..."), "cyan")

        try:
            self.page.goto(f"{BASE_URL}/login/email", wait_until='domcontentloaded')
            time.sleep(random.uniform(self.min_delay, self.max_delay)) # استخدام إعدادات التأخير

            self.logger.info(self.tr(f"Persona {self.persona_id}: Checking for Accept Cookies button. (جاري التحقق من زر قبول الكوكيز.)"))
            cookie_accept_button = self.page.locator(YOUGOV_ACCEPT_COOKIES_BUTTON_SELECTOR)
            
            try:
                cookie_accept_button.wait_for(state='visible', timeout=5000)
                if cookie_accept_button.is_visible():
                    self.logger.info(self.tr(f"Persona {self.persona_id}: Clicking Accept All Cookies. (جاري النقر على قبول كل الكوكيز.)"))
                    cookie_accept_button.click()
                    self.signals.status_updated.emit(self.persona_id, self.tr("Cookies Accepted. - تم قبول الكوكيز."), "light_green_700")
                    time.sleep(random.uniform(1, 2))
                else:
                    self.logger.info(self.tr(f"Persona {self.persona_id}: Accept Cookies button not found or not visible. (لم يتم العثور على زر قبول الكوكيز أو أنه غير مرئي.)"))
            except PlaywrightTimeoutError:
                self.logger.info(self.tr(f"Persona {self.persona_id}: Accept Cookies button did not become visible within timeout. (زر قبول الكوكيز لم يظهر ضمن المهلة.)"))


            self.logger.info(self.tr(f"Persona {self.persona_id}: Attempting to fill email field. (جاري محاولة ملء حقل البريد الإلكتروني.)"))
            email_input = self.page.locator(YOUGOV_EMAIL_INPUT_SELECTOR)
            email_input.fill(self.email, timeout=10000)
            self.logger.info(self.tr(f"Persona {self.persona_id}: Email field filled. (تم ملء حقل البريد الإلكتروني.)"))
            time.sleep(random.uniform(self.min_delay, self.max_delay)) # استخدام إعدادات التأخير

            self.logger.info(self.tr(f"Persona {self.persona_id}: Clicking Next button for email submission. (جاري النقر على زر Next لإرسال البريد.)"))
            next_button = self.page.locator(YOUGOV_NEXT_BUTTON_SELECTOR)

            self.logger.info(self.tr(f"Persona {self.persona_id}: Waiting for Next button (locator: '{YOUGOV_NEXT_BUTTON_SELECTOR}') to be visible. (جاري انتظار زر Next ليصبح مرئياً.)"))
            next_button.wait_for(state='visible', timeout=30000)
            self.logger.info(self.tr(f"Persona {self.persona_id}: Waiting for Next button (selector: 'button.button-element.primary.medium.basic:has-text('Next'):enabled') to be enabled. (جاري انتظار زر Next ليصبح مفعلاً.)"))
            self.page.wait_for_selector(f"button.button-element.primary.medium.basic:has-text('Next'):enabled", timeout=45000) 
            self.logger.info(self.tr(f"Persona {self.persona_id}: Next button is enabled. Clicking. (زر Next مفعل. جاري النقر.)"))

            next_button.click(timeout=15000)

            self.signals.status_updated.emit(self.persona_id, self.tr("Email Submitted. Please complete login & click 'Answer Now'. - تم إرسال البريد. أكمل تسجيل الدخول وانقر 'أجب الآن'."), "orange")
            time.sleep(random.uniform(self.min_delay, self.max_delay)) # استخدام إعدادات التأخير

            return True
        except PlaywrightTimeoutError as e:
            self.logger.error(self.tr(f"Persona {self.persona_id}: Timeout during login flow: {e}. Current URL: {self.page.url} (مهلة أثناء تدفق تسجيل الدخول.)"))
            self.signals.status_updated.emit(self.persona_id, self.tr("Login Timeout! - مهلة تسجيل الدخول!"), "red")
            self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Login Timeout: {e}", self.persona_id)
            return False
        except Exception as e:
            self.logger.critical(self.tr(f"Persona {self.persona_id}: Critical error during login flow: {traceback.format_exc()} (خطأ فادح أثناء تدفق تدفق تسجيل الدخول.)"))
            self.signals.status_updated.emit(self.persona_id, self.tr("Login Failed! - فشل تسجيل الدخول!"), "red")
            self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Login Failed: {e}", self.persona_id)
            return False

    def _get_current_page_html_content(self):
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                self.page.wait_for_load_state("networkidle", timeout=15000)
                time.sleep(random.uniform(1, 2)) # استخدام إعدادات التأخير

                html_content = self.page.content()
                self.logger.info(self.tr(f"Persona {self.persona_id}: Captured HTML content (size: {len(html_content)} bytes) on attempt {attempt + 1}. (تم التقاط محتوى HTML للصفحة.)"))
                return html_content
            except PlaywrightTimeoutError as e:
                self.logger.warning(self.tr(f"Persona {self.persona_id}: Timeout waiting for page to become idle or during HTML capture (attempt {attempt + 1}/{max_attempts}): {e}. Retrying in 1 second... (مهلة انتظار الصفحة.)"))
                self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Timeout capturing HTML: {e}", self.persona_id)
                time.sleep(1)
                continue
            except PlaywrightError as e:
                if "Page.content: Unable to retrieve content because the page is navigating" in str(e):
                    self.logger.warning(self.tr(f"Persona {self.persona_id}: Page navigating during HTML capture (attempt {attempt + 1}/{max_attempts}). Retrying in 1 second... (الصفحة تتنقل أثناء التقاط HTML. جاري إعادة المحاولة...)"))
                    time.sleep(1)
                    continue
                else:
                    self.logger.error(self.tr(f"Persona {self.persona_id}: Failed to capture page HTML content due to Playwright error: {e}. Traceback: {traceback.format_exc()} (فشل التقاط محتوى HTML للصفحة.)"))
                    self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Playwright error capturing HTML: {e}", self.persona_id)
                return None
            except Exception as e:
                self.logger.error(self.tr(f"Persona {self.persona_id}: Failed to capture page HTML content due to unexpected error: {e}. Traceback: {traceback.format_exc()} (فشل التقاط محتوى HTML للصفحة.)"))
                self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Unexpected error capturing HTML: {e}", self.persona_id)
                return None
        self.logger.error(self.tr(f"Persona {self.persona_id}: Failed to capture page HTML content after {max_attempts} attempts. (فشل التقاط محتوى HTML للصفحة بعد عدة محاولات.)"))
        return None

    def _learn_selectors_from_ai(self):
        self.signals.status_updated.emit(self.persona_id, self.tr("Learning page structure with AI... - تعلم هيكل الصفحة بالذكاء الاصطناعي..."), "amber")
        self.logger.info(self.tr(f"Persona {self.persona_id}: Attempting to learn selectors from AI for URL: {self.page.url} (جاري محاولة تعلم المحددات من الذكاء الاصطناعي)"))

        html_content = self._get_current_page_html_content()
        if not html_content:
            self.logger.error(self.tr(f"Persona {self.persona_id}: Could not get page HTML content to send to AI. (تعذر الحصول على محتوى HTML للصفحة لإرساله إلى الذكاء الاصطناعي.)"))
            self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Failed to get HTML for selector AI.", self.persona_id)
            return False

        processed_html_content = extract_visible_html(html_content)
        final_html_to_send = processed_html_content[:8000]
        self.logger.info(self.tr(f"Persona {self.persona_id}: Cleaned and trimmed HTML content to {len(final_html_to_send)} characters for Selector AI."))

        try:
            self.signals.ai_started_processing.emit(self.persona_id)
            self.logger.info(self.tr(f"Persona {self.persona_id}: Sending HTML (first 2000 chars) to Selector AI. HTML start: {final_html_to_send[:2000]}... (جاري إرسال HTML إلى الذكاء الاصطناعي للمحددات)"))

            ai_response_raw = self.selector_ai_client.predict(
                final_html_to_send,
                api_name="/predict"
            )
            self.logger.info(self.tr(f"Persona {self.persona_id}: Received raw AI response: {ai_response_raw} (تم استلام استجابة الذكاء الاصطناعية الأولية)"))
            
            current_url = self.page.url if self.page else "N/A"
            self.signals.omran_selector_ai_response.emit(current_url, self.tr("تعلم المحددات"), ai_response_raw)


            try:
                ai_response_json = json.loads(ai_response_raw)
                if ai_response_json.get("error"):
                    self.logger.error(self.tr(f"Persona {self.persona_id}: Selector AI returned an error: {ai_response_json['error']}. Traceback: {ai_response_json.get('traceback', 'N/A')} (الذكاء الاصطناعي للمحددات أعاد خطأ.)"))
                    self.signals.status_updated.emit(self.persona_id, self.tr("AI Selector Error! - خطأ محددات الذكاء الاصطناعي!"), "red")
                    self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Selector AI error: {ai_response_json['error']}", self.persona_id)
                    return False

                self.logger.info(self.tr(f"Persona {self.persona_id}: Parsed AI response: {ai_response_json} (تم تحليل استجابة الذكاء الاصطناعي)"))
            except json.JSONDecodeError:
                self.logger.error(self.tr(f"Persona {self.persona_id}: AI response is not valid JSON: {ai_response_raw} (استجابة الذكاء الاصطناعي ليست JSON صالحة)"))
                self.signals.status_updated.emit(self.persona_id, self.tr("AI Response Malformed! - استجابة الذكاء الاصطناعي غير صحيحة!"), "red")
                self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Selector AI response malformed.", self.persona_id)
                return False

            self.current_page_selectors['question_selector'] = ai_response_json.get('question_selector') or \
                                                               self.current_page_selectors['question_selector']
            self.current_page_selectors['option_container_selector'] = ai_response_json.get(
                'option_container_selector') or self.current_page_selectors['option_container_selector']
            self.current_page_selectors['option_label_selector'] = ai_response_json.get('option_label_selector') or \
                                                                   self.current_page_selectors['option_label_selector']
            self.current_page_selectors['option_input_selector'] = ai_response_json.get('option_input_selector') or \
                                                                   self.current_page_selectors['option_input_selector']
            self.current_page_selectors['submit_button_selector'] = ai_response_json.get('submit_button_selector') or \
                                                                    self.current_page_selectors[
                                                                        'submit_button_selector']
            self.current_page_selectors['input_type'] = ai_response_json.get('input_type', 'unknown')

            self.logger.info(self.tr(f"Persona {self.persona_id}: Selectors after AI learning (or fallback):"))
            for key, value in self.current_page_selectors.items():
                self.logger.info(f"  {key}: '{value}'")

            if any(ai_response_json.get(key) for key in
                   ['question_selector', 'option_container_selector', 'option_label_selector', 'option_input_selector',
                    'submit_button_selector']) or self.current_page_selectors['input_type'] != 'unknown':
                url_pattern_to_save = re.sub(r'(\?|&)(hsh|ck|qid)=[^&]*', '', self.page.url)
                save_dynamic_selectors(url_pattern_to_save, self.current_page_selectors)
                
                save_omran2_selector_knowledge(
                    current_url,
                    self.tr("تعلم المحددات من AI"),
                    json.dumps(self.current_page_selectors),
                    ai_response_raw
                )
                
                self.signals.status_updated.emit(self.persona_id, self.tr("AI learned page structure! - تعلم الذكاء الاصطناعي هيكل الصفحة!"), "light_blue_accent")
                return True
            else:
                self.logger.warning(self.tr(f"Persona {self.persona_id}: AI returned all empty selectors. Using existing/default selectors. (الذكاء الاصطناعي أعاد محددات فارغة بالكامل. جاري استخدام المحددات الحالية/الافتراضية.)"))
                self.signals.status_updated.emit(self.persona_id, self.tr("AI found no specific selectors. - الذكاء الاصطناعي لم يجد محددات محددة."), "orange_300")
                return False

        except Exception as e:
            self.logger.critical(self.tr(f"Persona {self.persona_id}: Failed to learn selectors from AI: {traceback.format_exc()} (فشل تعلم المحددات من الذكاء الاصطناعي)"))
            self.signals.status_updated.emit(self.persona_id, self.tr("AI Learning Failed! - فشل تعلم الذكاء الاصطناعي!"), "red")
            self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Selector AI learning failed: {e}", self.persona_id)
            return False
        finally:
            self.signals.ai_finished_processing.emit(self.persona_id)

    def is_on_question_page(self):
        try:
            current_q_selector = self.current_page_selectors['question_selector']
            self.logger.info(self.tr(f"Persona {self.persona_id}: Checking for YouGov question page using selector: Question='{current_q_selector}'. (جاري التحقق من صفحة سؤال YouGov)"))

            has_question_text_element = self.page.locator(YOUGOV_DEFAULT_QUESTION_TEXT_SELECTOR).count() > 0
            has_options_or_text_input = (
                        self.page.locator(self.current_page_selectors['option_container_selector']).count() > 0 or
                        self.page.locator(YOUGOV_DEFAULT_TEXT_AREA_INPUT_SELECTOR).count() > 0)
            has_submit_button = self.page.locator(self.current_page_selectors['submit_button_selector']).count() > 0

            is_survey_url = "survey2.yougov.com" in self.page.url or "yougov.com/survey" in self.page.url or "yougov.com/profiler" in self.page.url
            is_not_dashboard_or_region = not (
                        "dashboard" in self.page.url or "region" in self.page.url or "account.yougov.com" in self.page.url)

            if has_question_text_element and has_options_or_text_input and has_submit_button and is_survey_url and is_not_dashboard_or_region:
                self.logger.info(self.tr(f"Persona {self.persona_id}: Detected YouGov question page (Elements: Q={has_question_text_element}, Options/Text={has_options_or_text_input}, Submit={has_submit_button}, URL={is_survey_url}). (تم اكتشاف صفحة سؤال YouGov.)"))
                return True
            else:
                self.logger.info(self.tr(f"Persona {self.persona_id}: Not a recognized YouGov question page. Current URL: {self.page.url}"))
                return False
        except PlaywrightTimeoutError:
            self.logger.info(self.tr(f"Persona {self.persona_id}: YouGov question text selector not found within timeout. Current URL: {self.page.url} (لم يتم العثور على محدد نص سؤال YouGov ضمن المهلة.)"))
            return False
        except Exception as e:
            self.logger.warning(self.tr(f"Persona {self.persona_id}: Error checking for YouGov question page: {e}. Current URL: {self.page.url} (خطأ أثناء التحقق من صفحة سؤال YouGov.)"))
            self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Error checking question page: {e}", self.persona_id)
            return False

    def answer_survey(self):
        self.signals.status_updated.emit(self.persona_id, self.tr("Scanning YouGov Survey... - فحص استبيان YouGov..."), "blue")
        self.logger.info(self.tr(f"Persona {self.persona_id}: Attempting to identify question and options/input using current selectors. (جاري محاولة تحديد السؤال والخيارات/الإدخال.)"))

        try:
            question_selector = self.current_page_selectors['question_selector']
            option_container_selector = self.current_page_selectors['option_container_selector']
            option_label_selector = self.current_page_selectors['option_label_selector']
            option_input_selector = self.current_page_selectors['option_input_selector']
            submit_button_selector = self.current_page_selectors['submit_button_selector']
            current_input_type = self.current_page_selectors.get('input_type', 'unknown')

            self.logger.info(self.tr(f"Persona {self.persona_id}: Current selectors in use: Q='{question_selector}', OptCont='{option_container_selector}', OptLbl='{option_label_selector}', OptInp='{option_input_selector}', Submit='{submit_button_selector}', Type='{current_input_type}'."))

            question_containers = self.page.locator(
                "yg-question, yg-attitude, .survey-question-container, .question-wrapper, .question-group, .question-view, form.question-form, [role='main'] > div.question-view, [data-test='question-container'], .question-cont").all()

            if not question_containers:
                self.logger.warning(self.tr(f"Persona {self.persona_id}: Could not find distinct question containers. Falling back to treating the whole page as one question. (تعذر العثور على حاويات أسئلة. جاري معالجة الصفحة ككل.)"))
                question_containers = [self.page.locator('body')]

            self.signals.status_updated.emit(self.persona_id, self.tr(f"Found {len(question_containers)} potential questions. Answering... - تم العثور على {len(question_containers)} سؤال محتمل. جاري الإجابة..."), "blue")
            for i, container in enumerate(question_containers):
                if not self.is_running:
                    self.logger.info(self.tr(f"Persona {self.persona_id}: Stopping survey answering due to stop request."))
                    break

                self.logger.info(self.tr(f"Persona {self.persona_id}: Processing question container {i + 1} of {len(question_containers)}. (جاري معالجة حاوية السؤال.)"))

                current_question_locator = container.locator(question_selector) if container.locator(
                    question_selector).count() > 0 else self.page.locator(question_selector)

                try:
                    question_text = current_question_locator.text_content(timeout=5000).strip()
                    if not question_text:
                        question_text = current_question_locator.inner_text(timeout=5000).strip()
                except PlaywrightTimeoutError:
                    self.logger.warning(self.tr(f"Persona {self.persona_id}: Timeout getting text for question {i + 1} in container {i + 1}. (مهلة الحصول على نص الخيار.)"))
                    self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Timeout getting question text in survey.", self.persona_id)
                    continue
                except Exception as e_q_text:
                    self.logger.warning(self.tr(f"Persona {self.persona_id}: Error getting text for question {i + 1} in container {i + 1}: {e_q_text}. (خطأ في الحصول على نص الخيار.)"))
                    self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Error getting question text: {e_q_text}", self.persona_id)
                    continue

                if not question_text:
                    self.logger.warning(self.tr(f"Persona {self.persona_id}: No question text found in container {i + 1}. Skipping. (لم يتم العثور على نص سؤال في الحاوية.)"))
                    self.signals.omran_error_message.emit(f"Persona {self.persona_id}: No question text found in survey container.", self.persona_id)
                    continue

                self.logger.info(self.tr(f"Persona {self.persona_id}: Detected Question in container {i + 1}: '{question_text}' (تم اكتشاف السؤال)"))

                options_data = []
                options_text_list = []
                options_as_string = ""

                is_text_input_actual_in_container = container.locator(YOUGOV_DEFAULT_TEXT_AREA_INPUT_SELECTOR).count() > 0
                is_selection_type_actual_in_container = container.locator(option_container_selector).count() > 0

                if current_input_type == 'unknown':
                    if is_text_input_actual_in_container:
                        if container.locator("input[type='number']").count() > 0:
                            current_input_type = 'number'
                        else:
                            current_input_type = 'text'
                    elif is_selection_type_actual_in_container:
                        current_input_type = 'single_select'
                
                if self.current_page_selectors.get('input_type') != current_input_type:
                    self.current_page_selectors['input_type'] = current_input_type
                    url_pattern_to_save = re.sub(r'(\?|&)(hsh|ck|qid)=[^&]*', '', self.page.url)
                    save_dynamic_selectors(url_pattern_to_save, self.current_page_selectors)
                    self.logger.info(self.tr(f"Persona {self.persona_id}: Inferred and saved input_type as '{current_input_type}' for '{url_pattern_to_save}'."))


                self.logger.info(self.tr(f"Persona {self.persona_id}: Determined input type for container {i + 1}: '{current_input_type}'."))

                if current_input_type in ['single_select', 'multi_select', 'grid']:
                    self.logger.info(self.tr(f"Persona {self.persona_id}: Processing selection-based question in container {i + 1}. (جاري معالجة سؤال قائم على الاختيار.)"))
                    option_elements = container.locator(option_container_selector).all()

                    for j, el in enumerate(option_elements):
                        option_text = ""
                        try:
                            label_locator = el.locator(option_label_selector)
                            if label_locator.count() > 0:
                                option_text = label_locator.text_content(timeout=500).strip()
                                if not option_text:
                                    option_text = label_locator.inner_text(timeout=500).strip()
                            if not option_text:
                                option_text = el.text_content(timeout=500).strip()
                                if not option_text:
                                    option_text = el.inner_text(timeout=500).strip()
                        except PlaywrightTimeoutError:
                            self.logger.warning(self.tr(f"Persona {self.persona_id}: Timeout getting text for option {j + 1} in container {i + 1}. (مهلة الحصول على نص الخيار.)"))
                            self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Timeout getting option text in survey.", self.persona_id)
                            continue
                        except Exception as text_e:
                            self.logger.warning(self.tr(f"Persona {self.persona_id}: Error getting text for option {j + 1} in container {i + 1}: {text_e}. (خطأ في الحصول على نص الخيار.)"))
                            self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Error getting option text: {text_e}", self.persona_id)
                            continue

                        input_to_click_locator = None
                        try:
                            temp_input_locator = el.locator(option_input_selector) if option_input_selector else None
                            if temp_input_locator and temp_input_locator.count() > 0 and temp_input_locator.is_visible():
                                input_to_click_locator = temp_input_locator
                            else:
                                label_clickable_locator = el.locator(
                                    option_label_selector) if option_label_selector else None
                                if label_clickable_locator and label_clickable_locator.count() > 0 and label_clickable_locator.is_visible():
                                    input_to_click_locator = label_clickable_locator
                                else:
                                    if el.is_visible():
                                        input_to_click_locator = el
                        except Exception as loc_e:
                            self.logger.warning(self.tr(f"Persona {self.persona_id}: Error finding clickable element for option {j + 1} in container {i + 1}: {loc_e}. (خطأ في إيجاد العنصر القابل للنقر.)"))
                            self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Error finding clickable element for option: {loc_e}", self.persona_id)
                            input_to_click_locator = None

                        if option_text and input_to_click_locator:
                            options_data.append({
                                'text': option_text,
                                'input_locator': input_to_click_locator,
                                'container_element': el
                            })
                        else:
                            self.logger.warning(self.tr(f"Persona {self.persona_id}: Found option container but no valid text or clickable element for option {j + 1} in container {i + 1}. Skipping."))

                    options_text_list = [item['text'] for item in options_data]
                    options_as_string = ",".join(options_text_list)
                    self.logger.info(self.tr(f"Persona {self.persona_id}: Detected Options: '{options_as_string}'"))

                elif current_input_type in ['text', 'number']:
                    self.logger.info(self.tr(f"Persona {self.persona_id}: Processing text/number input question in container {i + 1}. (جاري معالجة سؤال إدخال نصي/رقمي.)"))
                    options_as_string = "TEXT_INPUT_QUESTION"
                    options_data = []

                else:
                    self.logger.warning(self.tr(f"Persona {self.persona_id}: Could not determine question type for container {i + 1} (final fallback). Skipping. (تعذر تحديد نوع السؤال في الحاوية.)"))
                    self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Could not determine question type in survey.", self.persona_id)
                    continue

                self.signals.status_updated.emit(self.persona_id, self.tr(f"Asking AI for answer (Q {i + 1})... - سؤال الذكاء الاصطناعي (سؤال {i + 1})..."), "deep_purple")
                self.logger.info(self.tr(f"Persona {self.persona_id}: Sending to Question AI: Persona ID={self.persona_id}, Question='{question_text}', Options='{options_as_string}', Type='{current_input_type}'"))

                self.signals.ai_started_processing.emit(self.persona_id)
                ai_response_full = self.question_ai_client.predict(self.persona_id, question_text, options_as_string,
                                                                    current_input_type, api_name="/predict")
                self.signals.ai_finished_processing.emit(self.persona_id)
                self.logger.info(self.tr(f"Persona {self.persona_id}: Received full AI response: {ai_response_full}"))

                if "[ERROR]" in ai_response_full:
                    self.logger.error(self.tr(f"Persona {self.persona_id}: Question AI returned an error for Q {i + 1}: {ai_response_full}"))
                    self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Question AI error: {ai_response_full}", self.persona_id)
                    continue

                internal_monologue_tag = "Internal Monologue:"
                recommended_options_tag = "Recommended Option(s):"
                detailed_persona_answer_tag = "Detailed Persona Answer:"

                internal_monologue = ""
                chosen_option_text = ""
                persona_specific_answer = ""

                start_mono = ai_response_full.find(internal_monologue_tag)
                start_rec_opt = ai_response_full.find(recommended_options_tag)
                start_detailed_ans = ai_response_full.find(detailed_persona_answer_tag)

                if start_mono != -1 and start_rec_opt != -1:
                    internal_monologue = ai_response_full[
                                         start_mono + len(internal_monologue_tag):start_rec_opt].strip()
                if start_rec_opt != -1 and start_detailed_ans != -1:
                    recommended_options_raw = ai_response_full[
                                              start_rec_opt + len(recommended_options_tag):start_detailed_ans].strip()
                elif start_rec_opt != -1:
                    recommended_options_raw = \
                    ai_response_full[start_rec_opt + len(recommended_options_tag):].strip().split('\n')[0].strip()

                if start_detailed_ans != -1:
                    persona_specific_answer = ai_response_full[
                                              start_detailed_ans + len(detailed_persona_answer_tag):].strip()
                else:
                    persona_specific_answer = ai_response_full.strip()

                if "Recommended Option(s): N/A" in recommended_options_raw or "N/A (Error occurred)." in recommended_options_raw:
                    chosen_option_text = ""
                    self.logger.info(self.tr(f"Persona {self.persona_id}: AI recommended N/A or error. Chosen option text set to empty."))
                else:
                    chosen_option_text = recommended_options_raw.replace("Recommended Option(s):", "").strip()
                    self.logger.info(self.tr(f"Persona {self.persona_id}: Extracted AI Recommended Option: '{chosen_option_text}'"))

                if current_input_type in ['text', 'number']:
                    if not chosen_option_text or chosen_option_text == "N/A":
                        chosen_option_text = persona_specific_answer
                        self.logger.info(self.tr(f"Persona {self.persona_id}: For text/number input, falling back to Detailed Persona Answer: '{chosen_option_text}'"))

                self.save_to_persona_history(self.persona_id, question_text, persona_specific_answer)
                self.logger.info(self.tr(f"Persona {self.persona_id}: Final AI choice for Q {i + 1} (used for action): 'تم اختيار {chosen_option_text}'"))

                if current_input_type in ['text', 'number']:
                    text_input_locator = container.locator(YOUGOV_DEFAULT_TEXT_AREA_INPUT_SELECTOR)
                    if text_input_locator.count() > 0:
                        text_to_type = chosen_option_text if chosen_option_text else self.tr("لا توجد إجابة محددة.")
                        self._human_like_type(text_input_locator, text_to_type)
                        self.signals.status_updated.emit(self.persona_id, self.tr(f"Q {i + 1} Text Input Filled! - سؤال {i + 1} تم تعبئة النص!"), "light_green_700")
                    else:
                        self.logger.warning(self.tr(f"Persona {self.persona_id}: Expected text input field in container {i + 1} but none found with selector '{YOUGOV_DEFAULT_TEXT_AREA_INPUT_SELECTOR}'."))
                        self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Expected text input but none found.", self.persona_id)
                elif current_input_type in ['single_select', 'multi_select', 'grid']:
                    best_match_option_found = False
                    chosen_option_container_element = None

                    for option_item in options_data:
                        if chosen_option_text.lower() == option_item['text'].lower():
                            chosen_actual_clickable_locator = option_item['input_locator']
                            chosen_option_container_element = option_item['container_element']
                            self.logger.info(self.tr(f"Persona {self.persona_id}: Clicking exact match '{option_item['text']}' in container {i + 1}."))
                            chosen_actual_clickable_locator.click(timeout=7000)
                            self.signals.status_updated.emit(self.persona_id, self.tr(f"Q {i + 1} Option selected! - سؤال {i + 1} تم تحديد الخيار!"), "light_green_700")
                            best_match_option_found = True
                            break

                    if not best_match_option_found and chosen_option_text:
                        options_to_click_from_ai = [opt.strip() for opt in chosen_option_text.split(',') if opt.strip()]

                        for opt_text_to_click in options_to_click_from_ai:
                            try:
                                strict_locator_container = container.locator(
                                    f"{option_container_selector}:has-text('{opt_text_to_click}')")

                                if strict_locator_container.count() > 0:
                                    input_within_strict_locator = strict_locator_container.locator(
                                        option_input_selector) if option_input_selector else strict_locator_container

                                    if input_within_strict_locator.count() > 0 and input_within_strict_locator.first.is_visible() and not input_within_strict_locator.first.is_disabled():
                                        chosen_actual_clickable_locator = input_within_strict_locator.first
                                        chosen_option_container_element = strict_locator_container.first
                                        self.logger.info(self.tr(f"Persona {self.persona_id}: Found exact text option using Playwright selector for '{opt_text_to_click}'. Clicking. (تم العثور على خيار بالنص الدقيق.)"))
                                        chosen_actual_clickable_locator.click(timeout=7000)
                                        self.signals.status_updated.emit(self.persona_id, self.tr(f"Q {i + 1} Option selected (by text)! - سؤال {i + 1} تم تحديد الخيار (بالنص)!"), "light_green_700")
                                        best_match_option_found = True
                                    else:
                                        self.logger.warning(self.tr(f"Persona {self.persona_id}: Element for '{opt_text_to_click}' found by :has-text but not visible or enabled. (العنصر موجود ولكنه غير مرئي أو غير مفعل.)"))
                                        self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Option '{opt_text_to_click}' not clickable.", self.persona_id)
                                else:
                                    self.logger.warning(self.tr(f"Persona {self.persona_id}: No option found with exact text '{opt_text_to_click}' using :has-text. (لم يتم العثور على خيار.)"))
                                    self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Option '{opt_text_to_click}' not found by text.", self.persona_id)
                            except Exception as text_select_e:
                                self.logger.error(self.tr(f"Persona {self.persona_id}: Error using :has-text selector for option '{opt_text_to_click}': {text_select_e}. (خطأ في محدد النص.)"))
                                self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Error selecting option by text: {text_select_e}", self.persona_id)

                    if not best_match_option_found:
                        self.logger.warning(self.tr(f"Persona {self.persona_id}: AI chose '{chosen_option_text}' but no valid or clickable option found. This might indicate AI provided a bad option name or option not found."))
                        self.signals.omran_error_message.emit(f"Persona {self.persona_id}: AI chose '{chosen_option_text}' but option not found/clickable.", self.persona_id)
                        increment_kick_count(self.persona_id)
                        self.signals.risk_updated.emit(self.persona_id)
                        self.signals.play_sound.emit()
                    
                    if best_match_option_found and persona_specific_answer and chosen_option_container_element:
                        associated_text_input = chosen_option_container_element.locator(
                            "textarea, input[type='text'], input[type='number']").first
                        
                        if associated_text_input.count() > 0 and associated_text_input.is_visible() and not associated_text_input.is_disabled():
                            self.logger.info(self.tr(f"Persona {self.persona_id}: Found associated text input for selected option. Typing persona-specific answer."))
                            self._human_like_type(associated_text_input, persona_specific_answer)
                            self.signals.status_updated.emit(self.persona_id, self.tr(f"Q {i + 1} Hybrid Text Filled! - سؤال {i + 1} تم تعبئة النص المختلط!"), "light_green_700")
                        else:
                            self.logger.info(self.tr(f"Persona {self.persona_id}: No visible/enabled associated text input found for selected option, or no persona_specific_answer provided."))


                time.sleep(random.uniform(self.min_delay, self.max_delay)) # استخدام إعدادات التأخير

            if not self.is_running:
                self.logger.info(self.tr(f"Persona {self.persona_id}: Stopping submit due to stop request."))
                return

            self.logger.info(self.tr(f"Persona {self.persona_id}: Finished processing all questions on page. Attempting to click submit button."))
            submit_button_locator = self.page.locator(submit_button_selector)
            if submit_button_locator.is_visible():
                self.logger.info(self.tr(f"Persona {self.persona_id}: Checking submit button '{submit_button_locator.element_handle().evaluate('el => el.outerHTML') if submit_button_locator.element_handle() else submit_button_locator}'. Visible: {submit_button_locator.is_visible()}, Enabled: {not submit_button_locator.is_disabled()}."))
                try:
                    submit_button_locator.wait_for(state='visible', timeout=10000)
                    submit_button_locator.click(timeout=5000)
                    self.signals.status_updated.emit(self.persona_id, self.tr("Submitted all answers! - تم إرسال كل الإجابات!"), "green")
                    self.signals.trigger_ui_answer_now.emit(self.persona_id, 10)
                except PlaywrightTimeoutError:
                    self.logger.warning(self.tr(f"Persona {self.persona_id}: Submit/Next button not enabled within timeout. Trying force click."))
                    self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Submit button timeout. Trying force click.", self.persona_id)
                    try:
                        submit_button_locator.click(force=True, timeout=5000)
                        self.signals.status_updated.emit(self.persona_id, self.tr("Submitted (Forced)! - تم الإرسال (بالقوة)!"), "green")
                        self.signals.trigger_ui_answer_now.emit(self.persona_id, 10)
                    except Exception as force_e:
                        self.logger.error(self.tr(f"Persona {self.persona_id}: Force click failed for submit button. Manual intervention may be needed. {force_e}"))
                        self.signals.status_updated.emit(self.persona_id, self.tr("Submit Failed! Manual! - فشل الإرسال! يدوي!"), "red")
                        self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Force submit failed: {force_e}", self.persona_id)
                        increment_kick_count(self.persona_id)
                        self.signals.risk_updated.emit(self.persona_id)
                        self.signals.play_sound.emit()
            else:
                self.logger.warning(self.tr(f"Persona {self.persona_id}: No submit button found after answering all questions. Manual intervention may be needed."))
                self.signals.status_updated.emit(self.persona_id, self.tr("No submit button found. - لم يتم العثور على زر إرسال."), "orange")
                self.signals.omran_error_message.emit(f"Persona {self.persona_id}: No submit button found after answering.", self.persona_id)
                increment_kick_count(self.persona_id)
                self.signals.risk_updated.emit(self.persona_id)
                self.signals.play_sound.emit()

        except Exception as e:
            self.logger.error(self.tr(f"Persona {self.persona_id}: Error in answer_survey: {traceback.format_exc()}"))
            self.signals.status_updated.emit(self.persona_id, self.tr(f"Survey answer failed: {e.__class__.__name__}"), "red")
            self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Survey answer failed: {e}", self.persona_id)
            increment_kick_count(self.persona_id)
            self.signals.risk_updated.emit(self.persona_id)
            self.signals.play_sound.emit()

    def run(self):
        try:
            self.logger.info(self.tr(f"Persona {self.persona_id}: Thread starting... (بدء تشغيل الخيط)"))

            max_retries_ai_connect = 3
            for attempt in range(max_retries_ai_connect):
                if not self.is_running: return
                try:
                    self.signals.status_updated.emit(self.persona_id, self.tr(f"Connecting to Question AI (Attempt {attempt + 1}/{max_retries_ai_connect})... - الاتصال بالذكاء الاصطناعي (أسئلة)..."), "teal")
                    self.logger.info(self.tr(f"Persona {self.persona_id}: Attempting to connect to Question AI at {self.question_ai_url}. (جاري محاولة الاتصال بالذكاء الاصطناعي للأسئلة.)"))
                    time.sleep(random.uniform(self.min_delay, self.max_delay)) # استخدام إعدادات التأخير
                    self.question_ai_client = Client(self.question_ai_url)
                    self.logger.info(self.tr(f"Persona {self.persona_id}: Successfully connected to Question AI client. (تم الاتصال بنجاح بالذكاء الاصطناعي للأسئلة.)"))
                    break
                except Exception as e:
                    self.logger.critical(self.tr(f"Persona {self.persona_id}: Failed to connect to Question AI client (Attempt {attempt + 1}/{max_retries_ai_connect}): {traceback.format_exc()} (فشل الاتصال بالذكاء الاصطناعي للأسئلة.)"))
                    self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Failed to connect to Question AI: {e}", self.persona_id)
                    if attempt < max_retries_ai_connect - 1:
                        time.sleep(random.uniform(5, 10))
                    else:
                        self.signals.status_updated.emit(self.persona_id, self.tr("Question AI Connection Failed! - فشل اتصال الذكاء الاصطناعي (أسئلة)!"), "red")
                        self.is_running = False
                        return

            for attempt in range(max_retries_ai_connect):
                if not self.is_running: return
                try:
                    self.signals.status_updated.emit(self.persona_id, self.tr(f"Connecting to Selector AI (Attempt {attempt + 1}/{max_retries_ai_connect})... - الاتصال بالذكاء الاصطناعي (محددات)..."), "blue_grey_700")
                    self.logger.info(self.tr(f"Persona {self.persona_id}: Attempting to connect to Selector AI at {self.selector_ai_url}. (جاري محاولة الاتصال بالذكاء الاصطناعي للمحددات.)"))
                    time.sleep(random.uniform(self.min_delay, self.max_delay)) # استخدام إعدادات التأخير
                    self.selector_ai_client = Client(self.selector_ai_url)
                    self.logger.info(self.tr(f"Persona {self.persona_id}: Successfully connected to Selector AI client. (تم الاتصال بنجاح بالذكاء الاصطناعي للمحددات.)"))
                    break
                except Exception as e:
                    self.logger.critical(self.tr(f"Persona {self.persona_id}: Failed to connect to Selector AI client (Attempt {attempt + 1}/{max_retries_ai_connect}): {traceback.format_exc()} (فشل الاتصال بالذكاء الاصطناعي للمحددات.)"))
                    self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Failed to connect to Selector AI: {e}", self.persona_id)
                    if attempt < max_retries_ai_connect - 1:
                        time.sleep(random.uniform(5, 10))
                    else:
                        self.signals.status_updated.emit(self.persona_id, self.tr("Selector AI Connection Failed! - فشل اتصال الذكاء الاصطناعي (محددات)!"), "red")
                        self.is_running = False
                        return

            random_user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Firefox/121.0",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0",
            ]

            random_viewports = [
                {'width': 1366, 'height': 768}, {'width': 1920, 'height': 1080},
                {'width': 1536, 'height': 864}, {'width': 1440, 'height': 900},
                {'width': 1600, 'height': 900}
            ]

            random_locales = [
                'en-US', 'en-GB', 'fr-FR', 'de-DE', 'es-ES', 'it-IT'
            ]

            random_user_agent = random.choice(random_user_agents)
            random_viewport = random.choice(random_viewports)
            random_locale = random.choice(random_locales)

            self.logger.info(self.tr(f"Persona {self.persona_id}: Using digital fingerprint: User-Agent='{random_user_agent}', Viewport='{random_viewport}', Locale='{random_locale}' (جاري استخدام بصمة رقمية عشوائية.)"))

            with sync_playwright() as p:
                user_data_dir = os.path.join(PROFILES_DIR, f"persona_{self.persona_id}_profile")
                os.makedirs(user_data_dir, exist_ok=True)

                try:
                    self.context = p.chromium.launch_persistent_context(
                        user_data_dir,
                        headless=self.headless,
                        args=['--disable-blink-features=AutomationControlled', '--start-maximized'],
                        user_agent=random_user_agent,
                        viewport=random_viewport,
                        locale=random_locale,
                        accept_downloads=True,
                        ignore_https_errors=True,
                        proxy=self.proxy
                    )
                    self.browser = self.context.browser
                    self.page = self.context.new_page()
                    self.page.set_default_timeout(60000)
                    self.logger.info(self.tr(f"Persona {self.persona_id}: Browser and page context initialized. (تم تهيئة المتصفح وسياق الصفحة.)"))
                except Exception as e:
                    self.logger.critical(self.tr(f"Persona {self.persona_id}: Failed to launch browser with proxy {self.proxy}: {traceback.format_exc()} (فشل تشغيل المتصفح مع البروكسي.)"))
                    self.signals.status_updated.emit(self.persona_id, self.tr("Browser Launch Failed! - فشل تشغيل المتصفح!"), "red")
                    self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Browser launch with proxy failed: {e}", self.persona_id)
                    self.is_running = False
                    return


                if not self.perform_semi_auto_login():
                    self.logger.error(self.tr(f"Persona {self.persona_id}: Semi-auto login failed or was not completed. Stopping thread. (فشل تسجيل الدخول شبه التلقائي أو لم يكتمل. جاري إيقاف الخيط.)"))
                    self.is_running = False
                    return

                self.logger.info(self.tr(f"Persona {self.persona_id}: Initial login step complete. Waiting for user to click 'Answer Now'. (خطوة تسجيل الدخول الأولية مكتملة. في انتظار نقر المستخدم على 'أجب الآن'.)"))
                self.signals.status_updated.emit(self.persona_id, self.tr("Ready! Click 'Answer Now' to proceed. - جاهز! انقر 'أجب الآن' للمتابعة."), "light_green_700")

                while self.is_running:
                    try:
                        if self.force_selector_learning:
                            self.logger.info(self.tr(f"Persona {self.persona_id}: Manual selector learning triggered from UI. (تم تفعيل تعلم المحددات يدوياً من واجهة المستخدم.)"))
                            self.force_selector_learning = False
                            if not self._learn_selectors_from_ai():
                                self.logger.warning(self.tr(f"Persona {self.persona_id}: Manual selector learning failed. (فشل تعلم المحددات يدوياً.)"))
                                self.signals.status_updated.emit(self.persona_id, self.tr("Manual Learning Failed! - فشل التعلم اليدوي!"), "red_500")
                                self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Manual selector learning failed.", self.persona_id)
                                time.sleep(random.uniform(self.min_delay, self.max_delay)) # استخدام إعدادات التأخير
                            else:
                                self.signals.status_updated.emit(self.persona_id, self.tr("Manual Learning Complete! - اكتمل التعلم اليدوي!"), "light_green_700")
                                time.sleep(random.uniform(1, 2))
                            continue


                        if not self.force_answer_now:
                            self.logger.info(self.tr(f"Persona {self.persona_id}: Waiting for manual 'Answer Now' trigger from UI. Current URL: {self.page.url}"))
                            time.sleep(1)
                            continue

                        self.logger.info(self.tr(f"Persona {self.persona_id}: 'Answer Now' button clicked or triggered from UI. Proceeding. (تم النقر على 'أجب الآن' من واجهة المستخدم. جاري المتابعة.)"))
                        self.force_answer_now = False

                        current_url = self.page.url
                        self.logger.info(self.tr(f"Persona {self.persona_id}: Current URL: {current_url} (الرابط الحالي)"))
                        self.signals.status_updated.emit(self.persona_id, self.tr(f"Checking URL: {current_url[:50]}..."), "cyan_700")

                        current_url_pattern = re.sub(r'(\?|&)(hsh|ck|qid)=[^&]*', '', current_url)
                        saved_selectors = get_dynamic_selectors(current_url_pattern)

                        should_learn_new_selectors = False
                        if saved_selectors:
                            self.current_page_selectors.update(saved_selectors)
                            self.logger.info(self.tr(f"Persona {self.persona_id}: Loaded dynamic selectors for '{current_url_pattern}'. (تم تحميل المحددات الديناميكية)"))
                        else:
                            self.logger.info(self.tr(f"Persona {self.persona_id}: No complete dynamic selectors found for '{current_url_pattern}'. Will attempt to learn. (لم يتم العثور على محددات ديناميكية كاملة، ستحاول التعلم.)"))
                            should_learn_new_selectors = True

                        if self.current_page_selectors.get('input_type') == 'unknown' or \
                                not self.current_page_selectors.get('question_selector') or \
                                not self.current_page_selectors.get('submit_button_selector'):
                            self.logger.info(self.tr(f"Persona {self.persona_id}: Core selectors are missing/unknown. Forcing learning of new selectors. (المحددات الأساسية مفقودة/غير معروفة. جاري فرض تعلم محددات جديدة.)"))
                            should_learn_new_selectors = True

                        if should_learn_new_selectors:
                            if not self._learn_selectors_from_ai():
                                self.logger.warning(self.tr(f"Persona {self.persona_id}: Failed to learn selectors for '{current_url}'. Cannot proceed without them. (فشل تعلم المحددات. لا يمكن المتابتابعة.)"))
                                self.signals.status_updated.emit(self.persona_id, self.tr("Learning Failed! Waiting for Manual Trigger. - فشل التعلم! جاري انتظار التشغيل اليدوي."), "red_500")
                                self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Auto selector learning failed for {current_url}.", self.persona_id)
                                time.sleep(random.uniform(self.min_delay, self.max_delay)) # استخدام إعدادات التأخير
                                continue

                        if self.is_on_question_page():
                            self.signals.status_updated.emit(self.persona_id, self.tr("Survey question page detected. Answering... - تم اكتشاف صفحة سؤال الاستبيان. جاري الإجابة..."), "indigo")
                            self.answer_survey()
                            continue

                        self.logger.info(self.tr(f"Persona {self.persona_id}: Not on a question page. Assuming current survey is finished or no survey found. Navigating to dashboard."))
                        self.signals.status_updated.emit(self.persona_id, self.tr("Survey finished or not found. Navigating Dashboard. - انتهى الاستبيان أو لم يتم العثور عليه. جاري الانتقال إلى لوحة التحكم."), "orange_300")
                        self.page.goto(BASE_URL + "/dashboard", wait_until='domcontentloaded')
                        time.sleep(random.uniform(self.min_delay, self.max_delay)) # استخدام إعدادات التأخير
                        self.signals.status_updated.emit(self.persona_id, self.tr("No more surveys. Ready for manual trigger. - لا توجد استبيانات أخرى. جاهز للتشغيل اليدوي."), "light_green_700")
                        continue

                    except PlaywrightTimeoutError as e:
                        if not self.is_running: break
                        self.logger.error(self.tr(f"Persona {self.persona_id}: Playwright Timeout Error: {e}. Full traceback: {traceback.format_exc()} (خطأ مهلة Playwright.)"))
                        self.signals.status_updated.emit(self.persona_id, self.tr("Page Timeout! Waiting for Manual Trigger. - مهلة الصفحة! جاري انتظار التشغيل اليدوي."), "deep_orange")
                        self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Page Timeout: {e}", self.persona_id)
                        self.force_answer_now = False
                        increment_kick_count(self.persona_id)
                        self.signals.risk_updated.emit(self.persona_id)
                        self.signals.play_sound.emit()
                        time.sleep(random.uniform(self.min_delay, self.max_delay)) # استخدام إعدادات التأخير
                        continue

                    except Exception as e:
                        if not self.is_running or "closed" in str(e).lower() or "disconnected" in str(e).lower():
                            self.logger.info(self.tr(f"Persona {self.persona_id}: Loop interrupted due to stop request or browser closure: {e} (تم مقاطعة الحلقة بسبب طلب الإيقاف أو إغلاق المتصفح.)"))
                            break
                        self.logger.critical(self.tr(f"Persona {self.persona_id}: Critical error in main loop: {traceback.format_exc()} (خطأ فادح في الحلقة الرئيسية.)"))
                        self.signals.status_updated.emit(self.persona_id, self.tr("Loop Error! Waiting for Manual Trigger. - خطأ في الحلقة! جاري انتظار التشغيل اليدوي."), "red")
                        self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Critical loop error: {e}", self.persona_id)
                        self.force_answer_now = False
                        increment_kick_count(self.persona_id)
                        self.signals.risk_updated.emit(self.persona_id)
                        self.signals.play_sound.emit()
                        time.sleep(random.uniform(self.min_delay + 5, self.max_delay + 10)) # تأخير أطول للأخطاء الحرجة
                        continue

        except Exception as e:
            self.logger.critical(self.tr(f"Persona {self.persona_id}: Unhandled critical error, thread aborting: {traceback.format_exc()} (خطأ حرج غير معالج، جاري إنهاء الخيط.)"))
            self.signals.status_updated.emit(self.persona_id, self.tr("CRITICAL INIT ERROR - خطأ بدء حرج"), "red_900")
            self.signals.omran_error_message.emit(f"Persona {self.persona_id}: Critical initialization error: {e}", self.persona_id)
            self.signals.play_sound.emit()
        finally:
            self.logger.info(self.tr(f"Persona {self.persona_id}: Thread is finishing. (الخيط ينتهي.)"))
            # **التصحيح هنا**: إضافة تحقق لإغلاق موارد Playwright بشكل آمن
            if self.browser and self.browser.is_connected():
                try:
                    if self.page and hasattr(self.page, 'is_closed') and not self.page.is_closed():
                        self.page.close()
                    if self.context and self.context.is_connected(): # تحقق إضافي للسياق
                        self.context.close()
                    # لا تغلق المتصفح هنا إذا كان PersistentContext
                    # self.browser.close() 
                    self.logger.info(self.tr(f"Persona {self.persona_id}: Playwright resources closed in finally block."))
                except Exception as e:
                    self.logger.error(self.tr(f"Persona {self.persona_id}: Error closing Playwright resources in finally: {traceback.format_exc()}"))
                finally:
                    self.page = None
                    self.context = None
                    # لا تعيد تعيين self.browser = None هنا إذا كنت تستخدم PersistentContext
            self.signals.status_updated.emit(self.persona_id, self.tr("Stopped - توقف"), "grey")

    # إضافة دالة tr لترجمة النصوص داخل AutomationThread
    def tr(self, text):
        return QApplication.instance().translate("AutomationThread", text)


# ==============================================================================
# --- 5. Helper Dialogs and Widgets (Defined before MainWindow) ---
# ==============================================================================

class OmranChatWidget(QWidget): # تغيير اسم الفئة
    def __init__(self, worker_signals: WorkerSignals, get_gemini_api_key_func, parent=None): # إضافة get_gemini_api_key_func
        super().__init__(parent)
        self.setWindowTitle(self.tr("محادثة Omran")) # تغيير العنوان
        self.worker_signals = worker_signals
        self.last_error_message = ""
        self.get_gemini_api_key = get_gemini_api_key_func # دالة للحصول على المفتاح

        self.init_ui()
        self.connect_signals()

        # تهيئة نموذج Gemini
        self.gemini_model = None
        self.conversation = None # للحفاظ على سياق المحادثة
        self._init_gemini_model()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5) # تقليل الهوامش
        self.setStyleSheet("background-color: #2e2e2e; border-radius: 10px; border: 1px solid #424242;") # إضافة حدود

        title_label = QLabel(self.tr("محادثة Omran")) # تغيير العنوان
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #BBDEFB; padding: 5px; margin-bottom: 5px;") # خط أصغر قليلاً
        main_layout.addWidget(title_label)

        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        self.chat_history.setFont(QFont("Cairo", 10)) # خط أكبر
        self.chat_history.setStyleSheet("""
            QTextEdit {
                background-color: #1A1A1A;
                color: #e0e0e0;
                border-radius: 8px;
                padding: 8px; /* تقليل البادينج */
                border: 1px solid #424242;
            }
            p { /* لتنسيق فقرات الرسائل */
                margin-bottom: 3px; /* مسافة أقل بين الرسائل */
            }
        """)
        main_layout.addWidget(self.chat_history)

        # مؤشر الكتابة
        self.typing_indicator_label = QLabel(self.tr("Omran يكتب..."))
        self.typing_indicator_label.setStyleSheet("color: #9E9E9E; font-style: italic; font-size: 10px;")
        self.typing_indicator_label.hide()
        main_layout.addWidget(self.typing_indicator_label)


        input_layout = QHBoxLayout()
        self.user_input_field = QLineEdit()
        self.user_input_field.setPlaceholderText(self.tr("اكتب رسالتك هنا لـ Omran..."))
        self.user_input_field.setFont(QFont("Cairo", 10)) # خط أكبر
        self.user_input_field.setStyleSheet("background-color: #3a3a3a; color: #e0e0e0; border-radius: 8px; padding: 6px; border: 1px solid #555;") # بادينج أقل
        self.user_input_field.returnPressed.connect(self.send_message)
        input_layout.addWidget(self.user_input_field)

        self.send_button = QPushButton(self.tr("إرسال"))
        self.send_button.setFont(QFont("Cairo", 10, QFont.Bold)) # خط أكبر
        self.send_button.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                border-radius: 6px; /* زوايا أقل استدارة */
                padding: 6px 12px; /* بادينج أقل */
                border: none;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
        """)
        self.send_button.clicked.connect(self.send_message)
        input_layout.addWidget(self.send_button)

        main_layout.addLayout(input_layout)

        action_buttons_layout = QHBoxLayout()
        action_buttons_layout.setSpacing(5) # مسافة أقل بين الأزرار

        self.help_error_button = QPushButton(self.tr("مساعدة في آخر خطأ"))
        self.help_error_button.setFont(QFont("Cairo", 9)) # خط أصغر
        self.help_error_button.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                border-radius: 6px;
                padding: 6px 10px;
                border: none;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
            QPushButton:disabled {
                background-color: #6c757d;
            }
        """)
        self.help_error_button.clicked.connect(self.request_error_help)
        self.help_error_button.setEnabled(False)
        action_buttons_layout.addWidget(self.help_error_button)

        self.ask_free_ai_button = QPushButton(self.tr("اسأل AI سؤال حر"))
        self.ask_free_ai_button.setFont(QFont("Cairo", 9))
        self.ask_free_ai_button.setStyleSheet("""
            QPushButton {
                background-color: #673AB7; /* Deep Purple */
                color: white;
                border-radius: 6px;
                padding: 6px 10px;
                border: none;
            }
            QPushButton:hover {
                background-color: #7E57C2;
            }
        """)
        self.ask_free_ai_button.clicked.connect(self.ask_free_ai_question)
        action_buttons_layout.addWidget(self.ask_free_ai_button)

        self.clear_chat_button = QPushButton(self.tr("مسح المحادثة"))
        self.clear_chat_button.setFont(QFont("Cairo", 9)) # خط أصغر
        self.clear_chat_button.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border-radius: 6px;
                padding: 6px 10px;
                border: none;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
        """)
        self.clear_chat_button.clicked.connect(self.clear_chat)
        action_buttons_layout.addWidget(self.clear_chat_button)

        main_layout.addLayout(action_buttons_layout)

        self.append_message(self.tr("Omran"), self.tr("مرحباً! أنا Omran، مساعدك الذكي. كيف يمكنني مساعدتك اليوم؟"), "#4CAF50")

    def connect_signals(self):
        pass

    def _init_gemini_model(self):
        """تهيئة نموذج Gemini."""
        api_key = self.get_gemini_api_key()
        if not api_key:
            self.append_message(self.tr("Omran"), self.tr("لم يتم تكوين مفتاح Gemini API. لن أتمكن من الإجابة على الأسئلة الحرة. (يرجى إدخال المفتاح في إعدادات AI)."), "#FFC107")
            return

        try:
            genai.configure(api_key=api_key)
            self.gemini_model = genai.GenerativeModel('gemini-pro') # يمكن تغيير النموذج حسب الحاجة
            self.conversation = self.gemini_model.start_chat(history=[])
            self.append_message(self.tr("Omran"), self.tr("تم الاتصال بنجاح بـ Gemini. أنا الآن Omran، مساعدك الذكي!"), "#4CAF50")
        except Exception as e:
            self.append_message(self.tr("Omran"), self.tr(f"خطأ في تهيئة Gemini API: {e}. يرجى التحقق من المفتاح."), "#F44336")
            logging.error(f"Gemini API initialization error: {e}")

    def append_message(self, sender, message, color):
        # تنسيق رسائل المستخدم و Omran بشكل مختلف
        if sender == self.tr("أنت"): # استخدم self.tr
            html_message = f"<div style='text-align: right; margin-bottom: 5px;'>" \
                           f"<span style='background-color: #007bff; color: white; padding: 6px 10px; border-radius: 12px; max-width: 80%; display: inline-block; text-align: left;'>{message}</span>" \
                           f"<br><span style='font-size: 0.8em; color: #9E9E9E; margin-top: 2px; display: inline-block;'>{sender}</span>" \
                           f"</div>"
        else: # Omran or AI messages
            html_message = f"<div style='text-align: left; margin-bottom: 5px;'>" \
                           f"<span style='background-color: #424242; color: #e0e0e0; padding: 6px 10px; border-radius: 12px; max-width: 80%; display: inline-block;'>{message}</span>" \
                           f"<br><span style='font-size: 0.8em; color: #9E9E9E; margin-top: 2px; display: inline-block;'>{sender}</span>" \
                           f"</div>"

        cursor = self.chat_history.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(html_message)
        self.chat_history.verticalScrollBar().setValue(self.chat_history.verticalScrollBar().maximum())

    def send_message(self):
        user_message = self.user_input_field.text().strip()
        if not user_message:
            return

        self.append_message(self.tr("أنت"), user_message, "#ADD8E6")
        self.user_input_field.clear()

        # المنطق المحلي لأخطاء ومحددات البوت له الأولوية
        user_query_lower = user_message.lower()
        if "خطأ" in user_query_lower or "مشكلة" in user_query_lower or "error" in user_query_lower:
            omran_response = self.get_omran_simulated_response(user_message)
            self.append_message(self.tr("Omran"), omran_response, "#4CAF50")
            return
        
        if "محدد" in user_query_lower or "selector" in user_query_lower or "element" in user_query_lower:
            omran_response = self.get_omran_simulated_response(user_message)
            self.append_message(self.tr("Omran"), omran_response, "#4CAF50")
            return

        # إرسال السؤال إلى Gemini
        self.typing_indicator_label.show() # إظهار مؤشر الكتابة
        QApplication.processEvents() # لتحديث الواجهة وعرض "جاري التفكير"

        def _ask_gemini_in_thread():
            try:
                if self.gemini_model and self.conversation:
                    response = self.conversation.send_message(user_message)
                    gemini_answer = response.text
                    QTimer.singleShot(0, lambda: self.append_message(self.tr("Omran"), gemini_answer, "#4CAF50"))
                else:
                    QTimer.singleShot(0, lambda: self.append_message(self.tr("Omran"), self.tr("نموذج Gemini غير مهيأ أو مفتاح API مفقود. (راجع الإعدادات)."), "#FFC107"))
            except Exception as e:
                logging.error(f"Error querying Gemini: {e}")
                QTimer.singleShot(0, lambda: self.append_message(self.tr("Omran"), self.tr(f"عذراً، حدث خطأ أثناء الاتصال بـ Gemini: {e}"), "#F44336"))
            finally:
                QTimer.singleShot(0, self.typing_indicator_label.hide) # إخفاء مؤشر الكتابة
        
        threading.Thread(target=_ask_gemini_in_thread, daemon=True).start()


    def get_omran_simulated_response(self, user_query): # تغيير اسم الدالة
        user_query_lower = user_query.lower()

        if "خطأ" in user_query_lower or "مشكلة" in user_query_lower or "error" in user_query_lower:
            if self.last_error_message:
                return self.tr(f"بالتأكيد، آخر خطأ واجهته هو: '{self.last_error_message}'. " \
                       f"عادةً ما تشير هذه الأخطاء إلى مشكلات في الشبكة أو المحددات. " \
                       f"يرجى التحقق من اتصالك بالإنترنت وصحة المحددات المستخدمة. " \
                       f"هل تريد مني تحليل هذا الخطأ بشكل أعمق؟")
            else:
                return self.tr("لم أجد أي أخطاء حديثة. يرجى وصف المشكلة التي تواجهها.")

        if "محدد" in user_query_lower or "selector" in user_query_lower or "element" in user_query_lower:
            knowledge = get_omran2_selector_knowledge(description=user_query)
            if knowledge:
                response = self.tr("لقد وجدت بعض المعلومات حول المحددات:\n")
                for url, desc, sel_val, exp in knowledge:
                    response += self.tr(f"- الوصف: '{desc}', المحدد: '{sel_val}', الشرح: '{exp}', المصدر: {url}\n")
                response += self.tr("هل هذا يساعدك؟")
                return response
            else:
                return self.tr("المحددات مهمة جدًا! لكي أساعدك بشكل أفضل، نحتاج إلى محتوى HTML والسؤال عن العنصر الذي تبحث عنه. " \
                       "هل يمكنك تزويدي بمحتوى HTML الحالي أو وصف العنصر؟")

        if "تنظيم حركة المرور" in user_query_lower or "traffic" in user_query_lower or "rate limit" in user_query_lower:
            return self.tr("لتنظيم حركة المرور وتجنب الحظر أثناء الاستخلاص، أوصي بما يلي:\n" \
                   "1. إضافة تأخيرات عشوائية بين الطلبات (مثل 2-5 ثوانٍ).\n" \
                   "2. تدوير وكلاء المستخدم (User-Agents).\n" \
                   "3. استخدام وكلاء IP (Proxies) إذا كنت تقوم بطلبات مكثفة.\n" \
                   "4. مراقبة استجابات الخادم لأي رموز حالة HTTP غير اعتيادية (مثل 429 Too Many Requests).\n" \
                   "هل تريد معرفة المزيد عن أي من هذه النقاط؟")

        if "كيف" in user_query_lower or "شرح" in user_query_lower or "تعليم" in user_query_lower:
            return self.tr("أنا هنا لمساعدتك في فهم كيفية عمل التطبيق وحل المشكلات. " \
                   "ماذا تريد أن تتعلم أو تفهم؟ يمكنك سؤالي عن: \n" \
                   "- كيفية استخدام ميزات معينة.\n" \
                   "- أفضل الممارسات لاستخلاص الويب.\n" \
                   "- تفسير الأخطاء.")

        if "مرحبا" in user_query_lower or "سلام" in user_query_lower or "hi" in user_query_lower:
            return self.tr("أهلاً بك! كيف يمكنني مساعدتك اليوم؟")

        return self.tr("أنا Omran، مساعدك الذكي. لم أفهم سؤالك تمامًا. هل يمكنك إعادة صياغته أو سؤالي عن شيء آخر؟") \
               + self.tr("تذكر أنني أستطيع المساعدة في الأخطاء، المحددات، تنظيم حركة المرور، وشرح وظائف التطبيق.")

    def set_last_error(self, error_message: str):
        self.last_error_message = error_message
        self.help_error_button.setEnabled(True)
        self.append_message(self.tr("Omran"), self.tr(f"لقد اكتشفت خطأً جديدًا: '{error_message}'. " \
                                       "يمكنك النقر على 'مساعدة في آخر خطأ' لطلب المساعدة."), "#FFD700")

    def request_error_help(self):
        if self.last_error_message:
            self.append_message(self.tr("أنت"), self.tr("مساعدة في آخر خطأ"), "#ADD8E6")
            omran_response = self.get_omran_simulated_response(self.tr(f"حل مشكلة الخطأ التالي: {self.last_error_message}"))
            self.append_message(self.tr("Omran"), omran_response, "#4CAF50")
        else:
            self.append_message(self.tr("Omran"), self.tr("لا يوجد خطأ حالي لأقدم المساعدة فيه."), "#FFD700")

    def handle_selector_ai_response(self, url, question, response_json_string):
        try:
            response_data = json.loads(response_json_string)
            formatted_response = self.tr(f"استجابة AI المحددات لـ URL: {url}\n")
            formatted_response += self.tr(f"السؤال: {question}\n")
            formatted_response += self.tr("المحددات المقترحة:\n")
            for key, value in response_data.items():
                formatted_response += self.tr(f"- {key}: {value}\n")
            self.append_message(self.tr("Omran (AI المحددات)"), formatted_response, "#ADD8E6")
            
            if response_data.get('question_selector') and response_data.get('submit_button_selector'):
                self.append_message(self.tr("Omran"), self.tr("لقد تعلمت المحددات الجديدة لهذه الصفحة بنجاح! سأقوم بحفظها للاستخدام المستقبلي."), "#4CAF50")
            else:
                self.append_message(self.tr("Omran"), self.tr("لم أتمكن من تحديد جميع المحددات لهذه الصفحة. قد تحتاج إلى مراجعتها يدوياً."), "#FFD700")

        except json.JSONDecodeError:
            self.append_message(self.tr("Omran (AI المحددات)"), self.tr(f"استجابة غير صالحة من AI المحددات: {response_json_string}"), "#F44336")
            self.append_message(self.tr("Omran"), self.tr("يبدو أن استجابة AI المحددات لم تكن بالتنسيق المتوقع. يرجى التحقق من إعدادات Gradio AI."), "#FFD700")
        except Exception as e:
            self.append_message(self.tr("Omran (AI المحددات)"), self.tr(f"خطأ في معالجة استجابة AI المحددات: {e}"), "#F44336")
            self.append_message(self.tr("Omran"), self.tr("حدث خطأ أثناء معالجة استجابة AI المحددات. يرجى التحقق من السجلات."), "#FFD700")

    def ask_free_ai_question(self):
        # الآن هذه الدالة تستدعي send_message التي تتعامل مع Gemini
        self.send_message()

    def clear_chat(self):
        self.chat_history.clear()
        self.append_message(self.tr("Omran"), self.tr("مرحباً! أنا Omran، مساعدك الذكي. كيف يمكنني مساعدتك اليوم؟"), "#4CAF50")
        self.last_error_message = ""
        self.help_error_button.setEnabled(False)

    # إضافة دالة tr لترجمة النصوص داخل OmranChatWidget
    def tr(self, text):
        return QApplication.instance().translate("OmranChatWidget", text)


class ErrorDetailsDialog(QDialog):
    def __init__(self, persona_id: int, error_message: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr(f"تفاصيل الخطأ - الشخصية #{persona_id}"))
        self.setFixedSize(500, 350)
        self.setStyleSheet("""
            QDialog {
                background-color: #263238; /* Darker Blue Grey */
                border-radius: 10px;
            }
            QLabel {
                color: #CFD8DC;
                font-size: 14px;
            }
            QTextEdit {
                background-color: #1A1A1A;
                color: #E0E0E0;
                border: 1px solid #424242;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton {
                background-color: #F44336; /* Red */
                color: white;
                padding: 10px 20px;
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #E53935;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title_label = QLabel(self.tr(f"خطأ في الشخصية #{persona_id}"))
        title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #F44336;")
        layout.addWidget(title_label, alignment=Qt.AlignCenter)

        error_label = QLabel(self.tr("رسالة الخطأ:"))
        error_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(error_label)

        error_text_edit = QTextEdit()
        error_text_edit.setReadOnly(True)
        error_text_edit.setText(error_message)
        layout.addWidget(error_text_edit)

        suggestions_label = QLabel(self.tr("اقتراحات الإصلاح:"))
        suggestions_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(suggestions_label)

        suggestions_text_edit = QTextEdit()
        suggestions_text_edit.setReadOnly(True)
        suggestions_text_edit.setText(self._get_suggestions_for_error(error_message))
        layout.addWidget(suggestions_text_edit)

        close_button = QPushButton(self.tr("إغلاق"))
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, alignment=Qt.AlignCenter)

    def _get_suggestions_for_error(self, error_message: str) -> str:
        error_message_lower = error_message.lower()
        suggestions = []

        if "timeout" in error_message_lower:
            suggestions.append(self.tr("- تحقق من اتصالك بالإنترنت والبروكسي (إذا كنت تستخدمه)."))
            suggestions.append(self.tr("- قد تكون سرعة الإنترنت بطيئة، حاول زيادة مهلة الانتظار في الكود (timeout)."))
            suggestions.append(self.tr("- قد يكون الموقع بطيئًا في الاستجابة أو تحت ضغط عالٍ."))
            suggestions.append(self.tr("- تأكد من أن المحددات صحيحة وأن العنصر يظهر على الصفحة في الوقت المناسب."))
        if "selector" in error_message_lower or "element" in error_message_lower or "locator" in error_message_lower:
            suggestions.append(self.tr("- المحدد (Selector) المستخدم قد يكون غير صحيح أو تغير على الموقع."))
            suggestions.append(self.tr("- استخدم أداة فحص العناصر في المتصفح للتحقق من المحددات الصحيحة."))
            suggestions.append(self.tr("- حاول استخدام زر 'تعلم المحددات الآن' لتعلم المحددات الجديدة من الذكاء الاصطناعي."))
            suggestions.append(self.tr("- قد يكون العنصر غير مرئي أو غير قابل للتفاعل في الوقت الحالي."))
        if "login failed" in error_message_lower or "credentials" in error_message_lower:
            suggestions.append(self.tr("- تحقق من صحة البريد الإلكتروني وكلمة المرور للشخصية في إعدادات التعديل."))
            suggestions.append(self.tr("- قد يكون هناك كابتشا تتطلب حلاً يدوياً أو مفتاح 2Captcha API غير صحيح."))
            suggestions.append(self.tr("- تأكد من أن الموقع لا يكتشف الأتمتة ويحظر تسجيل الدخول."))
        if "captcha" in error_message_lower:
            suggestions.append(self.tr("- مفتاح 2Captcha API قد يكون غير صحيح أو انتهت صلاحيته."))
            suggestions.append(self.tr("- رصيد حساب 2Captcha قد يكون منخفضاً."))
            suggestions.append(self.tr("- قد تكون الكابتشا من نوع غير مدعوم بواسطة 2Captcha أو تتطلب تدخلاً يدوياً."))
        if "network error" in error_message_lower or "connection" in error_message_lower:
            suggestions.append(self.tr("- تحقق من اتصال جهازك بالإنترنت."))
            suggestions.append(self.tr("- إذا كنت تستخدم بروكسي، تحقق من صحة عنوان البروكسي وعمله."))
            suggestions.append(self.tr("- قد تكون هناك مشكلة مؤقتة في خادم الموقع المستهدف."))
        if "critical error" in error_message_lower or "unhandled" in error_message_lower:
            suggestions.append(self.tr("- هذا خطأ غير متوقع. يرجى مراجعة سجلات التطبيق الرئيسية للحصول على تفاصيل فنية أعمق."))
            suggestions.append(self.tr("- قد تحتاج إلى إعادة تشغيل التطبيق."))
            suggestions.append(self.tr("- إذا تكرر الخطأ، قد يشير ذلك إلى مشكلة في بيئة Python أو المكتبات المثبتة."))

        if not suggestions:
            suggestions.append(self.tr("- هذا خطأ عام. يرجى مراجعة سجل الأحداث (Logs) للحصول على تفاصيل إضافية."))
            suggestions.append(self.tr("- حاول إعادة تشغيل البوت أو التطبيق."))
            suggestions.append(self.tr("- تأكد من أن جميع المكتبات مثبتة ومحدثة."))

        return "\n".join(suggestions)

    # إضافة دالة tr لترجمة النصوص داخل ErrorDetailsDialog
    def tr(self, text):
        return QApplication.instance().translate("ErrorDetailsDialog", text)


class EditPersonaDialog(QDialog):
    """
    نافذة منبثقة لتعديل بيانات الشخصية (الإيميل، كلمة المرور، مفتاح 2Captcha).
    """
    def __init__(self, persona_id, persona_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr(f"تعديل الشخصية #{persona_id}"))
        self.persona_id = persona_id
        self.persona_data = persona_data
        self.setMinimumWidth(450)
        self.setStyleSheet("""
            QDialog {
                background-color: #212121; /* خلفية داكنة */
                border-radius: 10px;
            }
            QLabel {
                color: #CFD8DC;
                font-size: 14px;
            }
            QLineEdit {
                background-color: #303030;
                border: 1px solid #424242;
                border-radius: 5px;
                color: white;
                padding: 8px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #2196F3; /* أزرق عند التركيز */
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 10px 20px;
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5CB85C;
            }
        """)

        layout = QFormLayout(self)
        layout.setContentsMargins(20, 20, 20, 20) # هوامش داخلية
        layout.setVerticalSpacing(15) # مسافة بين الصفوف

        self.email_field = QLineEdit(self.persona_data[0])
        self.email_field.setPlaceholderText(self.tr("أدخل عنوان البريد الإلكتروني"))
        layout.addRow(self.tr("الإيميل:"), self.email_field)

        self.password_field = QLineEdit(self.persona_data[1])
        self.password_field.setEchoMode(QLineEdit.Password)
        self.password_field.setPlaceholderText(self.tr("أدخل كلمة المرور"))
        layout.addRow(self.tr("كلمة المرور:"), self.password_field)

        self.api_key_field = QLineEdit(self.persona_data[4])
        self.api_key_field.setPlaceholderText(self.tr("أدخل مفتاح API لخدمة الكابتشا (اختياري)"))
        layout.addRow(self.tr("مفتاح 2Captcha API:"), self.api_key_field)

        save_button = QPushButton(self.tr("حفظ التغييرات"))
        save_button.clicked.connect(self.save_changes)
        layout.addRow(save_button)

    def save_changes(self):
        save_persona_credentials(self.persona_id, self.email_field.text(), self.password_field.text())
        save_api_key(self.persona_id, self.api_key_field.text())
        self.accept()

    # إضافة دالة tr لترجمة النصوص داخل EditPersonaDialog
    def tr(self, text):
        return QApplication.instance().translate("EditPersonaDialog", text)


class ProxySettingsDialog(QDialog):
    """
    نافذة منبثقة لتعديل إعدادات البروكسي للشخصية، مع خيار اختبار الاتصال.
    """
    def __init__(self, persona_id, persona_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr(f"تعديل بروكسي الشخصية #{persona_id}"))
        self.persona_id = persona_id
        self.persona_data = persona_data
        self.setMinimumWidth(500)
        self.setStyleSheet("""
            QDialog {
                background-color: #212121;
                border-radius: 10px;
            }
            QLabel {
                color: #CFD8DC;
                font-size: 14px;
            }
            QLineEdit {
                background-color: #303030;
                border: 1px solid #424242;
                border-radius: 5px;
                color: white;
                padding: 8px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #2196F3;
            }
            QRadioButton {
                color: #CFD8DC;
                font-size: 14px;
            }
            QPushButton {
                background-color: #2196F3; /* أزرق */
                color: white;
                padding: 10px 20px;
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton#save_button {
                background-color: #4CAF50; /* أخضر للحفظ */
            }
            QPushButton#save_button:hover {
                background-color: #5CB85C;
            }
        """)

        layout = QFormLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setVerticalSpacing(15)

        # Proxy Type Radios
        self.proxy_type_group = QButtonGroup(self)
        proxy_type_layout = QHBoxLayout()

        self.radio_none = QRadioButton(self.tr("لا يوجد بروكسي"))
        self.radio_none.setChecked(self.persona_data[5] == 'none')
        proxy_type_layout.addWidget(self.radio_none)
        self.proxy_type_group.addButton(self.radio_none)

        self.radio_regular = QRadioButton(self.tr("بروكسي عادي"))
        self.radio_regular.setChecked(self.persona_data[5] == 'regular')
        proxy_type_layout.addWidget(self.radio_regular)
        self.proxy_type_group.addButton(self.radio_regular)

        self.radio_home = QRadioButton(self.tr("بروكسي منزلي"))
        self.radio_home.setChecked(self.persona_data[5] == 'home')
        proxy_type_layout.addWidget(self.radio_home)
        self.proxy_type_group.addButton(self.radio_home)

        layout.addRow(self.tr("نوع البروكسي:"), proxy_type_layout)

        self.proxy_field = QLineEdit(self.persona_data[2])
        self.proxy_field.setPlaceholderText(self.tr("مثال: http://user:pass@host:port"))
        self.proxy_field.setToolTip(self.tr("أدخل عنوان البروكسي بالصيغة: http://اسم_المستخدم:كلمة_المرور@المضيف:المنفذ"))
        layout.addRow(self.tr("عنوان البروكسي:"), self.proxy_field)

        self.test_status_label = QLabel(self.tr("جاهز للاختبار."))
        self.test_status_label.setStyleSheet("color: grey; font-style: italic;")

        test_button = QPushButton(self.tr("اختبار الاتصال"))
        test_button.setIcon(QIcon(":/qt-material/wifi_tethering")) # أيقونة اختبار الاتصال
        test_button.clicked.connect(self.test_connection)
        
        test_button_layout = QHBoxLayout()
        test_button_layout.addWidget(test_button)
        test_button_layout.addWidget(self.test_status_label)
        layout.addRow(test_button_layout)

        save_button = QPushButton(self.tr("حفظ"))
        save_button.setObjectName("save_button")
        save_button.clicked.connect(self.save_changes)
        layout.addRow(save_button)

    def test_connection(self):
        proxy_address = self.proxy_field.text()
        proxy_type_selected = self.proxy_type_group.checkedButton().text().split(' - ')[0].lower().replace(' ', '')
        if "لا يوجد" in proxy_type_selected: # معالجة النص العربي
            proxy_type_selected = "noproxy"

        self.test_status_label.setText(self.tr("جاري الاختبار... يرجى الانتظار."))
        self.test_status_label.setStyleSheet("color: orange;")

        def _perform_test_in_thread():
            status_text = ""
            status_color = "red"
            try:
                if proxy_type_selected == 'noproxy' or not proxy_address:
                    status_text = self.tr("لا يوجد بروكسي مكون. الاتصال جيد.")
                    status_color = "green"
                    
                else:
                    # تحقق من تنسيق البروكسي قبل الاختبار
                    if not re.match(r"^(http|https|socks5):\/\/[^\s]+$", proxy_address) and \
                       not re.match(r"^[^\s]+:\d+$", proxy_address) and \
                       not re.match(r"^[^\s]+:[^\s]+@.*$", proxy_address):
                        status_text = self.tr("تنسيق البروكسي غير صالح. يرجى التحقق.")
                        status_color = "red"
                        QTimer.singleShot(0, lambda: self.test_status_label.setText(status_text))
                        QTimer.singleShot(0, lambda: self.test_status_label.setStyleSheet(f"color: {status_color};"))
                        return

                    proxies = {'http://': proxy_address, 'https://': proxy_address}

                    with httpx.Client(timeout=10) as client:
                        response = client.get("http://ip-api.com/json", proxies=proxies)
                        response.raise_for_status()
                        data = response.json()

                        if data.get('status') == 'success':
                            status_text = self.tr(f"نجاح! IP: {data['query']}, البلد: {data['country']}")
                            status_color = "green"
                        else:
                            status_text = self.tr(f"فشل الحصول على IP: {data}")
                            status_color = "red"

            except Exception as ex:
                status_text = self.tr(f"فشل الاتصال: {ex}")
                status_color = "red"
            finally:
                QTimer.singleShot(0, lambda: self.test_status_label.setText(status_text))
                QTimer.singleShot(0, lambda: self.test_status_label.setStyleSheet(f"color: {status_color};"))


        threading.Thread(target=_perform_test_in_thread, daemon=True).start()

    def save_changes(self):
        proxy_address = self.proxy_field.text().strip()
        proxy_type_selected = self.proxy_type_group.checkedButton().text().split(' - ')[0].lower().replace(' ', '')
        if "لا يوجد" in proxy_type_selected: # معالجة النص العربي
            proxy_type_selected = "none"
        
        if proxy_type_selected != "none" and proxy_address:
            # تحقق بسيط من التنسيق قبل الحفظ الفعلي
            if not re.match(r"^(http|https|socks5):\/\/[^\s]+$", proxy_address) and \
               not re.match(r"^[^\s]+:\d+$", proxy_address) and \
               not re.match(r"^[^\s]+:[^\s]+@.*$", proxy_address):
                QMessageBox.warning(self, self.tr("تنسيق بروكسي غير صالح"),
                                    self.tr("تنسيق عنوان البروكسي غير صحيح. يرجى استخدام صيغة مثل:\n"
                                    "http://المستخدم:كلمة_المرور@المضيف:المنفذ\n"
                                    "أو http://المضيف:المنفذ"))
                return # لا تحفظ إذا كان التنسيق خاطئاً

        save_persona_proxy(self.persona_id, proxy_address, proxy_type_selected)
        self.accept()

    # إضافة دالة tr لترجمة النصوص داخل ProxySettingsDialog
    def tr(self, text):
        return QApplication.instance().translate("ProxySettingsDialog", text)


class PasswordDialog(QDialog):
    """
    نافذة منبثقة لطلب كلمة المرور قبل الوصول إلى إعدادات AI.
    """
    def __init__(self, password_to_check: str, parent=None): # **التعديل هنا**: استقبال كلمة السر للتحقق
        super().__init__(parent)
        self.setWindowTitle(self.tr("كلمة السر المطلوبة"))
        self.setModal(True) # جعلها نافذة مشروطة
        self.setFixedSize(350, 180)
        self.password_to_check = password_to_check # **جديد**: حفظ كلمة السر للتحقق
        self.setStyleSheet("""
            QDialog {
                background-color: #212121;
                border-radius: 10px;
            }
            QLabel {
                color: #CFD8DC;
                font-size: 15px;
                margin-bottom: 10px;
            }
            QLineEdit {
                background-color: #303030;
                border: 1px solid #424242;
                border-radius: 5px;
                color: white;
                padding: 8px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #2196F3;
            }
            QPushButton {
                background-color: #2196F3;
                color: white;
                padding: 10px 20px;
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setAlignment(Qt.AlignCenter)

        self.message_label = QLabel(self.tr("الرجاء إدخال كلمة السر للوصول إلى إعدادات AI:"))
        self.message_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.message_label)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText(self.tr("كلمة السر"))
        self.password_input.returnPressed.connect(self.check_password) # تفعيل زر الإدخال عند الضغط على Enter
        layout.addWidget(self.password_input)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: red; font-size: 12px;")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        submit_button = QPushButton(self.tr("تأكيد"))
        submit_button.clicked.connect(self.check_password)
        layout.addWidget(submit_button)

    def check_password(self):
        if self.password_input.text() == self.password_to_check: # **التعديل هنا**: التحقق من كلمة السر الممررة
            self.accept()
        else:
            self.status_label.setText(self.tr("كلمة سر خاطئة!"))
            self.password_input.clear()

    # إضافة دالة tr لترجمة النصوص داخل PasswordDialog
    def tr(self, text):
        return QApplication.instance().translate("PasswordDialog", text)


class AISettingsDialog(QDialog):
    """
    نافذة منبثقة لإعدادات روابط نماذج الذكاء الاصطناعي.
    """
    def __init__(self, current_question_ai_url, current_selector_ai_url, current_gemini_api_key, parent=None): # إضافة current_gemini_api_key
        super().__init__(parent)
        self.setWindowTitle(self.tr("إعدادات الذكاء الاصطناعي (AI)"))
        self.setMinimumWidth(500)
        self.setStyleSheet("""
            QDialog {
                background-color: #212121;
                border-radius: 10px;
            }
            QLabel {
                color: #CFD8DC;
                font-size: 14px;
            }
            QLineEdit {
                background-color: #303030;
                border: 1px solid #424242;
                border-radius: 5px;
                color: white;
                padding: 8px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #2196F3;
            }
            QPushButton {
                background-color: #673AB7; /* Deep Purple */
                color: white;
                padding: 10px 20px;
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #7E57C2;
            }
        """)

        layout = QFormLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setVerticalSpacing(15)

        self.question_ai_url_field = QLineEdit(current_question_ai_url)
        self.question_ai_url_field.setPlaceholderText(self.tr("رابط نموذج الذكاء الاصطناعي للإجابة على الأسئلة (Gradio)"))
        self.question_ai_url_field.setToolTip(self.tr("الرابط لنموذج الذكاء الاصطناعي (Gradio) الذي سيستخدم للإجابة على الأسئلة."))
        layout.addRow(self.tr("رابط AI الأسئلة:"), self.question_ai_url_field)

        self.selector_ai_url_field = QLineEdit(current_selector_ai_url)
        self.selector_ai_url_field.setPlaceholderText(self.tr("رابط نموذج الذكاء الاصطناعي لتعلم المحددات (Hugging Face Gradio)"))
        self.selector_ai_url_field.setToolTip(self.tr("الرابط لخادم Gradio AI على Hugging Face الذي سيستخدم لتعلم محددات عناصر الاستبيان من HTML."))
        layout.addRow(self.tr("رابط AI المحددات:"), self.selector_ai_url_field)

        # حقل مفتاح Gemini API الجديد
        self.gemini_api_key_field = QLineEdit(current_gemini_api_key)
        self.gemini_api_key_field.setEchoMode(QLineEdit.Password) # لإخفاء المفتاح
        self.gemini_api_key_field.setPlaceholderText(self.tr("أدخل مفتاح Gemini API هنا"))
        self.gemini_api_key_field.setToolTip(self.tr("مفتاح API لنموذج Gemini AI المستخدم في محادثة Omran."))
        gemini_api_key_label = QLabel(self.tr("مفتاح Gemini API:"))
        gemini_api_key_label.setObjectName("gemini_api_key_label")
        ai_settings_layout.addRow(gemini_api_key_label, self.gemini_api_key_field)

        save_button = QPushButton(self.tr("حفظ إعدادات AI"))
        save_button.clicked.connect(self.save_changes)
        layout.addRow(save_button)

    def save_changes(self):
        set_app_setting("question_ai_url", self.question_ai_url_field.text())
        set_app_setting("selector_ai_url", self.selector_ai_url_field.text())
        set_app_setting("gemini_api_key", self.gemini_api_key_field.text()) # حفظ مفتاح Gemini API
        self.accept()

    # إضافة دالة tr لترجمة النصوص داخل AISettingsDialog
    def tr(self, text):
        return QApplication.instance().translate("AISettingsDialog", text)


# ==============================================================================
# --- 6. Main Application Class (MainWindow) - فئة التطبيق الرئيسية (PySide6) ---
# ==============================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.tr("OMRAN ASK7"))
        self.setWindowIcon(QIcon(":/qt-material/dashboard"))
        self.setGeometry(100, 100, 1600, 1000)

        self.persona_controls = {}
        self.active_threads = {}
        self.ai_active_persona_id = None
        self.ai_request_queue = deque()
        self.last_error_details = {} # لتخزين تفاصيل آخر خطأ لكل شخصية

        self.setup_database_and_load_data()

        self.worker_signals = WorkerSignals()
        # OmranChatWidget الآن نافذة عائمة، لا تمرر parent
        self.omran_chat_widget = OmranChatWidget(self.worker_signals, self.get_gemini_api_key_from_settings) 
        self.omran_chat_widget.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint) # نافذة عائمة وتظل في الأعلى
        self.omran_chat_widget.hide() # مخفية في البداية

        self.worker_signals.status_updated.connect(self.update_status_ui)
        self.worker_signals.risk_updated.connect(self.update_risk_indicator_ui)
        self.worker_signals.play_sound.connect(self.play_sound_ui)
        self.worker_signals.trigger_ui_answer_now.connect(self._trigger_manual_answer_now_from_thread)
        self.worker_signals.ai_started_processing.connect(self.handle_ai_started_processing)
        self.worker_signals.ai_finished_processing.connect(self.handle_ai_finished_processing)
        self.worker_signals.force_learn_selectors.connect(self.handle_force_learn_selectors)
        self.worker_signals.omran_error_message.connect(self.handle_omran_error_message) # ربط إشارة الخطأ
        self.worker_signals.omran_selector_ai_response.connect(self.omran_chat_widget.handle_selector_ai_response)

        # إعداد نظام الإشعارات (Snackbar)
        self.snackbar = QLabel(self)
        self.snackbar.setAlignment(Qt.AlignCenter)
        self.snackbar.setStyleSheet("""
            QLabel {
                background-color: #333;
                color: white;
                padding: 10px 20px;
                border-radius: 8px;
                font-size: 14px;
                opacity: 0; /* مخفي في البداية */
            }
        """)
        self.snackbar.hide()
        self.snackbar_animation = QPropertyAnimation(self.snackbar, b"geometry")
        self.snackbar_animation.setDuration(300)
        self.snackbar_animation.setEasingCurve(QEasingCurve.OutQuad)
        self.snackbar_timer = QTimer(self)
        self.snackbar_timer.setSingleShot(True)
        self.snackbar_timer.timeout.connect(self.hide_snackbar)

        # إعداد المترجم
        self._translator = None
        self.current_language = get_app_setting("current_language", "ar")
        self.load_language(self.current_language)

        # تطبيق الثيم الافتراضي (الداكن) عند البدء
        self.current_theme_name = get_app_setting("current_theme", "dark")
        self.apply_initial_theme()

        self.setup_ui()

        self.audio_error_dummy = False
        logging.info("Audio system initialized (dummy). Actual audio playback requires QtMultimedia.")

        # إعداد مؤقت نصيحة Omran اليومية
        self.omran_tip_timer = QTimer(self)
        self.omran_tip_timer.timeout.connect(self.send_omran_random_tip)
        self.omran_tip_timer.start(300 * 1000) # كل 5 دقائق (300 ثانية)

        # إعداد مؤقت معلومة اليوم في السجلات
        self.daily_info_timer = QTimer(self)
        self.daily_info_timer.timeout.connect(self.add_daily_info_to_logs)
        self.daily_info_timer.start(3600 * 1000) # كل ساعة (3600 ثانية)


    def setup_database_and_load_data(self):
        """يهيئ قاعدة بيانات SQLite ويحمل بيانات الشخصية الأولية."""
        setup_database()
        self.personas_data = {}
        for i in range(1, NUM_PERSONAS + 1):
            self.personas_data[i] = get_persona_data(i)
        
        self.question_ai_url = get_app_setting("question_ai_url", "https://omran2211-ask.hf.space/")
        self.selector_ai_url = get_app_setting("selector_ai_url", "https://serverboot-yourusernamesurveyselectorai.hf.space/")
        self.gemini_api_key = get_app_setting("gemini_api_key", "") # تحميل مفتاح Gemini API
        # **جديد**: تحميل إعدادات حجم البطاقة
        self.persona_card_width = int(get_app_setting("persona_card_width", "200"))
        self.persona_card_height = int(get_app_setting("persona_card_height", "220"))

    def get_gemini_api_key_from_settings(self):
        """دالة مساعدة لتمرير مفتاح Gemini API إلى OmranChatWidget."""
        return self.gemini_api_key

    def apply_initial_theme(self):
        """تطبيق الثيم الافتراضي عند بدء التشغيل."""
        if self.current_theme_name == "dark":
            apply_stylesheet(self.app, theme='dark_blue.xml', extra={
                'font_family': 'Cairo',
                'danger': '#B71C1C',
                'warning': '#FFB300',
                'success': '#4CAF50',
                'info': '#2196F3',
            })
        elif self.current_theme_name == "light":
            apply_stylesheet(self.app, theme='light_blue.xml', extra={
                'font_family': 'Cairo',
                'danger': '#D32F2F',
                'warning': '#FFA000',
                'success': '#388E3C',
                'info': '#1976D2',
            })
        elif self.current_theme_name == "transparent_dark":
            apply_stylesheet(self.app, theme='dark_amber.xml', extra={ # استخدام ثيم أساسي ثم تعديله بالشفافية
                'font_family': 'Cairo',
                'danger': '#FF5252',
                'warning': '#FFD700',
                'success': '#8BC34A',
                'info': '#4FC3F7',
            })
            # تطبيق الشفافية على النافذة الرئيسية
            # ملاحظة: هذا سيجعل كل شيء في النافذة شفافًا، بما في ذلك النص.
            # للشفافية الخلفية فقط، يتطلب الأمر تعديلات CSS أعمق.
            self.setWindowOpacity(float(get_app_setting("app_transparency", "100")) / 100.0)
        
        # تحديث نص زر تبديل الثيم
        if hasattr(self, 'theme_toggle_button_advanced'): # تأكد من وجود الزر قبل تحديثه
            if self.current_theme_name == "dark":
                self.theme_toggle_button_advanced.setIcon(QIcon(":/qt-material/light_mode"))
                self.theme_toggle_button_advanced.setText(self.tr("تبديل إلى الثيم الفاتح"))
            elif self.current_theme_name == "light":
                self.theme_toggle_button_advanced.setIcon(QIcon(":/qt-material/dark_mode"))
                self.theme_toggle_button_advanced.setText(self.tr("تبديل إلى الثيم الداكن"))
            elif self.current_theme_name == "transparent_dark":
                self.theme_toggle_button_advanced.setIcon(QIcon(":/qt-material/opacity"))
                self.theme_toggle_button_advanced.setText(self.tr("تبديل إلى الثيم النهاري"))

    def setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # لوحة التحكم الرئيسية على اليسار
        left_panel_layout = QVBoxLayout()
        left_panel_layout.setContentsMargins(10, 10, 10, 10)

        # السطر 2360 (تقريباً)
        title_label = QLabel(self.tr("OMRAN ASK7"))
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 38px; font-weight: bold; color: #BBDEFB; padding: 10px;")
        # أضف هذا السطر الجديد:
        title_label.setObjectName("app_title_label")
        left_panel_layout.addWidget(title_label)

        description_label = QLabel(self.tr("أداة أتمتة الاستبيانات الذكية"))
        description_label.setAlignment(Qt.AlignCenter)
        description_label.setStyleSheet("font-size: 18px; color: #B0BEC5; margin-bottom: 20px;")
        # أضف هذا السطر الجديد:
        description_label.setObjectName("app_description_label")
        left_panel_layout.addWidget(description_label)

        self.setup_top_metrics_ui(left_panel_layout)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { /* The tab widget frame */
                border: 1px solid #303030;
                border-radius: 8px;
                background-color: #1A1A1A; /* خلفية التبويبات */
            }
            QTabBar::tab {
                background: #263238; /* خلفية التبويبة غير النشطة */
                color: #CFD8DC;
                border: 1px solid #303030;
                border-bottom-color: #263238; /* Same as pane color */
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                min-width: 100px;
                padding: 8px 15px;
                font-size: 14px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: #1A1A1A; /* خلفية التبويبة النشطة */
                color: #BBDEFB;
                border-bottom-color: #1A1A1A; /* Same as pane color */
            }
            QTabBar::tab:hover {
                background: #37474F; /* Darker blue grey on hover */
            }
        """)
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # تبويب لوحة التحكم (Dashboard) - الشخصيات
        dashboard_tab = QWidget()
        dashboard_tab.setObjectName("dashboard_tab")
        dashboard_layout = QVBoxLayout(dashboard_tab)
        dashboard_layout.addSpacing(10) # مسافة إضافية
        self.headless_switch = QCheckBox(self.tr("وضع التصفح الخفي (بدون واجهة)"))
        self.headless_switch.setChecked(False)
        self.headless_switch.setToolTip(self.tr("تشغيل المتصفح بدون واجهة رسومية مرئية."))
        self.headless_switch.setStyleSheet("font-size: 14px; margin-left: 10px; margin-bottom: 15px;")
        dashboard_layout.addWidget(self.headless_switch)
        
        self.personas_grid_widget = QWidget()
        self.personas_grid_layout = QGridLayout(self.personas_grid_widget)
        self.personas_grid_layout.setSpacing(10) # مسافة بين البطاقات
        self.personas_grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft) # محاذاة للأعلى واليسار

        # لضمان أن الأعمدة تتمدد بالتساوي وتكون البطاقات مربعة قدر الإمكان
        for col in range(7): # 7 أعمدة لكل صف
            self.personas_grid_layout.setColumnStretch(col, 1)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.personas_grid_widget)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: 1px solid #303030;
                border-radius: 8px;
                background-color: #1A1A1A;
            }
            QScrollBar:vertical {
                border: none;
                background: #263238;
                width: 10px;
                margin: 0px 0px 0px 0px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #546E7A;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
        dashboard_layout.addWidget(self.scroll_area)
        dashboard_layout.setStretch(1, 1) # جعل منطقة التمرير تتمدد
        self.tabs.addTab(dashboard_tab, self.tr("الشخصيات"))

        # تبويب سجل الأحداث (Logs)
        logs_tab = QWidget()
        logs_tab.setObjectName("logs_tab")
        logs_layout = QVBoxLayout(logs_tab)
        self.logs_text_browser = QTextBrowser()
        self.logs_text_browser.setReadOnly(True)
        self.logs_text_browser.setStyleSheet("background-color: #1A1A1A; color: #E0E0E0; border-radius: 8px; padding: 10px;")
        logs_layout.addWidget(self.logs_text_browser)
        self.log_handler = QTextEditLogger(self.logs_text_browser, self)
        logging.getLogger().addHandler(self.log_handler)
        self.tabs.addTab(logs_tab, self.tr("سجل الأحداث"))

        # تبويب إعدادات الذكاء الاصطناعي
        ai_settings_tab = QWidget()
        ai_settings_tab.setObjectName("ai_settings_tab")
        ai_settings_layout = QFormLayout(ai_settings_tab)
        ai_settings_tab.setStyleSheet("background-color: #1A1A1A; border-radius: 8px; padding: 20px;")

        self.question_ai_url_field = QLineEdit(get_app_setting("question_ai_url", "https://omran2211-ask.hf.space/"))
        self.question_ai_url_field.setPlaceholderText(self.tr("رابط نموذج الذكاء الاصطناعي للإجابة على الأسئلة (Gradio)"))
        self.question_ai_url_field.setToolTip(self.tr("الرابط لنموذج الذكاء الاصطناعي (Gradio) الذي سيستخدم للإجابة على الأسئلة."))
        question_ai_url_label = QLabel(self.tr("رابط AI الأسئلة:"))
        question_ai_url_label.setObjectName("question_ai_url_label")
        ai_settings_layout.addRow(question_ai_url_label, self.question_ai_url_field)

        self.selector_ai_url_field = QLineEdit(get_app_setting("selector_ai_url", "https://serverboot-yourusernamesurveyselectorai.hf.space/"))
        self.selector_ai_url_field.setPlaceholderText(self.tr("رابط نموذج الذكاء الاصطناعي لتعلم المحددات (Hugging Face Gradio)"))
        self.selector_ai_url_field.setToolTip(self.tr("الرابط لخادم Gradio AI على Hugging Face الذي سيستخدم لتعلم محددات عناصر الاستبيان من HTML."))
        selector_ai_url_label = QLabel(self.tr("رابط AI المحددات:"))
        selector_ai_url_label.setObjectName("selector_ai_url_label")
        ai_settings_layout.addRow(selector_ai_url_label, self.selector_ai_url_field)

        # حقل مفتاح Gemini API في تبويبة الإعدادات
        self.gemini_api_key_field = QLineEdit(get_app_setting("gemini_api_key", ""))
        self.gemini_api_key_field.setEchoMode(QLineEdit.Password)
        self.gemini_api_key_field.setPlaceholderText(self.tr("أدخل مفتاح Gemini API هنا"))
        self.gemini_api_key_field.setToolTip(self.tr("مفتاح API لنموذج Gemini AI المستخدم في محادثة Omran."))
        ai_settings_layout.addRow(self.tr("مفتاح Gemini API:"), self.gemini_api_key_field)

        save_ai_settings_button = QPushButton(self.tr("حفظ إعدادات AI"))
        save_ai_settings_button.setObjectName("save_ai_settings_button")
        save_ai_settings_button.setStyleSheet("""
            QPushButton {
                background-color: #673AB7; /* Deep Purple */
                color: white;
                padding: 10px 20px;
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #7E57C2;
            }
        """)
        save_ai_settings_button.clicked.connect(self.save_ai_settings_from_tab)
        ai_settings_layout.addRow(save_ai_settings_button)
        self.tabs.addTab(ai_settings_tab, self.tr("إعدادات الذكاء الاصطناعي"))

        # تبويب سجل الأسئلة والأجوبة
        qna_history_tab = QWidget()
        qna_history_tab.setObjectName("qna_history_tab")
        qna_history_layout = QVBoxLayout(qna_history_tab)
        self.qna_history_text_browser = QTextBrowser()
        self.qna_history_text_browser.setReadOnly(True)
        self.qna_history_text_browser.setStyleSheet("background-color: #1A1A1A; color: #E0E0E0; border-radius: 8px; padding: 10px;")
        qna_history_layout.addWidget(self.qna_history_text_browser)
        self.load_qna_history()
        self.tabs.addTab(qna_history_tab, self.tr("سجل الأسئلة والأجوبة"))

        # تبويب إعدادات متقدمة
        advanced_settings_tab = QWidget()
        advanced_settings_tab.setObjectName("advanced_settings_tab")
        advanced_settings_layout = QVBoxLayout(advanced_settings_tab)
        advanced_settings_layout.setContentsMargins(20, 20, 20, 20)
        advanced_settings_layout.setAlignment(Qt.AlignTop)
        advanced_settings_tab.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # زر تبديل الثيم في الإعدادات المتقدمة
        self.theme_toggle_button_advanced = QPushButton(self.tr("تبديل الثيم"))
        self.theme_toggle_button_advanced.setIcon(QIcon(":/qt-material/light_mode"))
        self.theme_toggle_button_advanced.setStyleSheet("""
            QPushButton {
                background-color: #455A64;
                color: white;
                font-size: 14px;
                padding: 8px 15px;
                border-radius: 8px;
                border: none;
                margin-bottom: 10px;
            }
            QPushButton:hover {
                background-color: #607D8B;
            }
        """)
        self.theme_toggle_button_advanced.clicked.connect(self.toggle_theme)
        advanced_settings_layout.addWidget(self.theme_toggle_button_advanced, alignment=Qt.AlignLeft)
        
        # إعدادات حجم البطاقة في الإعدادات المتقدمة
        card_size_group = QFormLayout()
        card_size_group_widget = QWidget()
        card_size_group_widget.setLayout(card_size_group)
        card_size_group_widget.setStyleSheet("border: 1px solid #424242; border-radius: 8px; padding: 10px; margin-top: 10px;")
        
        self.persona_card_width_spinbox = QSpinBox()
        self.persona_card_width_spinbox.setRange(100, 300) # نطاق معقول للعرض
        self.persona_card_width_spinbox.setValue(self.persona_card_width)
        self.persona_card_width_spinbox.setStyleSheet("background-color: #303030; color: white; border: 1px solid #555; border-radius: 5px; padding: 5px;")
        card_width_label = QLabel(self.tr("عرض البطاقة (بكسل):"))
        card_width_label.setObjectName("persona_card_width_label")
        card_size_group.addRow(card_width_label, self.persona_card_width_spinbox)

        self.persona_card_height_spinbox = QSpinBox()
        self.persona_card_height_spinbox.setRange(100, 300) # نطاق معقول للارتفاع
        self.persona_card_height_spinbox.setValue(self.persona_card_height)
        self.persona_card_height_spinbox.setStyleSheet("background-color: #303030; color: white; border: 1px solid #555; border-radius: 5px; padding: 5px;")
        card_height_label = QLabel(self.tr("ارتفاع البطاقة (بكسل):"))
        card_height_label.setObjectName("persona_card_height_label")
        card_size_group.addRow(card_height_label, self.persona_card_height_spinbox)

        save_card_size_button = QPushButton(self.tr("حفظ حجم البطاقة"))
        save_card_size_button.setObjectName("save_card_size_button")
        save_card_size_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 8px 15px;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background-color: #5CB85C;
            }
        """)
        save_card_size_button.clicked.connect(self.save_persona_card_settings)
        card_size_group.addRow(save_card_size_button)

        advanced_settings_layout.addWidget(card_size_group_widget)
        
        # إعدادات التأخير العشوائي
        delay_settings_group = QFormLayout()
        delay_settings_group_widget = QWidget()
        delay_settings_group_widget.setLayout(delay_settings_group)
        delay_settings_group_widget.setStyleSheet("border: 1px solid #424242; border-radius: 8px; padding: 10px; margin-top: 10px;")

        self.min_delay_spinbox = QSpinBox()
        self.min_delay_spinbox.setRange(0, 30)
        self.min_delay_spinbox.setValue(int(get_app_setting("min_delay_seconds", "2")))
        self.min_delay_spinbox.setStyleSheet("background-color: #303030; color: white; border: 1px solid #555; border-radius: 5px; padding: 5px;")
        min_delay_label = QLabel(self.tr("الحد الأدنى للتأخير (ثواني):"))
        min_delay_label.setObjectName("min_delay_seconds_label")
        delay_settings_group.addRow(min_delay_label, self.min_delay_spinbox)

        self.max_delay_spinbox = QSpinBox()
        self.max_delay_spinbox.setRange(1, 60)
        self.max_delay_spinbox.setValue(int(get_app_setting("max_delay_seconds", "5")))
        self.max_delay_spinbox.setStyleSheet("background-color: #303030; color: white; border: 1px solid #555; border-radius: 5px; padding: 5px;")
        max_delay_label = QLabel(self.tr("الحد الأقصى للتأخير (ثواني):"))
        max_delay_label.setObjectName("max_delay_seconds_label")
        delay_settings_group.addRow(max_delay_label, self.max_delay_spinbox)

        save_delay_button = QPushButton(self.tr("حفظ إعدادات التأخير"))
        save_delay_button.setObjectName("save_delay_button")
        save_delay_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 8px 15px;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background-color: #5CB85C;
            }
        """)
        save_delay_button.clicked.connect(self.save_delay_settings)
        delay_settings_group.addRow(save_delay_button)

        advanced_settings_layout.addWidget(delay_settings_group_widget)

        # إعدادات الشفافية
        transparency_group = QFormLayout()
        transparency_group_widget = QWidget()
        transparency_group_widget.setLayout(transparency_group)
        transparency_group_widget.setStyleSheet("border: 1px solid #424242; border-radius: 8px; padding: 10px; margin-top: 10px;")

        self.transparency_slider = QSlider(Qt.Horizontal)
        self.transparency_slider.setRange(0, 100) # 0% شفافية (معتم) إلى 100% شفافية (غير مرئي)
        self.transparency_slider.setValue(int(float(get_app_setting("app_transparency", "100")))) # تحميل القيمة المحفوظة
        self.transparency_slider.setToolTip(self.tr("تحكم في شفافية الخلفية للثيم الشفاف. 0% = معتم, 100% = شفاف تماماً."))
        self.transparency_slider.valueChanged.connect(self.update_app_transparency)

        self.transparency_value_label = QLabel(self.tr(f"{self.transparency_slider.value()}%"))
        self.transparency_value_label.setStyleSheet("color: #CFD8DC; font-size: 14px;")

        transparency_label = QLabel(self.tr("مستوى الشفافية:"))
        transparency_label.setObjectName("transparency_label")
        transparency_group.addRow(transparency_label, self.transparency_slider)
        transparency_group.addRow("", self.transparency_value_label)

        advanced_settings_layout.addWidget(transparency_group_widget)

        # إعدادات اللغة
        language_group = QFormLayout()
        language_group_widget = QWidget()
        language_group_widget.setLayout(language_group)
        language_group_widget.setStyleSheet("border: 1px solid #424242; border-radius: 8px; padding: 10px; margin-top: 10px;")

        self.language_combo = QComboBox()
        self.language_combo.addItem(self.tr("العربية"), "ar")
        self.language_combo.addItem(self.tr("English"), "en")
        self.language_combo.setCurrentText(self.tr("العربية") if self.current_language == "ar" else self.tr("English")) # تعيين اللغة الحالية
        self.language_combo.currentIndexChanged.connect(self.change_language)
        language_label = QLabel(self.tr("اللغة:"))
        language_label.setObjectName("language_label")
        language_group.addRow(language_label, self.language_combo)

        advanced_settings_layout.addWidget(language_group_widget)

        other_settings_label = QLabel(self.tr("إعدادات متقدمة أخرى ستأتي هنا."))
        other_settings_label.setObjectName("other_advanced_settings_label")
        ### نهاية الاستبدال ###
        advanced_settings_layout.addWidget(other_settings_label)
        advanced_settings_layout.addStretch(1)
        self.tabs.addTab(advanced_settings_tab, self.tr("إعدادات متقدمة"))


        left_panel_layout.addWidget(self.tabs)
        self.main_layout.addLayout(left_panel_layout, 2) # لوحة التحكم تأخذ 2/3 من العرض

        self.load_personas_to_ui()
        self.apply_custom_styles() # تطبيق الأنماط المخصصة بعد تهيئة الواجهة


    def setup_top_metrics_ui(self, parent_layout):
        metrics_container = QWidget()
        metrics_layout = QVBoxLayout(metrics_container)
        metrics_container.setStyleSheet("""
            QWidget {
                background-color: #263238;
                border: 1px solid #303030;
                border-radius: 10px;
                padding: 15px;
                margin-bottom: 20px;
            }
        """)

        # السطر 2740 (تقريباً) - داخل دالة setup_top_metrics_ui
        ai_activity_layout = QHBoxLayout()
        ai_activity_label_title = QLabel(self.tr("حالة الذكاء الاصطناعي:"))
        ai_activity_label_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #CFD8DC;")
        ai_activity_label_title.setObjectName("ai_activity_label_title")
        ai_activity_layout.addWidget(ai_activity_label_title)

        self.ai_active_persona_label = QLabel(self.tr("لا يوجد نشاط"))
        self.ai_active_persona_label.setStyleSheet("font-size: 14px; color: #9E9E9E; font-weight: bold;")
        self.ai_active_persona_label.setObjectName("ai_active_persona_label")
        ai_activity_layout.addWidget(self.ai_active_persona_label)
        ai_activity_layout.addStretch(1)
        metrics_layout.addLayout(ai_activity_layout)

        ### أضف هذا السطر ###
        ai_queue_layout = QHBoxLayout()
        ### نهاية الإضافة ###

        ai_queue_label_title = QLabel(self.tr("قائمة انتظار الذكاء الاصطناعي:"))
        ai_queue_label_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #CFD8DC;")
        ai_queue_label_title.setObjectName("ai_queue_label_title")
        ai_queue_layout.addWidget(ai_queue_label_title)

        self.ai_queue_count_label = QLabel("0")
        self.ai_queue_count_label.setStyleSheet("font-size: 14px; color: #9E9E9E; font-weight: bold;")
        self.ai_queue_count_label.setObjectName("ai_queue_count_label")
        ai_queue_layout.addWidget(self.ai_queue_count_label)
        ai_queue_layout.addStretch(1)
        metrics_layout.addLayout(ai_queue_layout)

        parent_layout.addWidget(metrics_container)

        # هذا العنصر (self.ai_queue_count_label) هو خاصية بالفعل، لا تحتاج لـ objectName هنا
        # self.ai_queue_count_label = QLabel("0")
        # ...

        self.ai_queue_count_label = QLabel("0")
        self.ai_queue_count_label.setStyleSheet("font-size: 14px; color: #9E9E9E; font-weight: bold;")
        ai_queue_layout.addWidget(self.ai_queue_count_label)
        ai_queue_layout.addStretch(1)
        metrics_layout.addLayout(ai_queue_layout)

        parent_layout.addWidget(metrics_container)

    def setup_ai_settings_button(self, parent_layout):
        ai_settings_btn = QPushButton(self.tr("إعدادات الذكاء الاصطناعي (AI)"))
        ai_settings_btn.setIcon(QIcon(":/qt-material/settings"))
        ai_settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #673AB7;
                color: white;
                font-size: 16px;
                font-weight: bold;
                padding: 12px 25px;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background-color: #7E57C2;
            }
            QPushButton:pressed {
                background-color: #5E35B1;
            }
        """)
        ai_settings_btn.clicked.connect(self.open_ai_settings_with_password)
        parent_layout.addWidget(ai_settings_btn, alignment=Qt.AlignCenter)

    def load_personas_to_ui(self):
        # مسح الشبكة الحالية
        for i in reversed(range(self.personas_grid_layout.count())):
            widget = self.personas_grid_layout.itemAt(i).widget()
            if widget is not None:
                widget.deleteLater()

        col_count = 7 # 7 أعمدة لكل صف
        row_index = 0
        col_index = 0

        for i in range(1, NUM_PERSONAS + 1):
            persona_data = get_persona_data(i)
            email = persona_data[0] or self.tr(f"الشخصية {i}") # ترجمة اسم الشخصية الافتراضي
            kick_count = persona_data[3]

            persona_card = self.create_persona_card(i, email, kick_count)
            self.personas_grid_layout.addWidget(persona_card, row_index, col_index)
            
            col_index += 1
            if col_index >= col_count:
                col_index = 0
                row_index += 1
            
            self.update_buttons_enabled_state(i, self.tr("Idle - خامل"))

    def create_persona_card(self, persona_id, email, kick_count):
        card_widget = QWidget()
        card_layout = QVBoxLayout(card_widget)
        card_layout.setContentsMargins(10, 10, 10, 10) # تقليل الهوامش الداخلية للبطاقة
        
        # **التعديل هنا**: استخدام العرض والارتفاع من الإعدادات
        card_widget.setFixedSize(self.persona_card_width, self.persona_card_height) 
        
        card_widget.setStyleSheet("""
            QWidget {
                border: 1px solid #424242;
                border-radius: 12px;
                background-color: #263238;
            }
            QLabel {
                color: #CFD8DC;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 5px 8px; /* **التعديل هنا**: تصغير حجم البادينج للأزرار */
                border-radius: 5px; /* **التعديل هنا**: تصغير زوايا الأزرار */
                border: none;
                font-weight: bold;
                font-size: 11px; /* **التعديل هنا**: تصغير حجم الخط للأزرار */
            }
            QPushButton:hover {
                background-color: #689F38; /* **التعديل هنا**: لون أفتح عند التحويم */
                opacity: 1; /* التأكد من الشفافية الكاملة */
            }
            QPushButton:pressed {
                background-color: #388E3C; /* لون أغمق عند الضغط */
            }
            QPushButton#start_btn { background-color: #4CAF50; }
            QPushButton#start_btn:hover { background-color: #689F38; }
            QPushButton#stop_btn { background-color: #F44336; }
            QPushButton#stop_btn:hover { background-color: #E53935; }
            QPushButton#answer_now_btn { background-color: #2196F3; }
            QPushButton#answer_now_btn:hover { background-color: #1976D2; }
            QPushButton#edit_btn, QPushButton#proxy_btn { background-color: #546E7A; }
            QPushButton#edit_btn:hover, QPushButton#proxy_btn:hover { background-color: #78909C; }
            QPushButton#learn_selectors_btn { background-color: #FFC107; }
            QPushButton#learn_selectors_btn:hover { background-color: #FFD54F; }
            QPushButton#error_icon_btn {
                background-color: transparent;
                border: none;
                padding: 0px;
            }
            QPushButton#error_icon_btn:hover {
                background-color: rgba(255, 0, 0, 0.2);
            }
        """)

        # Title and Persona ID and Error Icon
        top_row = QHBoxLayout()
        persona_id_label = QLabel(f"#{persona_id}")
        persona_id_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #BBDEFB;")
        top_row.addWidget(persona_id_label)

        title_label = QLabel(email)
        title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #E0E0E0;") # خط أصغر قليلاً
        title_label.setCursor(Qt.PointingHandCursor) # لجعلها قابلة للنقر
        # ربط النقر على عنوان الشخصية
        title_label.mousePressEvent = lambda event: self.open_omran_chat_with_context(persona_id) 
        top_row.addWidget(title_label)
        top_row.addStretch(1)

        error_icon_btn = QPushButton()
        error_icon_btn.setObjectName("error_icon_btn")
        error_icon_btn.setIcon(QIcon(":/qt-material/error"))
        error_icon_btn.setIconSize(QSize(20, 20)) # أيقونة أصغر
        error_icon_btn.setFixedSize(20, 20) # حجم ثابت للأيقونة
        error_icon_btn.setToolTip(self.tr("انقر لعرض تفاصيل آخر خطأ."))
        error_icon_btn.hide()
        error_icon_btn.clicked.connect(lambda: self.show_persona_error_details(persona_id))
        top_row.addWidget(error_icon_btn)
        self.persona_controls[persona_id] = self.persona_controls.get(persona_id, {})
        self.persona_controls[persona_id]['error_icon_btn'] = error_icon_btn

        card_layout.addLayout(top_row)

        # Status
        status_row = QHBoxLayout()
        status_icon = QLabel()
        status_icon.setFixedSize(12, 12) # أيقونة حالة أصغر
        status_icon.setStyleSheet("background-color: #9E9E9E; border-radius: 6px;")
        self.persona_controls[persona_id]['status_icon'] = status_icon

        status_text = QLabel(self.tr("خامل - Idle"))
        status_text.setStyleSheet("font-size: 11px; color: #9E9E9E;") # خط أصغر
        self.persona_controls[persona_id]['status_text'] = status_text
        status_row.addWidget(status_icon)
        status_row.addWidget(status_text)
        status_row.addStretch(1)
        card_layout.addLayout(status_row)

        # Risk Indicator
        risk_row = QHBoxLayout()
        risk_label = QLabel(self.tr("المخاطرة:"))
        risk_label.setStyleSheet("font-size: 10px; color: #B0BEC5;") # خط أصغر
        risk_row.addWidget(risk_label)

        risk_bar = QProgressBar()
        risk_bar.setRange(0, 10)
        risk_bar.setValue(min(kick_count, 10))
        risk_bar.setTextVisible(False)
        risk_bar.setFixedSize(80, 8) # شريط تقدم أصغر
        self.update_progress_bar_color(risk_bar, min(kick_count, 10))
        self.persona_controls[persona_id]['risk_bar'] = risk_bar

        kick_count_label = QLabel(f"{kick_count}/10")
        kick_count_label.setStyleSheet("font-size: 10px; color: #B0BEC5;") # خط أصغر
        self.persona_controls[persona_id]['kick_count_label'] = kick_count_label

        risk_row.addWidget(risk_bar)
        risk_row.addWidget(kick_count_label)
        risk_row.addStretch(1)
        card_layout.addLayout(risk_row)

        # Buttons
        buttons_layout = QGridLayout() # استخدام شبكة للأزرار داخل البطاقة
        buttons_layout.setSpacing(5) # مسافة أقل بين الأزرار

        start_btn = QPushButton(self.tr("تشغيل"))
        start_btn.setObjectName("start_btn")
        start_btn.setProperty("persona_id", persona_id)
        start_btn.clicked.connect(self.start_click)
        start_btn.installEventFilter(self) # لتأثير التحويم
        buttons_layout.addWidget(start_btn, 0, 0) # الصف 0، العمود 0

        stop_btn = QPushButton(self.tr("إيقاف"))
        stop_btn.setObjectName("stop_btn")
        stop_btn.setProperty("persona_id", persona_id)
        stop_btn.clicked.connect(self.stop_click)
        stop_btn.setEnabled(False)
        stop_btn.installEventFilter(self) # لتأثير التحويم
        buttons_layout.addWidget(stop_btn, 0, 1) # الصف 0، العمود 1

        answer_now_btn = QPushButton(self.tr("أجب الآن"))
        answer_now_btn.setObjectName("answer_now_btn")
        answer_now_btn.setProperty("persona_id", persona_id)
        answer_now_btn.clicked.connect(self.manual_start_click)
        answer_now_btn.setEnabled(False)
        answer_now_btn.installEventFilter(self) # لتأثير التحويم
        buttons_layout.addWidget(answer_now_btn, 1, 0) # الصف 1، العمود 0

        learn_selectors_btn = QPushButton(self.tr("تعلم المحددات")) # نص أقصر
        learn_selectors_btn.setObjectName("learn_selectors_btn")
        learn_selectors_btn.setProperty("persona_id", persona_id)
        learn_selectors_btn.clicked.connect(self.manual_learn_selectors_click)
        learn_selectors_btn.setEnabled(False)
        learn_selectors_btn.installEventFilter(self) # لتأثير التحويم
        buttons_layout.addWidget(learn_selectors_btn, 1, 1) # الصف 1، العمود 1
        
        # أزرار التعديل والبروكسي في صف منفصل أو دمجها
        edit_proxy_layout = QHBoxLayout()
        edit_proxy_layout.setSpacing(5)

        edit_btn = QPushButton(self.tr("تعديل"))
        edit_btn.setObjectName("edit_btn")
        edit_btn.setProperty("persona_id", persona_id)
        edit_btn.clicked.connect(self.edit_click)
        edit_btn.installEventFilter(self) # لتأثير التحويم
        edit_proxy_layout.addWidget(edit_btn)

        proxy_btn = QPushButton(self.tr("بروكسي"))
        proxy_btn.setObjectName("proxy_btn")
        proxy_btn.setProperty("persona_id", persona_id)
        proxy_btn.clicked.connect(self.proxy_click)
        proxy_btn.installEventFilter(self) # لتأثير التحويم
        edit_proxy_layout.addWidget(proxy_btn)
        
        card_layout.addLayout(buttons_layout)
        card_layout.addLayout(edit_proxy_layout)


        self.persona_controls[persona_id]['card_widget'] = card_widget
        self.persona_controls[persona_id]['title_label'] = title_label
        self.persona_controls[persona_id]['start_btn'] = start_btn
        self.persona_controls[persona_id]['stop_btn'] = stop_btn
        self.persona_controls[persona_id]['edit_btn'] = edit_btn
        self.persona_controls[persona_id]['proxy_btn'] = proxy_btn
        self.persona_controls[persona_id]['answer_now_btn'] = answer_now_btn
        self.persona_controls[persona_id]['learn_selectors_btn'] = learn_selectors_btn

        return card_widget

    def update_progress_bar_color(self, progress_bar, value):
        if value > 7:
            progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #F44336; border-radius: 4px; }")
        elif value > 4:
            progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #FF9800; border-radius: 4px; }")
        else:
            progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #4CAF50; border-radius: 4px; }")

    def update_status_ui(self, persona_id: int, text: str, color_name: str):
        if persona_id in self.persona_controls:
            controls = self.persona_controls[persona_id]
            controls['status_text'].setText(text)
            
            qcolor_map = {
                "grey": "#9E9E9E",
                "deep_orange_accent": "#FF6E40",
                "orange": "#FF9800",
                "red": "#F44336",
                "light_green_700": "#689F38",
                "cyan": "#00BCD4",
                "amber": "#FFC107",
                "light_blue_accent": "#40C4FF",
                "blue": "#2196F3",
                "deep_purple": "#673AB7",
                "green": "#4CAF50",
                "orange_300": "#FFB74D",
                "cyan_700": "#0097A7",
                "purple_200": "#CE93D8",
                "blue_accent_200": "#448AFF",
                "red_500": "#F44336",
                "red_900": "#B71C1C",
                "amber_700": "#FFB300",
                "grey_700": "#616161",
                "blue_grey_700": "#455A64",
                "blue_grey_800": "#37474F",
                "blue_accent_700": "#2962FF",
                "white": "#FFFFFF",
                "black": "#000000",
                "indigo": "#3F51B5"
            }
            
            color_hex = qcolor_map.get(color_name.lower(), "#FFFFFF")

            controls['status_icon'].setStyleSheet(f"background-color: {color_hex}; border-radius: 7px;")
            controls['status_text'].setStyleSheet(f"color: {color_hex}; font-size: 13px;")

            self.update_buttons_enabled_state(persona_id, text)

            # إظهار/إخفاء أيقونة الخطأ
            if "error" in text.lower() or "failed" in text.lower() or "timeout" in text.lower() or "critical" in text.lower():
                controls['error_icon_btn'].show()
            else:
                # أخفي الأيقونة فقط إذا لم يكن هناك خطأ محفوظ لهذه الشخصية
                if persona_id not in self.last_error_details or not self.last_error_details[persona_id]:
                    controls['error_icon_btn'].hide()


    def update_buttons_enabled_state(self, persona_id, status_text):
        if persona_id in self.persona_controls:
            controls = self.persona_controls[persona_id]
            
            is_running_state = not (status_text.startswith(self.tr("Stopped")) or status_text.startswith(self.tr("Login Failed")) or status_text.startswith(self.tr("CRITICAL INIT ERROR")) or self.tr("stopped") in status_text.lower())
            
            controls['start_btn'].setEnabled(not is_running_state)
            controls['edit_btn'].setEnabled(not is_running_state)
            controls['proxy_btn'].setEnabled(not is_running_state)
            controls['stop_btn'].setEnabled(is_running_state)
            
            controls['answer_now_btn'].setEnabled(is_running_state and (self.ai_active_persona_id is None or self.ai_active_persona_id == persona_id))
            
            controls['learn_selectors_btn'].setEnabled(is_running_state and (self.ai_active_persona_id is None or self.ai_active_persona_id == persona_id))


    def update_risk_indicator_ui(self, persona_id: int):
        if persona_id in self.persona_controls:
            _, _, _, kick_count, _, _ = get_persona_data(persona_id)
            controls = self.persona_controls[persona_id]
            controls['risk_bar'].setValue(min(kick_count, 10))
            self.update_progress_bar_color(controls['risk_bar'], min(kick_count, 10))
            controls['kick_count_label'].setText(f"{kick_count}/10")

    def play_sound_ui(self):
        logging.info("Playing error sound (dummy playback).")
        self.show_snackbar(self.tr("حدث خطأ! يرجى التحقق من السجلات."), "error")


    def start_click(self, event): # إضافة event لاستخدام installEventFilter
        sender_button = self.sender()
        persona_id = sender_button.property("persona_id")

        if persona_id in self.active_threads and self.active_threads[persona_id].is_alive():
            self.show_snackbar(self.tr(f"بوت الشخصية {persona_id} قيد التشغيل بالفعل."), "warning")
            return

        self.update_buttons_enabled_state(persona_id, self.tr("Starting..."))

        email, password, saved_proxy, kick_count, api_key, proxy_type = get_persona_data(persona_id)
        proxy_to_use = {'server': saved_proxy} if proxy_type in ['regular', 'home'] and saved_proxy else None

        question_ai_url = get_app_setting("question_ai_url")
        selector_ai_url = get_app_setting("selector_ai_url")

        if not question_ai_url or not selector_ai_url:
            self.show_snackbar(self.tr("روابط نماذج الذكاء الاصطناعي غير مضبوطة. يرجى ضبطها في إعدادات AI أولاً."), "error")
            self.update_buttons_enabled_state(persona_id, self.tr("Stopped - توقف"))
            return

        thread = AutomationThread(
            persona_id,
            self.headless_switch.isChecked(),
            proxy_to_use,
            question_ai_url,
            selector_ai_url,
            save_to_persona_history_global,
            self.worker_signals
        )
        self.active_threads[persona_id] = thread
        thread.start()
        self.show_snackbar(self.tr(f"تم تشغيل الشخصية {persona_id}!"), "success")

    def stop_click(self, event): # إضافة event لاستخدام installEventFilter
        sender_button = self.sender()
        persona_id = sender_button.property("persona_id")
        if persona_id in self.active_threads:
            self.update_status_ui(persona_id, self.tr("Stopping... - جاري الإيقاف..."), "amber")
            self.active_threads[persona_id].stop()
            if persona_id in self.ai_request_queue:
                self.ai_request_queue.remove(persona_id)
                self.update_global_ai_status_ui()
            if self.ai_active_persona_id == persona_id:
                self.ai_active_persona_id = None
                self.process_next_ai_request()
            self.update_buttons_enabled_state(persona_id, self.tr("Stopping..."))

        else:
            self.show_snackbar(self.tr(f"بوت الشخصية {persona_id} لا يعمل."), "warning")
            self.update_buttons_enabled_state(persona_id, self.tr("Stopped - توقف"))
            
    def edit_click(self, event): # إضافة event لاستخدام installEventFilter
        sender_button = self.sender()
        persona_id = sender_button.property("persona_id")
        edit_dialog = EditPersonaDialog(persona_id, self.personas_data[persona_id], self)
        if edit_dialog.exec() == QDialog.Accepted:
            self.personas_data[persona_id] = get_persona_data(persona_id)
            self.load_personas_to_ui()
            self.show_snackbar(self.tr(f"تم تحديث بيانات الشخصية {persona_id} بنجاح!"), "info")


    def proxy_click(self, event): # إضافة event لاستخدام installEventFilter
        sender_button = self.sender()
        persona_id = sender_button.property("persona_id")
        proxy_dialog = ProxySettingsDialog(persona_id, self.personas_data[persona_id], self)
        if proxy_dialog.exec() == QDialog.Accepted:
            self.personas_data[persona_id] = get_persona_data(persona_id)
            self.load_personas_to_ui()
            self.show_snackbar(self.tr(f"تم تحديث بروكسي الشخصية {persona_id} بنجاح!"), "info")


    def manual_start_click(self, event): # إضافة event لاستخدام installEventFilter
        sender_button = self.sender()
        persona_id = sender_button.property("persona_id")
        self._add_to_ai_request_queue(persona_id, "answer")

    def manual_learn_selectors_click(self, event): # إضافة event لاستخدام installEventFilter
        sender_button = self.sender()
        persona_id = sender_button.property("persona_id")
        self._add_to_ai_request_queue(persona_id, "learn_selectors")

    # ==============================================================================
    # --- 7. AI Queue and Status Management ---
    # ==============================================================================
       # هذا الجزء هو تكملة للكود السابق. يرجى التأكد من دمج الجزأين معًا.

# ==============================================================================
# --- 7. AI Queue and Status Management (Continuation) ---
# ==============================================================================
    def _add_to_ai_request_queue(self, persona_id, request_type):
        """
        يضيف طلب معالجة AI إلى قائمة الانتظار.
        يتم معالجة طلب واحد فقط في كل مرة.
        """
        request_tuple = (persona_id, request_type)
        # لا نضيف الطلب إذا كان البوت غير نشط أو إذا كان هناك طلب لنفس البوت قيد المعالجة بالفعل
        if persona_id not in self.active_threads or not self.active_threads[persona_id].is_alive():
            self.show_snackbar(self.tr(f"بوت الشخصية {persona_id} غير نشط. يرجى تشغيله أولاً."), "error")
            self.update_buttons_enabled_state(persona_id, self.tr("Bot not running."))
            return

        # إذا كان هناك AI نشط بالفعل لشخصية أخرى، أضف إلى قائمة الانتظار
        if self.ai_active_persona_id is not None and self.ai_active_persona_id != persona_id:
            if request_tuple not in self.ai_request_queue:
                self.ai_request_queue.append(request_tuple)
                self.update_global_ai_status_ui()
                self.update_status_ui(persona_id, self.tr("Waiting for AI slot... - في انتظار دور الذكاء الاصطناعي..."), "orange_300")
            else:
                self.show_snackbar(self.tr(f"الشخصية {persona_id} موجودة بالفعل في قائمة انتظار الذكاء الاصطناعي."), "info")
        # إذا لم يكن هناك AI نشط، أو كان AI نشطًا لنفس الشخصية، قم بالتشغيل فورًا
        else:
            self.ai_request_queue.append(request_tuple) # أضف إلى القائمة ثم قم بالمعالجة
            self.process_next_ai_request()

    def _trigger_ai_action(self, persona_id, request_type):
        """
        يطلق إجراء AI محدد (إجابة أو تعلم المحددات) في خيط البوت.
        """
        thread = self.active_threads.get(persona_id)
        if thread and thread.is_alive():
            if request_type == "answer":
                thread.force_answer_now = True
                self.show_snackbar(self.tr(f"تم إرسال أمر 'أجب الآن' يدوياً للشخصية {persona_id}!"), "info")
                self.update_status_ui(persona_id, self.tr("تم إرسال أمر يدوي! - Manual trigger sent!"), "teal")
            elif request_type == "learn_selectors":
                thread.force_selector_learning = True
                self.show_snackbar(self.tr(f"تم إرسال أمر 'تعلم المحددات' يدوياً للشخصية {persona_id}!"), "info")
                self.update_status_ui(persona_id, self.tr("تم إرسال أمر تعلم المحددات يدوياً! - Manual learn selectors sent!"), "amber_700")
        else:
            self.show_snackbar(self.tr(f"بوت الشخصية {persona_id} لا يعمل. يرجى تشغيله أولاً."), "error")
            self.update_status_ui(persona_id, self.tr("البوت لا يعمل! - Bot not running!"), "red")
            # إزالة الطلب من قائمة الانتظار إذا كان البوت غير نشط
            request_tuple = (persona_id, request_type)
            if request_tuple in self.ai_request_queue:
                self.ai_request_queue.remove(request_tuple)
                self.update_global_ai_status_ui()
            if self.ai_active_persona_id == persona_id:
                self.ai_active_persona_id = None
                self.process_next_ai_request()


    def _trigger_manual_answer_now_from_thread(self, persona_id: int, delay: int):
        """
        تُستدعى هذه الدالة بواسطة خيط البوت لجدولة طلب "أجب الآن" تلقائياً بعد الانتهاء من المعالجة الحالية.
        """
        if self.ai_active_persona_id == persona_id:
            self.ai_active_persona_id = None
            self.update_global_ai_status_ui()
            self.process_next_ai_request() # معالجة الطلب التالي في قائمة الانتظار فوراً

        self.show_snackbar(self.tr(f"الشخصية {persona_id}: جدولة 'أجب الآن' تلقائياً بعد {delay} ثوانٍ..."), "info")
        self.update_status_ui(persona_id, self.tr(f"جدولة 'أجب الآن' تلقائياً بعد {delay} ثوانٍ... - Scheduling auto 'Answer Now' in {delay}s..."), "purple_200")
        QTimer.singleShot(delay * 1000, lambda: self._add_to_ai_request_queue(persona_id, "answer"))

    def handle_ai_started_processing(self, persona_id: int):
        """
        تُستدعى عندما يبدأ AI بمعالجة طلب لشخصية معينة.
        """
        self.ai_active_persona_id = persona_id
        self.update_global_ai_status_ui()
        self.show_snackbar(self.tr(f"الذكاء الاصطناعي بدأ المعالجة للشخصية #{persona_id}."), "info")
        # تعطيل أزرار "أجب الآن" و "تعلم المحددات" للشخصيات الأخرى
        for pid, controls in self.persona_controls.items():
            if pid != persona_id and pid in self.active_threads and self.active_threads[pid].is_alive():
                controls['answer_now_btn'].setEnabled(False)
                controls['learn_selectors_btn'].setEnabled(False)

    def handle_ai_finished_processing(self, persona_id: int):
        """
        تُستدعى عندما ينتهي AI من معالجة طلب لشخصية معينة.
        """
        self.ai_active_persona_id = None # تحرير قفل AI
        self.update_global_ai_status_ui()
        self.show_snackbar(self.tr(f"الذكاء الاصطناعي انتهى من المعالجة للشخصية #{persona_id}."), "info")
        # إعادة تمكين أزرار "أجب الآن" و "تعلم المحددات" لجميع الشخصيات النشطة
        for pid, controls in self.persona_controls.items():
            if pid in self.active_threads and self.active_threads[pid].is_alive():
                self.update_buttons_enabled_state(pid, controls['status_text'].text())
        self.process_next_ai_request() # معالجة الطلب التالي في قائمة الانتظار

    def handle_force_learn_selectors(self, persona_id: int):
        """
        تُستدعى عندما يطلب البوت تعلم المحددات.
        """
        self.update_status_ui(persona_id, self.tr("البوت يطلب تعلم المحددات... - Bot requesting selector learning..."), "amber")

    def process_next_ai_request(self):
        """
        يعالج الطلب التالي في قائمة انتظار AI إذا لم يكن هناك AI نشط حالياً.
        """
        if self.ai_active_persona_id is None and self.ai_request_queue:
            next_persona_id, request_type = self.ai_request_queue.popleft()
            self.update_global_ai_status_ui()
            self.update_status_ui(next_persona_id, self.tr(f"بدء معالجة الذكاء الاصطناعي ({request_type})... - Starting AI processing ({request_type})..."), "deep_purple")
            
            thread = self.active_threads.get(next_persona_id)
            if thread:
                self.ai_active_persona_id = next_persona_id
                if request_type == "answer":
                    thread.force_answer_now = True
                elif request_type == "learn_selectors":
                    thread.force_selector_learning = True
            else:
                logging.warning(self.tr(f"Persona {next_persona_id} requested AI but thread is not active. Removing from queue."))
                self.show_snackbar(self.tr(f"الشخصية {next_persona_id} غير نشطة. تم إزالتها من قائمة انتظار AI."), "warning")
                self.update_status_ui(next_persona_id, self.tr("البوت غير نشط. - Bot not active."), "red")
                self.update_global_ai_status_ui()
                self.process_next_ai_request() # حاول معالجة التالي في القائمة

        else:
            self.update_global_ai_status_ui()

    def update_global_ai_status_ui(self):
        """
        يحدث حالة AI العالمية في لوحة التحكم.
        """
        if self.ai_active_persona_id:
            self.ai_active_persona_label.setText(self.tr(f"الشخصية #{self.ai_active_persona_id} (نشط)"))
            self.ai_active_persona_label.setStyleSheet("font-size: 14px; color: #8BC34A; font-weight: bold;")
        else:
            self.ai_active_persona_label.setText(self.tr("لا يوجد نشاط"))
            self.ai_active_persona_label.setStyleSheet("font-size: 14px; color: #9E9E9E; font-weight: bold;")

        self.ai_queue_count_label.setText(str(len(self.ai_request_queue)))
        if len(self.ai_request_queue) > 0:
            self.ai_queue_count_label.setStyleSheet("font-size: 14px; color: #FFC107; font-weight: bold;")
        else:
            self.ai_queue_count_label.setStyleSheet("font-size: 14px; color: #9E9E9E; font-weight: bold;")

        for persona_id, controls in self.persona_controls.items():
            if persona_id in self.active_threads and self.active_threads[persona_id].is_alive():
                self.update_buttons_enabled_state(persona_id, controls['status_text'].text())

    def open_ai_settings_with_password(self):
        """
        يفتح نافذة إعدادات AI بعد التحقق من كلمة المرور.
        """
        password_dialog = PasswordDialog(AI_SETTINGS_PASSWORD, self)
        if password_dialog.exec() == QDialog.Accepted:
            # استدعاء AISettingsDialog مع مفتاح Gemini API الحالي
            ai_settings_dialog = AISettingsDialog(
                get_app_setting("question_ai_url", "https://omran2211-ask.hf.space/"),
                get_app_setting("selector_ai_url", "https://serverboot-yourusernamesurveyselectorai.hf.space/"),
                get_app_setting("gemini_api_key", ""), # تمرير مفتاح Gemini API
                self
            )
            if ai_settings_dialog.exec() == QDialog.Accepted:
                self.question_ai_url = get_app_setting("question_ai_url")
                self.selector_ai_url = get_app_setting("selector_ai_url")
                self.gemini_api_key = get_app_setting("gemini_api_key") # تحديث المفتاح بعد الحفظ
                # إعادة تهيئة OmranChatWidget إذا تغير مفتاح Gemini
                self.omran_chat_widget._init_gemini_model()
                self.show_snackbar(self.tr("تم حفظ إعدادات الذكاء الاصطناعي بنجاح!"), "success")
        else:
            self.show_snackbar(self.tr("كلمة سر خاطئة. لا يمكن الوصول إلى إعدادات الذكاء الاصطناعي."), "error")

    def save_ai_settings_from_tab(self):
        """
        يحفظ إعدادات AI من تبويبة الإعدادات المباشرة.
        """
        set_app_setting("question_ai_url", self.question_ai_url_field.text())
        set_app_setting("selector_ai_url", self.selector_ai_url_field.text())
        set_app_setting("gemini_api_key", self.gemini_api_key_field.text()) # حفظ مفتاح Gemini API
        self.question_ai_url = self.question_ai_url_field.text()
        self.selector_ai_url = self.selector_ai_url_field.text()
        self.gemini_api_key = self.gemini_api_key_field.text() # تحديث المفتاح
        # إعادة تهيئة OmranChatWidget إذا تغير مفتاح Gemini
        self.omran_chat_widget._init_gemini_model()
        self.show_snackbar(self.tr("تم حفظ إعدادات الذكاء الاصطناعي بنجاح!"), "success")

    def save_persona_card_settings(self):
        """
        يحفظ إعدادات حجم بطاقة الشخصية.
        """
        new_width = self.persona_card_width_spinbox.value()
        new_height = self.persona_card_height_spinbox.value()
        set_app_setting("persona_card_width", str(new_width))
        set_app_setting("persona_card_height", str(new_height))
        self.persona_card_width = new_width
        self.persona_card_height = new_height
        self.load_personas_to_ui() # إعادة تحميل الواجهة لتطبيق التغييرات
        self.show_snackbar(self.tr("تم حفظ حجم بطاقات الشخصيات بنجاح!"), "success")

    def save_delay_settings(self):
        """
        يحفظ إعدادات التأخير العشوائي.
        """
        min_delay = self.min_delay_spinbox.value()
        max_delay = self.max_delay_spinbox.value()
        if min_delay > max_delay:
            self.show_snackbar(self.tr("الحد الأدنى للتأخير لا يمكن أن يكون أكبر من الحد الأقصى!"), "error")
            return
        set_app_setting("min_delay_seconds", str(min_delay))
        set_app_setting("max_delay_seconds", str(max_delay))
        self.show_snackbar(self.tr("تم حفظ إعدادات التأخير بنجاح!"), "success")

    def load_qna_history(self, persona_id=None):
        """
        يحمل سجل الأسئلة والأجوبة ويعرضه.
        """
        history = get_conversation_history(persona_id)
        self.qna_history_text_browser.clear()
        if not history:
            self.qna_history_text_browser.setText(self.tr("<span style='color: #9E9E9E;'>لا يوجد سجل للأسئلة والأجوبة.</span>"))
            return
        
        for timestamp, question, answer in history:
            self.qna_history_text_browser.append(self.tr(f"<span style='color: #BBDEFB;'><b>{timestamp}</b></span>"))
            self.qna_history_text_browser.append(self.tr(f"<span style='color: #ADD8E6;'><b>السؤال:</b> {question}</span>"))
            self.qna_history_text_browser.append(self.tr(f"<span style='color: #4CAF50;'><b>الإجابة:</b> {answer}</span>"))
            self.qna_history_text_browser.append("<br>") # مسافة بين الإدخالات

    def handle_omran_error_message(self, error_message: str, persona_id: int):
        """
        يتعامل مع رسائل الخطأ من البوتات ويعرضها في Omran Chat.
        """
        # تخزين تفاصيل الخطأ لفتحها لاحقاً
        self.last_error_details[persona_id] = error_message
        # إرسال الخطأ إلى واجهة Omran Chat
        self.omran_chat_widget.set_last_error(self.tr(f"خطأ من الشخصية #{persona_id}: {error_message}"))
        # التأكد من ظهور أيقونة الخطأ على البطاقة
        if persona_id in self.persona_controls:
            self.persona_controls[persona_id]['error_icon_btn'].show()
        
        # إظهار نافذة Omran Chat عند حدوث خطأ
        self.omran_chat_widget.show()
        self.omran_chat_widget.raise_() # جلبها للأمام

    def show_persona_error_details(self, persona_id: int):
        """
        يعرض نافذة تفاصيل الخطأ لشخصية معينة.
        """
        error_message = self.last_error_details.get(persona_id, self.tr("لا توجد تفاصيل خطأ متاحة لهذه الشخصية."))
        dialog = ErrorDetailsDialog(persona_id, error_message, self)
        dialog.exec()

    def open_omran_chat_with_context(self, persona_id: int):
        """
        يفتح نافذة Omran Chat مع سياق الشخصية المحددة.
        """
        self.omran_chat_widget.show()
        self.omran_chat_widget.raise_() # جلبها للأمام

        # إرسال رسالة إلى Omran بخصوص الشخصية
        self.omran_chat_widget.append_message(
            self.tr("Omran"),
            self.tr(f"مرحباً! لقد قمت بالتبديل إلى محادثتي لأنك نقرت على عنوان الشخصية #{persona_id}. "
                    f"كيف يمكنني مساعدتك بخصوص هذه الشخصية أو أي شيء آخر؟"),
            "#4CAF50"
        )
        # إذا كان هناك خطأ لهذه الشخصية، اعرضه في Omran Chat
        if persona_id in self.last_error_details:
            self.omran_chat_widget.set_last_error(self.tr(f"آخر خطأ من الشخصية #{persona_id}: {self.last_error_details[persona_id]}"))


    def show_snackbar(self, message: str, message_type: str = "info"):
        """
        يعرض رسالة إشعار مؤقتة (Snackbar) في أسفل الشاشة.
        """
        # تعيين لون الخلفية بناءً على نوع الرسالة
        color_map = {
            "info": "#2196F3",    # أزرق
            "success": "#4CAF50", # أخضر
            "warning": "#FF9800", # برتقالي
            "error": "#F44336"    # أحمر
        }
        bg_color = color_map.get(message_type, "#333")
        self.snackbar.setStyleSheet(f"background-color: {bg_color}; color: white; padding: 10px 20px; border-radius: 8px; font-size: 14px;")
        
        self.snackbar.setText(message)
        self.snackbar.adjustSize() # ضبط الحجم حسب النص

        # وضع الـ Snackbar في أسفل المنتصف
        parent_rect = self.rect()
        snackbar_width = self.snackbar.width()
        snackbar_height = self.snackbar.height()
        x = (parent_rect.width() - snackbar_width) // 2
        y = parent_rect.height() - snackbar_height - 20 # 20 بكسل من الأسفل
        
        # إعداد الرسوم المتحركة للظهور
        start_rect = QRect(x, parent_rect.height(), snackbar_width, snackbar_height)
        end_rect = QRect(x, y, snackbar_width, snackbar_height)
        
        self.snackbar_animation.setStartValue(start_rect)
        self.snackbar_animation.setEndValue(end_rect)
        
        self.snackbar.show()
        self.snackbar_animation.start()
        self.snackbar_timer.start(3000) # إخفاء بعد 3 ثوانٍ

    def hide_snackbar(self):
        """
        يخفي رسالة الإشعار (Snackbar).
        """
        # إعداد الرسوم المتحركة للاختفاء
        parent_rect = self.rect()
        snackbar_width = self.snackbar.width()
        snackbar_height = self.snackbar.height()
        x = (parent_rect.width() - snackbar_width) // 2
        y = parent_rect.height() - snackbar_height - 20
        
        start_rect = QRect(x, y, snackbar_width, snackbar_height)
        end_rect = QRect(x, parent_rect.height(), snackbar_width, snackbar_height) # العودة إلى الأسفل
        
        self.snackbar_animation.setStartValue(start_rect)
        self.snackbar_animation.setEndValue(end_rect)
        self.snackbar_animation.finished.connect(self.snackbar.hide) # إخفاء بعد انتهاء الرسوم المتحركة
        self.snackbar_animation.start()

    def toggle_theme(self):
        """
        يتبدل بين الثيمات المختلفة (داكن، فاتح، شبه شفاف).
        """
        if self.current_theme_name == "dark":
            apply_stylesheet(self.app, theme='light_blue.xml', extra={
                'font_family': 'Cairo',
                'danger': '#D32F2F',
                'warning': '#FFA000',
                'success': '#388E3C',
                'info': '#1976D2',
            })
            set_app_setting("current_theme", "light")
            self.current_theme_name = "light"
            self.theme_toggle_button_advanced.setIcon(QIcon(":/qt-material/dark_mode"))
            self.theme_toggle_button_advanced.setText(self.tr("تبديل إلى الثيم الداكن"))
            self.setWindowOpacity(1.0) # إزالة الشفافية إذا كانت مطبقة
            set_app_setting("app_transparency", "100") # حفظ قيمة الشفافية
            self.transparency_slider.setValue(100)
        elif self.current_theme_name == "light":
            # الثيم الشفاف (مثال: استخدام dark_amber كأساس ثم تطبيق الشفافية)
            apply_stylesheet(self.app, theme='dark_amber.xml', extra={
                'font_family': 'Cairo',
                'danger': '#FF5252',
                'warning': '#FFD700',
                'success': '#8BC34A',
                'info': '#4FC3F7',
            })
            set_app_setting("current_theme", "transparent_dark")
            self.current_theme_name = "transparent_dark"
            self.theme_toggle_button_advanced.setIcon(QIcon(":/qt-material/opacity"))
            self.theme_toggle_button_advanced.setText(self.tr("تبديل إلى الثيم النهاري"))
            # تطبيق الشفافية المحفوظة أو الافتراضية
            initial_transparency = float(get_app_setting("app_transparency", "80")) # شفافية افتراضية للثيم الشفاف
            self.setWindowOpacity(initial_transparency / 100.0)
            self.transparency_slider.setValue(int(initial_transparency))
        else: # العودة إلى الثيم الداكن
            apply_stylesheet(self.app, theme='dark_blue.xml', extra={
                'font_family': 'Cairo',
                'danger': '#B71C1C',
                'warning': '#FFB300',
                'success': '#4CAF50',
                'info': '#2196F3',
            })
            set_app_setting("current_theme", "dark")
            self.current_theme_name = "dark"
            self.theme_toggle_button_advanced.setIcon(QIcon(":/qt-material/light_mode"))
            self.theme_toggle_button_advanced.setText(self.tr("تبديل إلى الثيم الفاتح"))
            self.setWindowOpacity(1.0) # إزالة الشفافية
            set_app_setting("app_transparency", "100") # حفظ قيمة الشفافية
            self.transparency_slider.setValue(100)
        
        self.apply_custom_styles() # إعادة تطبيق الأنماط المخصصة

    def update_app_transparency(self, value):
        """
        يحدث شفافية النافذة الرئيسية بناءً على قيمة شريط التمرير.
        """
        self.transparency_value_label.setText(self.tr(f"{value}%"))
        opacity_value = value / 100.0
        self.setWindowOpacity(opacity_value)
        set_app_setting("app_transparency", str(value)) # حفظ قيمة الشفافية

    def apply_custom_styles(self):
        """
        يعيد تطبيق الأنماط المخصصة التي قد لا تتغير تلقائياً مع تبديل الثيم.
        """
        # إعادة تطبيق الأنماط على عناصر الواجهة التي قد لا تتغير تلقائياً
        self.central_widget.setStyleSheet(self.central_widget.styleSheet())
        self.tabs.setStyleSheet(self.tabs.styleSheet())
        self.omran_chat_widget.setStyleSheet(self.omran_chat_widget.styleSheet())
        self.logs_text_browser.setStyleSheet(self.logs_text_browser.styleSheet())
        self.qna_history_text_browser.setStyleSheet(self.qna_history_text_browser.styleSheet())
        
        # تحديث نص زر تبديل الثيم بعد تغيير اللغة
        if self.current_theme_name == "dark":
            self.theme_toggle_button_advanced.setText(self.tr("تبديل إلى الثيم الفاتح"))
        elif self.current_theme_name == "light":
            self.theme_toggle_button_advanced.setText(self.tr("تبديل إلى الثيم الداكن"))
        elif self.current_theme_name == "transparent_dark":
            self.theme_toggle_button_advanced.setText(self.tr("تبديل إلى الثيم النهاري"))

        # تحديث أيقونات بطاقات الشخصيات (لضمان تحديث الألوان)
        for persona_id, controls in self.persona_controls.items():
            current_status_text = controls['status_text'].text()
            # استخراج لون الحالة الحالي من ورقة الأنماط (قد يكون هذا معقدًا)
            # بدلاً من ذلك، يمكننا إعادة تعيين الحالة لتحديث الألوان
            self.update_status_ui(persona_id, current_status_text, "grey") # استخدام لون افتراضي لإعادة التحديث

    def send_omran_random_tip(self):
        """
        يرسل نصيحة عشوائية من Omran Assistant إلى Omran Chat.
        """
        tips = [
            self.tr("نصيحة اليوم من Omran Assistant: تأكد من أن بروكسياتك نشطة قبل بدء التشغيل لتجنب الأخطاء!"),
            self.tr("نصيحة اليوم من Omran Assistant: إذا واجهت مشكلة في تحديد العناصر، جرب استخدام زر 'تعلم المحددات الآن' لتحديث معرفتي."),
            self.tr("نصيحة اليوم من Omran Assistant: يمكنك مراجعة سجل الأحداث في التبويبة المخصصة لتتبع نشاط البوتات."),
            self.tr("نصيحة اليوم من Omran Assistant: لتجنب الحظر، استخدم تأخيرات عشوائية بين الطلبات ودوّر وكلاء المستخدم."),
            self.tr("نصيحة اليوم من Omran Assistant: هل تعلم أنه يمكنك النقر على عنوان الشخصية في لوحة التحكم لفتح محادثة معي بخصوصها؟"),
            self.tr("نصيحة اليوم من Omran Assistant: قم بتحديث مفتاح 2Captcha API الخاص بك بانتظام لضمان حل الكابتشا بسلاسة."),
            self.tr("نصيحة اليوم من Omran Assistant: إذا توقف بوت ما، تحقق من سجل الأخطاء الخاص به للحصول على تفاصيل.")
        ]
        tip = random.choice(tips)
        self.omran_chat_widget.append_message(self.tr("Omran Assistant"), tip, "#FFC107") # لون كهرماني للنصائح
        self.omran_chat_widget.show() # إظهار النافذة العائمة
        self.omran_chat_widget.raise_() # جلبها للأمام

    def add_daily_info_to_logs(self):
        """
        يضيف معلومة يومية عشوائية إلى سجلات التطبيق.
        """
        daily_infos = [
            self.tr("معلومة اليوم: الذكاء الاصطناعي يتطور بسرعة مذهلة، ويتم إصدار نماذج جديدة باستمرار."),
            self.tr("معلومة اليوم: تعلم الآلة هو فرع من الذكاء الاصطناعي يركز على بناء أنظمة تتعلم من البيانات."),
            self.tr("معلومة اليوم: معالجة اللغة الطبيعية (NLP) هي مجال في الذكاء الاصطناعي يركز على تفاعل أجهزة الكمبيوتر مع اللغة البشرية."),
            self.tr("معلومة اليوم: الروبوتات ليست مجرد آلات، بل هي أنظمة تجمع بين الميكانيكا والإلكترونيات والبرمجيات."),
            self.tr("معلومة اليوم: البيانات هي الوقود الذي يغذي أنظمة الذكاء الاصطناعي الحديثة. كلما زادت جودتها، زادت دقة النتائج."),
            self.tr("معلومة اليوم: شبكات الخصومة التوليدية (GANs) هي نوع من نماذج الذكاء الاصطناعي التي يمكنها توليد بيانات جديدة تشبه البيانات الحقيقية.")
        ]
        info = random.choice(daily_infos)
        logging.info(f"معلومة اليوم: {info}") # ستظهر في سجل الأحداث

    # ==============================================================================
    # --- 8. Animations and Visual Effects ---
    # ==============================================================================
    def eventFilter(self, obj, event):
        """
        فلتر الأحداث لتطبيق تأثيرات التحويم على الأزرار.
        """
        if isinstance(obj, QPushButton):
            if event.type() == QEvent.Enter:
                # عند دخول الماوس، قم بتكبير الزر قليلاً
                self.animate_button_scale(obj, 1.0, 1.05) # من 100% إلى 105%
            elif event.type() == QEvent.Leave:
                # عند خروج الماوس، قم بإعادة الزر لحجمه الأصلي
                self.animate_button_scale(obj, 1.05, 1.0)
            elif event.type() == QEvent.MouseButtonPress:
                # تأثير بسيط عند الضغط (ليس حلقة دائرية كاملة بسبب التعقيد)
                self.animate_button_scale(obj, 1.05, 0.95) # تصغير قليلاً عند الضغط
            elif event.type() == QEvent.MouseButtonRelease:
                # العودة للحجم الطبيعي عند الإفراج عن الضغط
                self.animate_button_scale(obj, 0.95, 1.0)
        return super().eventFilter(obj, event)

    def animate_button_scale(self, button, start_scale, end_scale):
        """
        ينشئ رسوم متحركة لتغيير حجم الزر.
        """
        animation = QPropertyAnimation(button, b"geometry")
        animation.setDuration(150) # مدة قصيرة
        animation.setEasingCurve(QEasingCurve.OutQuad)

        start_rect = button.geometry()
        end_width = int(start_rect.width() * end_scale)
        end_height = int(start_rect.height() * end_scale)
        # لجعله يتمدد من المركز
        end_x = start_rect.x() - (end_width - start_rect.width()) // 2
        end_y = start_rect.y() - (end_height - start_rect.height()) // 2

        animation.setStartValue(start_rect)
        animation.setEndValue(QRect(end_x, end_y, end_width, end_height))
        animation.start(QAbstractAnimation.DeleteWhenStopped) # حذف الرسوم المتحركة بعد الانتهاء

    # ==============================================================================
    # --- 9. Multi-language Support ---
    # ==============================================================================
    def load_language(self, language_code):
        """
        يقوم بتحميل ملف الترجمة وتثبيته.
        """
        if hasattr(self, '_translator') and self._translator:
            QApplication.instance().removeTranslator(self._translator)
        
        self._translator = QTranslator()
        # افترض أن ملفات .qm موجودة في مجلد 'translations' بجانب ملف التطبيق
        translations_path = os.path.join(os.path.dirname(__file__), "translations")
        if self._translator.load(f"{language_code}.qm", translations_path):
            QApplication.instance().installTranslator(self._translator)
            logging.info(f"Loaded language: {language_code}")
            self.current_language = language_code
            # إعادة ترجمة الواجهة بعد تغيير اللغة
            if hasattr(self, 'central_widget') and self.central_widget.isVisible(): # تجنب إعادة الترجمة قبل تهيئة الواجهة
                self.retranslate_ui()
        else:
            logging.warning(f"Could not load translator for language: {language_code} from {translations_path}")
            # إذا لم يتم العثور على ملف الترجمة، تأكد أن الواجهة لا تزال تعمل
            self.current_language = "ar" # العودة إلى الافتراضي إذا فشل التحميل
            if hasattr(self, 'central_widget') and self.central_widget.isVisible():
                self.retranslate_ui() # لإعادة تعيين النصوص إلى العربية الافتراضية

    def change_language(self, index):
        """
        يغير لغة التطبيق بناءً على اختيار المستخدم.
        """
        language_code = self.language_combo.currentData()
        if self.current_language != language_code:
            self.load_language(language_code)
            set_app_setting("current_language", language_code)
            self.show_snackbar(self.tr(f"تم تغيير اللغة إلى {language_code}."), "info")


    def retranslate_ui(self):
        """
        يعيد ترجمة جميع عناصر الواجهة الرسومية بعد تغيير اللغة.
        """
        self.findChild(QLabel, "app_title_label").setText(self.tr("OMRAN ASK7"))
        
        # تحديث نصوص العناصر الرئيسية
        for i in range(self.main_layout.count()):
            item = self.main_layout.itemAt(i)
            if item and item.widget():
                if isinstance(item.widget(), QLabel):
                    if item.widget().objectName() == "title_label": # إذا كان لديك اسم كائن
                        item.widget().setText(self.tr("OMRAN ASK7"))
                    elif item.widget().objectName() == "description_label":
                        self.findChild(QLabel, "app_description_label").setText(self.tr("أداة أتمتة الاستبيانات الذكية"))
        
        # تحديث نصوص تبويبات لوحة التحكم
        self.tabs.setTabText(self.tabs.indexOf(self.findChild(QWidget, "dashboard_tab")), self.tr("الشخصيات"))
        self.tabs.setTabText(self.tabs.indexOf(self.findChild(QWidget, "logs_tab")), self.tr("سجل الأحداث"))
        self.tabs.setTabText(self.tabs.indexOf(self.findChild(QWidget, "ai_settings_tab")),
                             self.tr("إعدادات الذكاء الاصطناعي"))
        self.tabs.setTabText(self.tabs.indexOf(self.findChild(QWidget, "qna_history_tab")),
                             self.tr("سجل الأسئلة والأجوبة"))
        self.tabs.setTabText(self.tabs.indexOf(self.findChild(QWidget, "advanced_settings_tab")),
                             self.tr("إعدادات متقدمة"))

        # تحديث نصوص عناصر لوحة التحكم العلوية
        self.ai_active_persona_label.setText(self.tr("لا يوجد نشاط")) # سيتم تحديثه لاحقاً
        self.ai_queue_count_label.setText("0") # سيتم تحديثه لاحقاً
        # تحديث تسميات AI Activity و AI Queue
        self.findChild(QLabel, "ai_activity_label_title").setText(self.tr("حالة الذكاء الاصطناعي:"))
        self.findChild(QLabel, "ai_queue_label_title").setText(self.tr("قائمة انتظار الذكاء الاصطناعي:"))

        # تحديث نصوص عناصر تبويبة لوحة التحكم (Dashboard)
        self.headless_switch.setText(self.tr("وضع التصفح الخفي (بدون واجهة)"))
        self.headless_switch.setToolTip(self.tr("تشغيل المتصفح بدون واجهة رسومية مرئية."))

        # تحديث نصوص تبويبة إعدادات AI
        # لتجنب الأخطاء، قم بتعيين objectName لـ QLabel في setup_ui
        # مثلاً: question_ai_url_label = QLabel(self.tr("رابط AI الأسئلة:"))
        # question_ai_url_label.setObjectName("question_ai_url_label")
        # layout.addRow(question_ai_url_label, self.question_ai_url_field)
        # ثم استخدم self.findChild(QLabel, "question_ai_url_label").setText(...)
        # مؤقتاً، سنقوم بتحديث الـ placeholder و tooltip فقط
        self.findChild(QLabel, "question_ai_url_label").setText(self.tr("رابط AI الأسئلة:"))
        self.question_ai_url_field.setPlaceholderText(
            self.tr("رابط نموذج الذكاء الاصطناعي للإجابة على الأسئلة (Gradio)"))
        self.question_ai_url_field.setToolTip(
            self.tr("الرابط لنموذج الذكاء الاصطناعي (Gradio) الذي سيستخدم للإجابة على الأسئلة."))

        self.findChild(QLabel, "selector_ai_url_label").setText(self.tr("رابط AI المحددات:"))
        self.selector_ai_url_field.setPlaceholderText(
            self.tr("رابط نموذج الذكاء الاصطناعي لتعلم المحددات (Hugging Face Gradio)"))
        self.selector_ai_url_field.setToolTip(
            self.tr("الرابط لخادم Gradio AI على Hugging Face الذي سيستخدم لتعلم محددات عناصر الاستبيان من HTML."))

        self.findChild(QLabel, "gemini_api_key_label").setText(self.tr("مفتاح Gemini API:"))
        self.gemini_api_key_field.setPlaceholderText(self.tr("أدخل مفتاح Gemini API هنا"))
        self.gemini_api_key_field.setToolTip(self.tr("مفتاح API لنموذج Gemini AI المستخدم في محادثة Omran."))
        self.findChild(QPushButton, "save_ai_settings_button").setText(self.tr("حفظ إعدادات AI"))


        # تحديث نصوص تبويبة سجل الأسئلة والأجوبة
        self.load_qna_history() # لإعادة تحميل السجل بالنصوص المترجمة

        # تحديث نصوص تبويبة الإعدادات المتقدمة
        self.findChild(QLabel, "persona_card_width_label").setText(self.tr("عرض البطاقة (بكسل):"))
        self.findChild(QLabel, "persona_card_height_label").setText(self.tr("ارتفاع البطاقة (بكسل):"))
        self.findChild(QPushButton, "save_card_size_button").setText(self.tr("حفظ حجم البطاقة"))

        self.findChild(QLabel, "min_delay_seconds_label").setText(self.tr("الحد الأدنى للتأخير (ثواني):"))
        self.findChild(QLabel, "max_delay_seconds_label").setText(self.tr("الحد الأقصى للتأخير (ثواني):"))
        self.findChild(QPushButton, "save_delay_button").setText(self.tr("حفظ إعدادات التأخير"))

        self.findChild(QLabel, "transparency_label").setText(self.tr("مستوى الشفافية:"))
        self.transparency_slider.setToolTip(
            self.tr("تحكم في شفافية الخلفية للثيم الشفاف. 0% = معتم, 100% = شفاف تماماً."))

        self.findChild(QLabel, "language_label").setText(self.tr("اللغة:"))
        self.language_combo.setItemText(0, self.tr("العربية"))
        self.language_combo.setItemText(1, self.tr("English"))

        self.findChild(QLabel, "other_advanced_settings_label").setText(self.tr("إعدادات متقدمة أخرى ستأتي هنا."))
        # لتحديث تسميات QFormLayout، يجب إعادة بناء الصفوف أو الوصول إلى QLabel مباشرة
        # مؤقتاً، لن يتم تحديث تسميات QFormLayout تلقائياً بهذه الطريقة.
        # advanced_settings_layout.itemAt(advanced_settings_layout.indexOf(self.findChild(QLabel, "other_advanced_settings_label"))).widget().setText(self.tr("إعدادات متقدمة أخرى ستأتي هنا."))


        # إعادة تحميل بطاقات الشخصيات لتحديث نصوصها
        self.load_personas_to_ui()
        # تحديث حالة الأزرار بعد إعادة الترجمة
        for persona_id, controls in self.persona_controls.items():
            self.update_buttons_enabled_state(persona_id, controls['status_text'].text())

        # تحديث نصوص Omran Chat Widget
        self.omran_chat_widget.setWindowTitle(self.tr("محادثة Omran"))
        # self.omran_chat_widget.findChild(QLabel, "title_label").setText(self.tr("محادثة Omran")) # هذا يحتاج لـ objectName
        self.omran_chat_widget.user_input_field.setPlaceholderText(self.tr("اكتب رسالتك هنا لـ Omran..."))
        self.omran_chat_widget.send_button.setText(self.tr("إرسال"))
        self.omran_chat_widget.help_error_button.setText(self.tr("مساعدة في آخر خطأ"))
        self.omran_chat_widget.ask_free_ai_button.setText(self.tr("اسأل AI سؤال حر"))
        self.omran_chat_widget.clear_chat_button.setText(self.tr("مسح المحادثة"))
        self.omran_chat_widget.typing_indicator_label.setText(self.tr("Omran يكتب..."))
        # إعادة تعيين رسالة الترحيب في Omran Chat
        self.omran_chat_widget.chat_history.clear()
        self.omran_chat_widget.append_message(self.tr("Omran"), self.tr("مرحباً! أنا Omran، مساعدك الذكي. كيف يمكنني مساعدتك اليوم؟"), "#4CAF50")


    # إضافة دالة tr لترجمة النصوص داخل MainWindow
    def tr(self, text):
        return QApplication.instance().translate("MainWindow", text)


# ==============================================================================
# --- 10. Application Entry Point - نقطة بدء التطبيق ---
# ==============================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    # قم بتعيين 'app' كخاصية لـ MainWindow لكي يمكن الوصول إليها من toggle_theme
    MainWindow.app = app 

    # تتبع تشغيل التطبيق
    def track_app_start():
        device_name = platform.node() # اسم الجهاز
        mac_address = gma() # عنوان MAC
        message = f"تم تشغيل التطبيق من الجهاز: {device_name} (MAC: {mac_address})"
        send_telegram_message(message)

    # تشغيل دالة التتبع في خيط منفصل لتجنب حظر بدء تشغيل الواجهة
    threading.Thread(target=track_app_start, daemon=True).start()

    setup_database()

    main_win = MainWindow()
    main_win.show()

    sys.exit(app.exec())
