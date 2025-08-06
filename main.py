# -*- coding: utf-8 -*-
import os
import re
import threading
import time
import base64
import io
import random
import requests

try:
    from PIL import Image, ImageTk, UnidentifiedImageError, ImageOps, ImageEnhance
except ImportError:
    print("خطأ: مكتبة Pillow (PIL) غير مثبتة. يرجى تثبيتها باستخدام: pip install Pillow")
    exit()
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox

try:
    import numpy as np
except ImportError:
    print("خطأ: مكتبة numpy غير مثبتة. يرجى تثبيتها باستخدام: pip install numpy")
    exit()
try:
    import cv2
except ImportError:
    print("خطأ: مكتبة opencv-python غير مثبتة. يرجى تثبيتها باستخدام: pip install opencv-python")
    exit()
try:
    import onnxruntime as ort
except ImportError:
    print("خطأ: مكتبة onnxruntime غير مثبتة. يرجى تثبيتها باستخدام: pip install onnxruntime")
    exit()
try:
    import torchvision.transforms as transforms
except ImportError:
    print("خطأ: مكتبة torchvision غير مثبتة. يرجى تثبيتها باستخدام: pip install torchvision")
    exit()

CHARSET = '0123456789abcdefghijklmnopqrstuvwxyz'
CHAR2IDX = {c: i for i, c in enumerate(CHARSET)}
IDX2CHAR = {i: c for c, i in CHAR2IDX.items()}
NUM_CLASSES = len(CHARSET)
NUM_POS = 5
ONNX_MODEL_PATH = r"C:\Users\ccl\Desktop\holako bag.onnx"  # الرجاء التأكد من صحة هذا المسار


def preprocess_for_model():
    """إعداد تحويلات الصور للنموذج."""
    return transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.Grayscale(num_output_channels=3),
        transforms.ToTensor(),  # تحويل إلى Tensor
        transforms.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5]),
    ])


import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class CaptchaApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Captcha Solver (ONNX Runtime) - v1.5")  # تحديث الإصدار
        self.device = 'cpu'
        if not os.path.exists(ONNX_MODEL_PATH):
            print(f"خطأ فادح: ملف نموذج ONNX غير موجود في المسار: {ONNX_MODEL_PATH}")
            self.root.quit()
            return
        try:
            available_providers = ort.get_available_providers()
            provider_to_use = ['CPUExecutionProvider']
            self.session = ort.InferenceSession(ONNX_MODEL_PATH, providers=provider_to_use)
            print(f"تم تحميل نموذج ONNX بنجاح باستخدام: {self.session.get_providers()}")
        except Exception as e:
            print(f"خطأ في تحميل النموذج: {e}")
            self.root.quit()
            return

        self.accounts = {}
        self.current_captcha = None  # يخزن tuple (user, pid) للكابتشا التي يتم معالجتها حالياً
        self.current_captcha_frame = None  # مرجع لإطار عرض الكابتشا الحالي والمرتبط بـ self.current_captcha
        self.proxy_entry = None
        self.apply_proxy_button = None
        self.notification_label = None
        self.speed_label = None
        self.accounts_frame = None
        self._build_gui()

    def _build_gui(self):
        settings_frame = tk.Frame(self.root)
        settings_frame.pack(padx=10, pady=10, fill=tk.X)
        self.notification_label = tk.Label(settings_frame, text="مرحباً! أدخل البروكسي (إذا أردت) ثم أضف حسابًا.",
                                           font=("Helvetica", 10), justify=tk.RIGHT, fg="blue")
        self.notification_label.pack(pady=5, fill=tk.X)
        btn_add = tk.Button(settings_frame, text="إضافة حساب", command=self.add_account, width=15)
        btn_add.pack(pady=5)
        proxy_frame = tk.Frame(settings_frame)
        proxy_frame.pack(pady=(5, 5), fill=tk.X)
        self.apply_proxy_button = tk.Button(proxy_frame, text="تطبيق البروكسي", command=self.apply_proxy_settings,
                                            width=15)
        self.apply_proxy_button.pack(side=tk.LEFT, padx=(0, 10))
        proxy_label = tk.Label(proxy_frame, text=":بروكسي (IP:Port)")
        proxy_label.pack(side=tk.RIGHT, padx=(5, 0))
        self.proxy_entry = tk.Entry(proxy_frame, justify=tk.RIGHT)
        self.proxy_entry.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        self.accounts_frame = tk.Frame(self.root, bd=1, relief="solid")
        self.accounts_frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        self.speed_label = tk.Label(self.root, text="المعالجة الأولية: - | التنبؤ: -", font=("Helvetica", 9))
        self.speed_label.pack(side=tk.BOTTOM, pady=(0, 5))

    def update_notification(self, message, color="black"):
        if self.notification_label and self.notification_label.winfo_exists():
            self.notification_label.config(text=message, fg=color)
        print(f"[{time.strftime('%H:%M:%S')}] [{color.upper()}] {message}")

    def generate_user_agent(self):
        ua_list = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
            "Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.105 Mobile Safari/537.36",
            "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Windows NT 6.1; WOW64; Trident/7.0; rv:11.0) like Gecko",
        ]
        return random.choice(ua_list)

    def apply_proxy_settings(self):
        # ... (نفس الكود بدون تغيير)
        if not self.proxy_entry:
            print("خطأ داخلي: لم يتم تهيئة مربع إدخال البروكسي.")
            return
        proxy_address = self.proxy_entry.get().strip()
        new_proxies = {}
        if proxy_address:
            if ':' not in proxy_address or not proxy_address.split(':')[0] or not proxy_address.split(':')[
                -1].isdigit():
                messagebox.showwarning("تحذير البروكسي",
                                       f"تنسيق البروكسي يبدو غير صالح: '{proxy_address}'.\nالتنسيق المتوقع هو IP:Port.\nلم يتم تطبيق التغيير.",
                                       parent=self.root)
                return
            else:
                formatted_proxy = f"http://{proxy_address}"
                new_proxies = {'http': formatted_proxy, 'https': formatted_proxy}
        updated_count = 0
        error_count = 0
        if not self.accounts:
            self.update_notification("لا توجد حسابات نشطة لتطبيق إعدادات البروكسي عليها.", "orange")
            return
        for user, account_data in self.accounts.items():
            if "session" in account_data and isinstance(account_data["session"], requests.Session):
                try:
                    account_data["session"].proxies = new_proxies
                    updated_count += 1
                except Exception as e:
                    error_count += 1
                    print(f"خطأ أثناء تحديث البروكسي للحساب {user}: {e}")
        if error_count > 0:
            self.update_notification(f"حدث خطأ أثناء تحديث البروكسي لـ {error_count} حساب(ات).", "red")
        if updated_count > 0:
            if new_proxies:
                self.update_notification(f"تم تطبيق البروكسي '{proxy_address}' على {updated_count} حساب(ات).", "blue")
            else:
                self.update_notification(f"تم إزالة إعدادات البروكسي من {updated_count} حساب(ات).", "blue")
        elif error_count == 0 and self.accounts:
            self.update_notification("لم يتم تغيير إعدادات البروكسي.", "grey")

    def create_session(self, user_agent):
        # ... (نفس الكود بدون تغيير)
        headers = {
            "User-Agent": user_agent, "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ar,en-US;q=0.9,en;q=0.8", "Content-Type": "application/json",
            "Origin": "https://ecsc.gov.sy", "Referer": "https://ecsc.gov.sy/",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0", "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-site",
            "Source": "WEB", "Host": "api.ecsc.gov.sy:8443", "Connection": "keep-alive",
        }
        session = requests.Session()
        session.headers.update(headers)
        session.verify = False
        if self.proxy_entry:
            proxy_address = self.proxy_entry.get().strip()
            if proxy_address and ':' in proxy_address:
                try:
                    ip, port = proxy_address.split(':', 1)
                    if ip and port.isdigit():
                        formatted_proxy = f"http://{proxy_address}"
                        proxies = {'http': formatted_proxy, 'https': formatted_proxy}
                        session.proxies = proxies
                except Exception as e:
                    print(f"خطأ في تعيين البروكسي الأولي للجلسة الجديدة: {e}")
        return session

    def login(self, username, password, session, retries=2):
        # ... (نفس الكود مع إزالة time.sleep) ...
        url = "https://api.ecsc.gov.sy:8443/secure/auth/login"
        payload = {"username": username, "password": password}
        login_headers = {'Referer': 'https://ecsc.gov.sy/login'}
        for attempt in range(retries):
            try:
                self.update_notification(f"[{username}] محاولة تسجيل الدخول ({attempt + 1}/{retries})...", "grey")
                r = session.post(url, json=payload, headers=login_headers, timeout=(10, 20))
                if r.status_code == 200:
                    self.update_notification(f"[{username}] تم تسجيل الدخول بنجاح.", "green")
                    return True
                elif r.status_code == 401:
                    self.update_notification(f"[{username}] فشل تسجيل الدخول (401): بيانات الاعتماد غير صحيحة.", "red")
                    return False
                else:
                    self.update_notification(f"[{username}] فشل تسجيل الدخول ({r.status_code}). النص: {r.text[:200]}",
                                             "red")
                    if 500 <= r.status_code < 600 and attempt < retries - 1:
                        continue
                    else:
                        return False
            except requests.exceptions.RequestException as e:
                self.update_notification(f"[{username}] خطأ شبكة أثناء تسجيل الدخول: {type(e).__name__}", "red")
                if isinstance(e, requests.exceptions.ProxyError): return False
                if attempt < retries - 1:
                    continue
                else:
                    return False
            except Exception as e:
                self.update_notification(f"[{username}] خطأ غير متوقع أثناء تسجيل الدخول: {e}", "red")
                return False
        self.update_notification(f"[{username}] فشل تسجيل الدخول بعد {retries} محاولات.", "red")
        return False

    def add_account(self):
        # ... (نفس الكود بدون تغيير)
        user = simpledialog.askstring("اسم المستخدم", "أدخل اسم المستخدم:", parent=self.root)
        if user is None: return
        pwd = simpledialog.askstring("كلمة المرور", "أدخل كلمة المرور:", show="*", parent=self.root)
        if pwd is None: return
        if not user or not pwd:
            messagebox.showwarning("إدخال ناقص", "الرجاء إدخال اسم المستخدم وكلمة المرور.", parent=self.root)
            return
        if user in self.accounts:
            messagebox.showwarning("حساب مكرر", f"الحساب '{user}' موجود بالفعل.", parent=self.root)
            return
        session = self.create_session(self.generate_user_agent())
        if not self.login(user, pwd, session):
            return
        self.accounts[user] = {"password": pwd, "session": session}
        proc_ids_data = self.fetch_process_ids(session, user)
        if proc_ids_data is not None:
            self._create_account_ui(user, proc_ids_data)
        else:
            if user in self.accounts: del self.accounts[user]

    def fetch_process_ids(self, session, username):
        # ... (نفس الكود مع إزالة time.sleep) ...
        url = "https://api.ecsc.gov.sy:8443/dbm/db/execute"
        payload = {"ALIAS": "OPkUVkYsyq", "P_USERNAME": "WebSite", "P_PAGE_INDEX": 0, "P_PAGE_SIZE": 100}
        headers = {"Alias": "OPkUVkYsyq", "Referer": "https://ecsc.gov.sy/requests"}
        try:
            r = session.post(url, json=payload, headers=headers, timeout=(10, 20))
            if r.status_code == 200:
                result = r.json()
                if "P_RESULT" in result and result["P_RESULT"]:
                    return result["P_RESULT"]
                else:
                    return []
            else:  # Errors including 401, 403, 5xx
                self.update_notification(f"[{username}] فشل جلب العمليات ({r.status_code}). النص: {r.text[:200]}",
                                         "red")
                return None
        except requests.exceptions.RequestException as e:
            self.update_notification(f"[{username}] خطأ شبكة أثناء جلب العمليات: {type(e).__name__}", "red")
            return None
        except Exception as e:  # Includes JSONDecodeError
            self.update_notification(f"[{username}] خطأ غير متوقع أثناء جلب العمليات: {e}", "red")
            return None

    def _create_account_ui(self, user, processes_data):
        # ... (نفس الكود بدون تغيير)
        account_frame = tk.Frame(self.accounts_frame, bd=2, relief="groove")
        account_frame.pack(fill=tk.X, padx=5, pady=5)
        tk.Label(account_frame, text=f"الحساب: {user}", anchor="e", font=("Helvetica", 11, "bold")).pack(fill=tk.X,
                                                                                                         padx=5,
                                                                                                         pady=(2, 4))
        processes_frame = tk.Frame(account_frame)
        processes_frame.pack(fill=tk.X, padx=5, pady=(0, 5))
        if not processes_data:
            tk.Label(processes_frame, text="لا توجد عمليات متاحة لهذا الحساب حالياً.", fg="grey").pack(pady=5)
            return
        for proc in processes_data:
            pid = proc.get("PROCESS_ID")
            name = proc.get("ZCENTER_NAME", f"عملية {pid}")
            if pid is None: continue
            sub_frame = tk.Frame(processes_frame)
            sub_frame.pack(fill=tk.X, padx=5, pady=2)
            prog = ttk.Progressbar(sub_frame, mode='indeterminate')
            btn = tk.Button(sub_frame, text=name, width=25, state=tk.NORMAL)
            btn.pack(side=tk.RIGHT)
            command_lambda = lambda u=user, p=pid, pr=prog, clicked_btn=btn: threading.Thread(
                target=self._handle_captcha_request, args=(u, p, pr, clicked_btn), daemon=True
            ).start()
            btn.config(command=command_lambda)

    def _handle_captcha_request(self, user, pid, prog_bar, clicked_btn):
        try:
            if clicked_btn.winfo_exists():
                prog_bar.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True, before=clicked_btn)
                prog_bar.start(10)
            else:
                return
        except tk.TclError:
            return

        self.update_notification(f"[{user}] جارٍ طلب كابتشا للعملية '{pid}'...", "grey")
        captcha_data = None
        try:
            if user not in self.accounts or 'session' not in self.accounts[user]:
                raise ValueError(f"معلومات جلسة الحساب {user} غير موجودة.")
            session = self.accounts[user]["session"]
            captcha_data = self.get_captcha(session, pid, user)
        except Exception as e:
            self.update_notification(f"[{user}] خطأ فادح أثناء تحضير/طلب الكابتشا: {e}", "red")
        finally:
            try:
                if prog_bar.winfo_exists():
                    prog_bar.stop();
                    prog_bar.pack_forget()
            except tk.TclError:
                pass

        if captcha_data:
            # --- التغيير الرئيسي هنا ---
            # معالجة الكابتشا الجديدة مباشرة، حتى لو كانت هناك واحدة سابقة.
            self.update_notification(f"[{user}] كابتشا جديدة مستلمة لـ {pid}. سيتم معالجتها الآن.", "cyan")

            # مسح أي عرض كابتشا قديم فوراً.
            # هذا سيؤثر على self.current_captcha_frame
            self.clear_current_captcha_display()

            # تسجيل هذه الكابتشا الجديدة (user, pid) كالحالية التي نعمل عليها
            self.current_captcha = (user, pid)

            # استدعاء دالة العرض والمعالجة مع بيانات المهمة الحالية
            self.show_and_process_captcha(captcha_data, user, pid)

    def get_captcha(self, session, pid, user):
        url = f"https://api.ecsc.gov.sy:8443/captcha/get/{pid}"
        # لا توجد حاجة لـ max_request_retries أو request_attempts الآن
        # max_login_retries يمكن الاحتفاظ بها إذا أردت محاولة تسجيل الدخول مرة واحدة عند الخطأ 401/403
        # login_attempts = 0 # لم يعد ضرورياً بهذه الطريقة

        # محاولة واحدة لجلب الكابتشا
        try:
            self.update_notification(f"[{user}] محاولة جلب الكابتشا لـ PID {pid} (محاولة وحيدة).", "grey")
            r = session.get(url, timeout=(15, 30))

            if r.status_code == 200:
                captcha_info = r.json()
                if "file" in captcha_info and captcha_info["file"]:
                    self.update_notification(f"[{user}] تم جلب الكابتشا بنجاح لـ PID {pid}.", "green")
                    return captcha_info["file"]
                else:
                    self.update_notification(
                        f"[{user}] استجابة الكابتشا (PID: {pid}) لا تحتوي على ملف (200 OK). النص: {r.text[:200]}",
                        "orange")
                    return None  # فشل جلب الكابتشا (لا يوجد ملف)
            elif r.status_code in (401, 403):  # خطأ صلاحية
                self.update_notification(
                    f"[{user}] خطأ صلاحية ({r.status_code}) عند طلب كابتشا لـ PID {pid}. النص: {r.text[:200]}. سيتم محاولة إعادة تسجيل الدخول مرة واحدة.",
                    "orange")
                # محاولة إعادة تسجيل الدخول مرة واحدة. دالة login لديها منطق إعادة المحاولة الخاص بها (retries=2)
                if self.accounts[user].get("password"):  # التأكد من وجود كلمة مرور
                    if self.login(user, self.accounts[user]["password"], session):
                        self.update_notification(
                            f"[{user}] تم إعادة تسجيل الدخول بنجاح بعد خطأ الصلاحية. لن يتم إعادة محاولة جلب الكابتشا تلقائياً في هذه الدالة.",
                            "blue")
                        # بعد إعادة تسجيل الدخول الناجحة، لا نعيد محاولة جلب الكابتشا تلقائيًا هنا.
                        # الاستدعاء الأصلي لـ get_captcha قد فشل.
                        return None
                    else:
                        self.update_notification(f"[{user}] فشلت محاولة إعادة تسجيل الدخول بعد خطأ الصلاحية.", "red")
                        return None  # فشلت إعادة تسجيل الدخول
                else:
                    self.update_notification(
                        f"[{user}] لا يمكن محاولة إعادة تسجيل الدخول لـ {user}، كلمة المرور غير متوفرة.", "red")
                    return None
            else:  # أخطاء أخرى من الخادم (500, 5xx, etc.)
                self.update_notification(
                    f"[{user}] خطأ سيرفر ({r.status_code}) عند طلب كابتشا لـ PID {pid}. النص: {r.text[:200]}", "red")
                return None  # فشل جلب الكابتشا (خطأ سيرفر)

        except requests.exceptions.RequestException as e:
            self.update_notification(f"[{user}] خطأ شبكة ({type(e).__name__}) عند طلب كابتشا لـ PID {pid}.", "red")
            if isinstance(e, requests.exceptions.ProxyError):
                self.update_notification(f"[{user}] خطأ بروكسي محدد ({type(e).__name__}) عند طلب كابتشا لـ PID {pid}.",
                                         "red")
            return None  # فشل جلب الكابتشا (خطأ شبكة)
        except Exception as e:  # Includes JSONDecodeError
            self.update_notification(f"[{user}] خطأ غير متوقع عند طلب كابتشا لـ PID {pid}: {e}", "red")
            return None  # فشل جلب الكابتشا (خطأ غير متوقع)

        # نظريًا، يجب أن يتم الوصول إلى أحد مسارات الإرجاع أعلاه.
        # هذا الإرجاع هنا كإجراء احتياطي.
        # self.update_notification(f"[{user}] فشل الحصول على الكابتشا لـ PID {pid} في المحاولة الوحيدة (مسار احتياطي).", "red")
        # return None

    def predict_captcha(self, pil_image):
        # ... (نفس الكود بدون تغيير)
        preprocess = preprocess_for_model()
        img_rgb = pil_image.convert("RGB")
        start_preprocess = time.time()
        try:
            input_tensor = preprocess(img_rgb).unsqueeze(0).numpy().astype(np.float32)
        except Exception as e:
            return "preprocess_err", 0, 0
        end_preprocess = time.time()
        start_predict = time.time()
        predicted_text = "error"
        try:
            input_name = self.session.get_inputs()[0].name
            ort_inputs = {input_name: input_tensor}
            ort_outs = self.session.run(None, ort_inputs)[0]
            expected_elements = NUM_POS * NUM_CLASSES
            if len(ort_outs.shape) < 2 or ort_outs.shape[0] != 1 or ort_outs.shape[1] < expected_elements:
                raise ValueError(f"شكل مخرجات النموذج غير متوقع: {ort_outs.shape}.")
            ort_outs_trimmed = ort_outs[:, :expected_elements]
            ort_outs_reshaped = ort_outs_trimmed.reshape(1, NUM_POS, NUM_CLASSES)
            predicted_indices = np.argmax(ort_outs_reshaped, axis=2)[0]
            predicted_text = ''.join(IDX2CHAR[i] for i in predicted_indices if i in IDX2CHAR)
        except Exception as e:  # Catches IndexError, ValueError, ONNX errors
            print(f"خطأ أثناء التنبؤ بالكابتشا: {e}")
            predicted_text = "predict_err"  # رمز خطأ عام للتنبؤ
        end_predict = time.time()
        return predicted_text, (end_preprocess - start_preprocess) * 1000, (end_predict - start_predict) * 1000

    def clear_current_captcha_display(self):
        """مسح إطار عرض الكابتشا الرئيسي الحالي (self.current_captcha_frame) فورًا إذا كان موجودًا."""
        frame_to_destroy = self.current_captcha_frame
        if frame_to_destroy and frame_to_destroy.winfo_exists():
            try:
                frame_to_destroy.destroy()
            except tk.TclError:
                pass  # قد يكون الإطار دمر بالفعل
        self.current_captcha_frame = None  # تأكد من إزالة المرجع

    def clear_specific_frame(self, frame_to_clear):
        """مسح إطار محدد إذا كان موجودًا."""
        if frame_to_clear and frame_to_clear.winfo_exists():
            try:
                frame_to_clear.destroy()
            except tk.TclError:
                pass

    def show_and_process_captcha(self, base64_data, task_user, task_pid):
        # عند هذه النقطة، _handle_captcha_request قد قام بتعيين self.current_captcha = (task_user, task_pid)
        # وقام بمسح self.current_captcha_frame القديم.

        # 1. إنشاء إطار جديد لهذه المهمة الحالية وتخزين مرجعه في self.current_captcha_frame
        current_display_frame = tk.Frame(self.accounts_frame, bd=2, relief="sunken")
        current_display_frame._is_captcha_frame = True  # علامة للتعرف عليه
        current_display_frame.pack(pady=10, padx=5, fill=tk.X, side=tk.BOTTOM)
        self.current_captcha_frame = current_display_frame  # تعيين الإطار الحالي الرئيسي

        try:
            # === فك ترميز Base64 وفتح GIF ===
            if "," in base64_data:
                b64 = base64_data.split(",", 1)[1]
            else:
                b64 = base64_data
            raw = base64.b64decode(b64)
            pil = Image.open(io.BytesIO(raw))

            # === استخراج الإطارات وتجميعها في مصفوفة ===
            frames = []
            try:
                pil.seek(0)
                while True:
                    # نحول كل إطار إلى RGB ثم إلى مصفوفة float32
                    arr = np.array(pil.convert("RGB"), dtype=np.float32)
                    frames.append(arr)
                    pil.seek(pil.tell() + 1)
            except EOFError:
                pass

            if not frames:
                raise ValueError("لم يتم قراءة أي إطارات من بيانات الصورة.")

            stack = np.stack(frames, axis=0)  # (n_frames, H, W, 3)

            # === Sum Projection: جمع البكسل عبر الإطارات ===
            summed = np.sum(stack, axis=0)  # (H, W, 3)

            # === معايرة النطاق إلى [0–255] ===
            summed_clipped = np.clip(summed / summed.max() * 255.0, 0, 255).astype(np.uint8)

            # === تحويل إلى رمادي ===
            gray_pil = Image.fromarray(summed_clipped).convert("L")

            # === ضبط التباين تلقائياً ===
            auto = ImageOps.autocontrast(gray_pil, cutoff=1)

            # === معادلة التوزيع اللوني ===
            equalized = ImageOps.equalize(auto)

            # === تحويل ثنائي بعتبة 128 ===
            binary = equalized.point(lambda p: 255 if p > 128 else 0)
            processed_pil_image = binary  # هذه هي الصورة النهائية المعالجة

            # --- نهاية معالجة الصورة ---

            # 2. التنبؤ بالكابتشا وقياس الزمن
            predicted_solution, preprocess_ms, predict_ms = self.predict_captcha(processed_pil_image)

            # 3. التحقق من أنّ هذه المهمة لا تزال «الحالية»
            if self.current_captcha != (task_user, task_pid) or \
                    not current_display_frame.winfo_exists() or \
                    self.current_captcha_frame != current_display_frame:
                self.update_notification(
                    f"[{task_user}] تم إلغاء معالجة الكابتشا لـ {task_pid} بواسطة طلب أحدث.",
                    "orange"
                )
                self.clear_specific_frame(current_display_frame)
                return

            # 4. عرض النتائج في الواجهة
            self.update_notification(
                f"[{task_user}] النص المتوقع للكابتشا (PID: {task_pid}): {predicted_solution}",
                "blue"
            )
            if self.speed_label.winfo_exists():
                self.speed_label.config(
                    text=f"معالجة أولية: {preprocess_ms:.1f} ms | التنبؤ: {predict_ms:.1f} ms"
                )

            # 5. تحجيم الصورة وعرضها
            display_image = processed_pil_image.resize((180, 70), Image.Resampling.LANCZOS)
            tk_image = ImageTk.PhotoImage(display_image)
            img_label = tk.Label(current_display_frame, image=tk_image)
            img_label.image = tk_image
            img_label.pack(pady=5)

            # 6. عرض النص المتوقع
            prediction_label = tk.Label(
                current_display_frame,
                text=f"الحل المتوقع: {predicted_solution}",
                font=("Helvetica", 12, "bold")
            )
            prediction_label.pack(pady=(0, 5))

            # 7. إرسال النتيجة أو التعامل مع الأخطاء
            if predicted_solution not in [
                "error", "preprocess_err", "predict_err",
                "shape_err", "decode_err", "onnx_err"
            ]:
                threading.Thread(
                    target=self.submit_captcha_solution,
                    args=(task_user, task_pid, predicted_solution, current_display_frame),
                    daemon=True
                ).start()
            else:
                err_msg = f"خطأ في التنبؤ: {predicted_solution}"
                self.show_submission_result_in_frame(
                    current_display_frame,
                    task_user, task_pid, -1, err_msg, False
                )
                if self.current_captcha == (task_user, task_pid):
                    self.current_captcha = None
                # إبقاء الخطأ معلناً قليلاً ثم تنظيف الإطار
                self.root.after(
                    2000,
                    lambda frame=current_display_frame: self.clear_specific_frame(frame)
                )

        except Exception as e:
            # معالجة الأخطاء النهائية
            self.update_notification(
                f"[{task_user}] خطأ أثناء عرض/معالجة الكابتشا لـ {task_pid}: {e}", "red"
            )
            if self.current_captcha == (task_user, task_pid):
                self.current_captcha = None

            if current_display_frame.winfo_exists():
                self.show_submission_result_in_frame(
                    current_display_frame,
                    task_user, task_pid, -2,
                    f"خطأ معالجة: {e}", False
                )
                self.root.after(
                    2000,
                    lambda frame=current_display_frame: self.clear_specific_frame(frame)
                )

            if self.current_captcha_frame == current_display_frame:
                self.current_captcha_frame = None

    def submit_captcha_solution(self, task_user, task_pid, solution, display_frame_for_this_task):
        # تعمل هذه الدالة على بيانات مهمة محددة وإطارها المخصص.

        # التحقق مما إذا كانت هذه المهمة لا تزال هي "الحالية" وفقًا للمنطق الرئيسي للتطبيق.
        # هذا مفيد للتسجيل ولتحديد ما إذا كان يجب مسح self.current_captcha.
        is_still_globally_current_task = (self.current_captcha == (task_user, task_pid))

        if task_user not in self.accounts or "session" not in self.accounts[task_user]:
            self.update_notification(
                f"[{task_user}] لا يمكن إرسال الحل لـ PID {task_pid}، معلومات الحساب/الجلسة غير موجودة.", "red")
            if is_still_globally_current_task:  # إذا كانت هذه هي المهمة الحالية الرئيسية
                self.current_captcha = None
            self.clear_specific_frame(display_frame_for_this_task)  # مسح إطار هذه المهمة
            return

        session = self.accounts[task_user]["session"]
        url = f"https://api.ecsc.gov.sy:8443/rs/reserve?id={task_pid}&captcha={solution}"
        self.update_notification(f"[{task_user}] جارٍ إرسال الحل '{solution}' للعملية (PID: {task_pid})...", "blue")
        response_text = "لم يتم استلام استجابة"
        status_code = -1
        success = False
        try:
            r = session.get(url, timeout=(10, 45))
            response_text = r.text;
            status_code = r.status_code
            if status_code == 200: success = True
            # (تحديث الإشعارات بناءً على status_code ونص الاستجابة)
            self.update_notification(
                f"[{task_user}] استجابة الإرسال لـ PID {task_pid} (الحالة: {status_code}): {response_text[:150]}...",
                "green" if success else "red")

        except requests.exceptions.RequestException as e:
            response_text = f"خطأ شبكة: {type(e).__name__}"
            self.update_notification(f"[{task_user}] خطأ شبكة ({type(e).__name__}) أثناء إرسال الحل لـ PID {task_pid}.",
                                     "red")
        except Exception as e:
            response_text = f"خطأ غير متوقع: {e}"
            self.update_notification(f"[{task_user}] خطأ غير متوقع أثناء إرسال الحل لـ PID {task_pid}: {e}", "red")
        finally:
            # انتهت هذه المهمة (الإرسال).
            if is_still_globally_current_task and self.current_captcha == (task_user, task_pid):
                self.current_captcha = None  # لم تعد هناك مهمة "رئيسية" نشطة بعد هذا الإرسال

            # عرض النتيجة في الإطار الخاص بهذه المهمة
            if display_frame_for_this_task.winfo_exists():  # تأكد من أن الإطار لا يزال موجوداً
                self.root.after(0, lambda: self.show_submission_result_in_frame(
                    display_frame_for_this_task, task_user, task_pid, status_code, response_text, success
                ))
                # جدولة مسح الإطار الخاص بهذه المهمة بعد فترة لرؤية النتيجة
                self.root.after(3000, lambda frame=display_frame_for_this_task: self.clear_specific_frame(
                    frame))  # تأخير أطول لرؤية النتيجة
            elif is_still_globally_current_task and self.current_captcha_frame == display_frame_for_this_task:
                # إذا تم تدمير الإطار ولكن كان لا يزال هو الإطار الرئيسي المشار إليه
                self.current_captcha_frame = None

    def show_submission_result_in_frame(self, display_frame, user, pid, status_code, response_text, success):
        # ... (نفس الكود بدون تغيير جوهري، لكن تأكد من أنه يعمل مع display_frame الممرر) ...
        if not display_frame or not display_frame.winfo_exists():
            # self.update_notification(f"[{user}] حاول عرض نتيجة الإرسال لـ PID {pid} ولكن الإطار لم يعد موجوداً.", "orange")
            return
        result_message = f"[{user} | PID: {pid}] "
        color = "black"
        full_response_display = f" (الحالة: {status_code}, النص: {response_text[:250]})"
        if success:
            if "نجاح" in response_text or "success" in response_text.lower() or "تم الحجز" in response_text:
                result_message += f"نجاح!{full_response_display}";
                color = "green"
            elif "خطأ" in response_text or "incorrect" in response_text.lower() or "failed" in response_text.lower() or "غير صحيح" in response_text:
                result_message += f"فشل: حل خاطئ أو انتهت العملية.{full_response_display}";
                color = "orange"
            else:
                result_message += f"تم الإرسال (200).{full_response_display}";
                color = "blue"
        elif status_code == 400:
            result_message += f"فشل (400): طلب غير صالح.{full_response_display}"; color = "red"
        elif status_code in (401, 403):
            result_message += f"فشل ({status_code}): خطأ صلاحية.{full_response_display}"; color = "red"
        elif status_code < 0:
            result_message += f"خطأ داخلي ({status_code}): {response_text}"; color = "red"
        else:
            result_message += f"فشل ({status_code}).{full_response_display}"; color = "red"
        try:
            result_label = None
            for widget in display_frame.winfo_children():
                if isinstance(widget, tk.Label) and hasattr(widget, '_is_result_label') and widget._is_result_label:
                    result_label = widget;
                    break
            if result_label:
                result_label.config(text=result_message, fg=color)
            else:
                result_label = tk.Label(display_frame, text=result_message, fg=color, font=("Helvetica", 10),
                                        wraplength=max(200, display_frame.winfo_width() - 20))
                result_label._is_result_label = True
                result_label.pack(pady=(5, 5), fill=tk.X, side=tk.BOTTOM, expand=True)
        except tk.TclError:
            pass  # قد يتم تدمير الإطار
        except Exception as e:
            print(f"[{user}] خطأ عام أثناء عرض نتيجة الإرسال في الإطار لـ PID {pid}: {e}")


if __name__ == "__main__":
    try:
        requests.packages.urllib3.disable_warnings()
        root = tk.Tk()
        # root.geometry("700x600") # يمكنك تحديد حجم النافذة
        app = CaptchaApp(root)
        if hasattr(app, 'session') and app.session is not None:
            root.mainloop()
        else:
            if root.winfo_exists(): root.destroy()
    except ImportError as e:
        print(f"خطأ: لم يتم العثور على مكتبة مطلوبة: {e.name}. يرجى تثبيتها.")
    except Exception as e:
        import traceback

        print(f"\n--- حدث خطأ غير متوقع في المستوى الأعلى ---\n{traceback.format_exc()}")
