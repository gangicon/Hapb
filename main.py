# -*- coding: utf-8 -*-
import os
import re
import threading
import time
import base64
import io
import random
import requests
import urllib3
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox

try:
    from PIL import Image, ImageTk, UnidentifiedImageError, ImageOps, ImageEnhance
except ImportError:
    print("خطأ: مكتبة Pillow (PIL) غير مثبتة. يرجى تثبيتها باستخدام: pip install Pillow")
    exit()
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
ONNX_MODEL_URL = "http://kadolak.pythonanywhere.com/download-model/"


def preprocess_for_model():
    return transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.Grayscale(num_output_channels=3),
        transforms.ToTensor(),
        transforms.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5]),
    ])


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class CaptchaApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Captcha Solver (ONNX Runtime) - v1.9 (Remote Hardware)")
        self.device = 'cpu'
        self.session = None

        self.accounts = {}
        self.current_captcha = None
        self.current_captcha_frame = None

        self.notification_label = None
        self.speed_label = None
        self.accounts_frame = None
        self.loading_progress = None
        self.add_account_button = None
        self.retry_button = None

        self._build_gui()

        threading.Thread(target=self._load_model_threaded, daemon=True).start()

    def _build_gui(self):
        self.settings_frame = tk.Frame(self.root)
        self.settings_frame.pack(padx=10, pady=10, fill=tk.X)

        # --- تغيير المصطلح ---
        self.notification_label = tk.Label(self.settings_frame, text="مرحباً! جارٍ تركيب العتاد...",
                                           font=("Helvetica", 10), justify=tk.RIGHT, fg="blue")
        self.notification_label.pack(pady=5, fill=tk.X)

        self.add_account_button = tk.Button(self.settings_frame, text="إضافة حساب", command=self.add_account, width=15,
                                            state=tk.DISABLED)
        self.add_account_button.pack(pady=5)

        self.accounts_frame = tk.Frame(self.root, bd=1, relief="solid")
        self.accounts_frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        self.speed_label = tk.Label(self.root, text="المعالجة الأولية: - | التنبؤ: -", font=("Helvetica", 9))
        self.speed_label.pack(side=tk.BOTTOM, pady=(0, 5))

        self.loading_progress = ttk.Progressbar(self.settings_frame, mode='determinate', orient="horizontal",
                                                length=200)
        self.loading_progress.pack(pady=5, fill=tk.X)

    def _retry_load_model(self):
        if self.retry_button and self.retry_button.winfo_exists():
            self.retry_button.destroy()
            self.retry_button = None

        if self.loading_progress and not self.loading_progress.winfo_exists():
            self.loading_progress.pack(pady=5, fill=tk.X)

        threading.Thread(target=self._load_model_threaded, daemon=True).start()

    def _load_model_threaded(self):
        try:
            # --- تغيير المصطلح ---
            self.root.after(0, self.update_notification, "جارٍ تركيب العتاد من الخادم... قد يستغرق بعض الوقت.", "blue")

            response = requests.get(ONNX_MODEL_URL, stream=True, timeout=60)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            bytes_so_far = 0
            model_data = b''

            for chunk in response.iter_content(chunk_size=4096):
                model_data += chunk
                bytes_so_far += len(chunk)
                if total_size > 0:
                    percent = (bytes_so_far / total_size) * 100
                    self.root.after(0, lambda p=percent: self.loading_progress.config(value=p))
                    # --- تغيير المصطلح ---
                    self.root.after(0, self.update_notification, f"جارٍ تركيب العتاد: {percent:.1f}%", "blue")

            provider_to_use = ['CPUExecutionProvider']
            self.session = ort.InferenceSession(model_data, providers=provider_to_use)

            self.root.after(0, self._on_model_loaded_success)

        except requests.exceptions.RequestException:
            # --- معالجة خطأ انقطاع الإنترنت ---
            self.root.after(0, self._handle_network_error)

        except Exception as e:
            # --- تغيير المصطلح ---
            self.root.after(0, self._on_model_loaded_failure, f"خطأ في تهيئة العتاد: {e}")

    def _handle_network_error(self):
        if self.loading_progress and self.loading_progress.winfo_exists():
            self.loading_progress.pack_forget()

        # --- تغيير رسالة الخطأ ---
        self.update_notification("الرجاء تشغيل الإنترنت لتحميل وتركيب العتاد.", "red")

        if not self.retry_button or not self.retry_button.winfo_exists():
            self.retry_button = tk.Button(self.settings_frame, text="إعادة المحاولة", command=self._retry_load_model)
            self.retry_button.pack(pady=5)

    def _on_model_loaded_success(self):
        if self.loading_progress and self.loading_progress.winfo_exists():
            self.loading_progress.pack_forget()
        # --- تغيير المصطلح ---
        self.update_notification("تم تركيب العتاد بنجاح. يمكنك الآن إضافة حساب.", "green")
        if self.add_account_button and self.add_account_button.winfo_exists():
            self.add_account_button.config(state=tk.NORMAL)

    def _on_model_loaded_failure(self, error_message):
        if self.loading_progress and self.loading_progress.winfo_exists():
            self.loading_progress.pack_forget()
        # --- تغيير المصطلح ---
        self.update_notification(f"فشل تركيب العتاد. {error_message}", "red")
        messagebox.showerror("خطأ في التحميل", f"فشل تحميل أو تهيئة العتاد.\nالخطأ: {error_message}", parent=self.root)
        self.root.quit()

    def update_notification(self, message, color="black"):
        if self.notification_label and self.notification_label.winfo_exists():
            self.notification_label.config(text=message, fg=color)
        print(f"[{time.strftime('%H:%M:%S')}] [{color.upper()}] {message}")

    def generate_user_agent(self):
        ua_list = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        ]
        return random.choice(ua_list)

    def create_session(self, user_agent):
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
        return session

    def login(self, username, password, session, retries=2):
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
            else:
                self.update_notification(f"[{username}] فشل جلب العمليات ({r.status_code}). النص: {r.text[:200]}",
                                         "red")
                return None
        except requests.exceptions.RequestException as e:
            self.update_notification(f"[{username}] خطأ شبكة أثناء جلب العمليات: {type(e).__name__}", "red")
            return None
        except Exception as e:
            self.update_notification(f"[{username}] خطأ غير متوقع أثناء جلب العمليات: {e}", "red")
            return None

    def _create_account_ui(self, user, processes_data):
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
            self.update_notification(f"[{user}] كابتشا جديدة مستلمة لـ {pid}. سيتم معالجتها الآن.", "cyan")
            self.clear_current_captcha_display()
            self.current_captcha = (user, pid)
            self.show_and_process_captcha(captcha_data, user, pid)

    def get_captcha(self, session, pid, user):
        url = f"https://api.ecsc.gov.sy:8443/captcha/get/{pid}"
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
                    return None
            elif r.status_code in (401, 403):
                self.update_notification(
                    f"[{user}] خطأ صلاحية ({r.status_code}) عند طلب كابتشا لـ PID {pid}. النص: {r.text[:200]}. سيتم محاولة إعادة تسجيل الدخول مرة واحدة.",
                    "orange")
                if self.accounts[user].get("password"):
                    if self.login(user, self.accounts[user]["password"], session):
                        self.update_notification(
                            f"[{user}] تم إعادة تسجيل الدخول بنجاح بعد خطأ الصلاحية. لن يتم إعادة محاولة جلب الكابتشا تلقائياً في هذه الدالة.",
                            "blue")
                        return None
                    else:
                        self.update_notification(f"[{user}] فشلت محاولة إعادة تسجيل الدخول بعد خطأ الصلاحية.", "red")
                        return None
                else:
                    self.update_notification(
                        f"[{user}] لا يمكن محاولة إعادة تسجيل الدخول لـ {user}، كلمة المرور غير متوفرة.", "red")
                    return None
            else:
                self.update_notification(
                    f"[{user}] خطأ سيرفر ({r.status_code}) عند طلب كابتشا لـ PID {pid}. النص: {r.text[:200]}", "red")
                return None
        except requests.exceptions.RequestException as e:
            self.update_notification(f"[{user}] خطأ شبكة ({type(e).__name__}) عند طلب كابتشا لـ PID {pid}.", "red")
            return None
        except Exception as e:
            self.update_notification(f"[{user}] خطأ غير متوقع عند طلب كابتشا لـ PID {pid}: {e}", "red")
            return None

    def predict_captcha(self, pil_image):
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
        except Exception as e:
            print(f"خطأ أثناء التنبؤ بالكابتشا: {e}")
            predicted_text = "predict_err"
        end_predict = time.time()

        random_delay_s = random.uniform(0.030, 0.035)
        time.sleep(random_delay_s)

        preprocess_time_ms = (end_preprocess - start_preprocess) * 1000
        prediction_time_ms = ((end_predict - start_predict) * 1000) + (random_delay_s * 1000)

        return predicted_text, preprocess_time_ms, prediction_time_ms

    def clear_current_captcha_display(self):
        frame_to_destroy = self.current_captcha_frame
        if frame_to_destroy and frame_to_destroy.winfo_exists():
            try:
                frame_to_destroy.destroy()
            except tk.TclError:
                pass
        self.current_captcha_frame = None

    def clear_specific_frame(self, frame_to_clear):
        if frame_to_clear and frame_to_clear.winfo_exists():
            try:
                frame_to_clear.destroy()
            except tk.TclError:
                pass

    def show_and_process_captcha(self, base64_data, task_user, task_pid):
        current_display_frame = tk.Frame(self.accounts_frame, bd=2, relief="sunken")
        current_display_frame._is_captcha_frame = True
        current_display_frame.pack(pady=10, padx=5, fill=tk.X, side=tk.BOTTOM)
        self.current_captcha_frame = current_display_frame

        try:
            if "," in base64_data:
                b64 = base64_data.split(",", 1)[1]
            else:
                b64 = base64_data
            raw = base64.b64decode(b64)
            pil = Image.open(io.BytesIO(raw))

            frames = []
            try:
                pil.seek(0)
                while True:
                    arr = np.array(pil.convert("RGB"), dtype=np.float32)
                    frames.append(arr)
                    pil.seek(pil.tell() + 1)
            except EOFError:
                pass

            if not frames:
                raise ValueError("لم يتم قراءة أي إطارات من بيانات الصورة.")

            stack = np.stack(frames, axis=0)
            summed = np.sum(stack, axis=0)
            summed_clipped = np.clip(summed / summed.max() * 255.0, 0, 255).astype(np.uint8)
            gray_pil = Image.fromarray(summed_clipped).convert("L")
            auto = ImageOps.autocontrast(gray_pil, cutoff=1)
            equalized = ImageOps.equalize(auto)
            binary = equalized.point(lambda p: 255 if p > 128 else 0)
            processed_pil_image = binary

            predicted_solution, preprocess_ms, predict_ms = self.predict_captcha(processed_pil_image)

            if self.current_captcha != (task_user, task_pid) or \
                    not current_display_frame.winfo_exists() or \
                    self.current_captcha_frame != current_display_frame:
                self.update_notification(f"[{task_user}] تم إلغاء معالجة الكابتشا لـ {task_pid} بواسطة طلب أحدث.",
                                         "orange")
                self.clear_specific_frame(current_display_frame)
                return

            self.update_notification(f"[{task_user}] النص المتوقع للكابتشا (PID: {task_pid}): {predicted_solution}",
                                     "blue")
            if self.speed_label.winfo_exists():
                self.speed_label.config(text=f"معالجة أولية: {preprocess_ms:.1f} ms | التنبؤ: {predict_ms:.1f} ms")

            display_image = processed_pil_image.resize((180, 70), Image.Resampling.LANCZOS)
            tk_image = ImageTk.PhotoImage(display_image)
            img_label = tk.Label(current_display_frame, image=tk_image)
            img_label.image = tk_image
            img_label.pack(pady=5)

            prediction_label = tk.Label(current_display_frame, text=f"الحل المتوقع: {predicted_solution}",
                                        font=("Helvetica", 12, "bold"))
            prediction_label.pack(pady=(0, 5))

            if predicted_solution not in ["error", "preprocess_err", "predict_err", "shape_err", "decode_err",
                                          "onnx_err"]:
                threading.Thread(
                    target=self.submit_captcha_solution,
                    args=(task_user, task_pid, predicted_solution, current_display_frame),
                    daemon=True
                ).start()
            else:
                err_msg = f"خطأ في التنبؤ: {predicted_solution}"
                self.show_submission_result_in_frame(current_display_frame, task_user, task_pid, -1, err_msg, False)
                if self.current_captcha == (task_user, task_pid):
                    self.current_captcha = None
                self.root.after(2000, lambda frame=current_display_frame: self.clear_specific_frame(frame))

        except Exception as e:
            self.update_notification(f"[{task_user}] خطأ أثناء عرض/معالجة الكابتشا لـ {task_pid}: {e}", "red")
            if self.current_captcha == (task_user, task_pid):
                self.current_captcha = None

            if current_display_frame.winfo_exists():
                self.show_submission_result_in_frame(current_display_frame, task_user, task_pid, -2, f"خطأ معالجة: {e}",
                                                     False)
                self.root.after(2000, lambda frame=current_display_frame: self.clear_specific_frame(frame))

            if self.current_captcha_frame == current_display_frame:
                self.current_captcha_frame = None

    def submit_captcha_solution(self, task_user, task_pid, solution, display_frame_for_this_task):
        is_still_globally_current_task = (self.current_captcha == (task_user, task_pid))

        if task_user not in self.accounts or "session" not in self.accounts[task_user]:
            self.update_notification(
                f"[{task_user}] لا يمكن إرسال الحل لـ PID {task_pid}، معلومات الحساب/الجلسة غير موجودة.", "red")
            if is_still_globally_current_task:
                self.current_captcha = None
            self.clear_specific_frame(display_frame_for_this_task)
            return

        session = self.accounts[task_user]["session"]
        url = f"https://api.ecsc.gov.sy:8443/rs/reserve?id={task_pid}&captcha={solution}"
        self.update_notification(f"[{task_user}] جارٍ إرسال الحل '{solution}' للعملية (PID: {task_pid})...", "blue")
        response_text = "لم يتم استلام استجابة"
        status_code = -1
        success = False
        try:
            r = session.get(url, timeout=(10, 45))
            response_text = r.text
            status_code = r.status_code
            if status_code == 200: success = True
            self.update_notification(
                f"[{task_user}] استجابة الإرسال لـ PID {task_pid} (الحالة: {status_code}): {response_text[:150]}...",
                "green" if success else "red")

        except requests.exceptions.RequestException as e:
            response_text = f"خطأ شبكة: {type(e).__name__}"
            self.update_notification(f"[{task_user}] خطأ شبكة ({type(e).__name__}) أثناء إرسال الحل لـ PID {task_pid}.",
                                     "red")
        except Exception as e:
            response_text = f"خطأ غير متوقع: {e}"
            self.update_notification(f"[{task_user}] خطأ غير متوقع أثناء إرسال الحل لـ PID {pid}: {e}", "red")
        finally:
            if is_still_globally_current_task and self.current_captcha == (task_user, task_pid):
                self.current_captcha = None

            if display_frame_for_this_task.winfo_exists():
                self.root.after(0, lambda: self.show_submission_result_in_frame(
                    display_frame_for_this_task, task_user, task_pid, status_code, response_text, success
                ))
                self.root.after(3000, lambda frame=display_frame_for_this_task: self.clear_specific_frame(frame))
            elif is_still_globally_current_task and self.current_captcha_frame == display_frame_for_this_task:
                self.current_captcha_frame = None

    def show_submission_result_in_frame(self, display_frame, user, pid, status_code, response_text, success):
        if not display_frame or not display_frame.winfo_exists():
            return
        result_message = f"[{user} | PID: {pid}] "
        color = "black"
        full_response_display = f" (الحالة: {status_code}, النص: {response_text[:250]})"
        if success:
            if "نجاح" in response_text or "success" in response_text.lower() or "تم الحجز" in response_text:
                result_message += f"نجاح!{full_response_display}"
                color = "green"
            elif "خطأ" in response_text or "incorrect" in response_text.lower() or "failed" in response_text.lower() or "غير صحيح" in response_text:
                result_message += f"فشل: حل خاطئ أو انتهت العملية.{full_response_display}"
                color = "orange"
            else:
                result_message += f"تم الإرسال (200).{full_response_display}"
                color = "blue"
        elif status_code == 400:
            result_message += f"فشل (400): طلب غير صالح.{full_response_display}"
            color = "red"
        elif status_code in (401, 403):
            result_message += f"فشل ({status_code}): خطأ صلاحية.{full_response_display}"
            color = "red"
        elif status_code < 0:
            result_message += f"خطأ داخلي ({status_code}): {response_text}"
            color = "red"
        else:
            result_message += f"فشل ({status_code}).{full_response_display}"
            color = "red"
        try:
            result_label = None
            for widget in display_frame.winfo_children():
                if isinstance(widget, tk.Label) and hasattr(widget, '_is_result_label') and widget._is_result_label:
                    result_label = widget
                    break
            if result_label:
                result_label.config(text=result_message, fg=color)
            else:
                result_label = tk.Label(display_frame, text=result_message, fg=color, font=("Helvetica", 10),
                                        wraplength=max(200, display_frame.winfo_width() - 20))
                result_label._is_result_label = True
                result_label.pack(pady=(5, 5), fill=tk.X, side=tk.BOTTOM, expand=True)
        except tk.TclError:
            pass
        except Exception as e:
            print(f"[{user}] خطأ عام أثناء عرض نتيجة الإرسال في الإطار لـ PID {pid}: {e}")


if __name__ == "__main__":
    try:
        requests.packages.urllib3.disable_warnings()
        root = tk.Tk()
        app = CaptchaApp(root)
        root.mainloop()
    except ImportError as e:
        print(f"خطأ: لم يتم العثور على مكتبة مطلوبة: {e.name}. يرجى تثبيتها.")
    except Exception as e:
        import traceback

        print(f"\n--- حدث خطأ غير متوقع في المستوى الأعلى ---\n{traceback.format_exc()}")
