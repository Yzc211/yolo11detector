# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, session
from ultralytics import YOLO
import os
from datetime import datetime
from werkzeug.utils import secure_filename
import json
import shutil
from functools import wraps

# === 基本路径配置 ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_FOLDER = BASE_DIR  # 把 demo 目录当作模板目录
STATIC_FOLDER = os.path.join(BASE_DIR, "static")
RESULT_FOLDER = os.path.join(STATIC_FOLDER, "results")
MODELS_DIR = os.path.join(BASE_DIR, "models")
MODEL_CONFIG = os.path.join(BASE_DIR, "model_config.json")

os.makedirs(RESULT_FOLDER, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(STATIC_FOLDER, exist_ok=True)

# === Flask app ===
app = Flask(__name__, template_folder=TEMPLATES_FOLDER, static_folder=STATIC_FOLDER)
# IMPORTANT: 在真实部署时用更复杂的 secret_key 并保护好
app.secret_key = "change-this-secret-to-a-random-value"

# === Allowed image extensions ===
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif"}

# === Model holder ===
model = None
active_model = None

# === 静态用户（示例）===
USERS = {
    "user": {"password": "user123", "role": "user"},
    "admin": {"password": "admin123", "role": "admin"}
}

def _save_model_config(model_filename):
    with open(MODEL_CONFIG, "w", encoding="utf-8") as f:
        json.dump({"active_model": model_filename}, f)

def _load_model_config():
    if os.path.exists(MODEL_CONFIG):
        try:
            with open(MODEL_CONFIG, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("active_model")
        except Exception:
            return None
    return None

def load_model(model_path):
    global model, active_model
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"模型文件不存在: {model_path}")
    # 使用绝对路径加载模型
    model = YOLO(model_path)
    active_model = os.path.basename(model_path)
    _save_model_config(active_model)
    print(f"[INFO] 已加载模型: {model_path}")

# 复制仓库根目录下的默认模型到 models 目录（如存在）
default_pt = os.path.join(BASE_DIR, "yolo11n.pt")
if os.path.exists(default_pt):
    target_default = os.path.join(MODELS_DIR, "yolo11n.pt")
    if not os.path.exists(target_default):
        try:
            shutil.copyfile(default_pt, target_default)
        except Exception as e:
            print(f"[WARN] 无法复制默认模型: {e}")

# 初始化加载模型（优先配置指定的）
configured = _load_model_config()
if configured and os.path.exists(os.path.join(MODELS_DIR, configured)):
    try:
        load_model(os.path.join(MODELS_DIR, configured))
    except Exception as e:
        print(f"[WARN] 加载配置模型失败: {e}")
        model = None
else:
    model_files = [f for f in os.listdir(MODELS_DIR) if f.endswith(".pt")]
    if model_files:
        try:
            load_model(os.path.join(MODELS_DIR, model_files[0]))
        except Exception as e:
            print(f"[WARN] 初始化加载模型失败: {e}")
            model = None
    else:
        print("[WARN] models 目录为空，请上传 .pt 模型或将 yolo11n.pt 放到 demo/models/ 目录。")

def allowed_file(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS

# === 认证装饰器 ===
def login_required(view):
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"error": "未登录"}), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped

def admin_required(view):
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login", next=request.path))
        if session.get("role") != "admin":
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"error": "需要管理员权限"}), 403
            return "需要管理员权限", 403
        return view(*args, **kwargs)
    return wrapped

# --- 路由: 登录 / 登出 ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        if "username" in session:
            return redirect(url_for("index"))
        next_path = request.args.get("next", "/")
        return render_template("login.html", next=next_path)
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    next_path = request.form.get("next", "/")
    user = USERS.get(username)
    if not user or user.get("password") != password:
        return render_template("login.html", error="用户名或密码错误", next=next_path)
    session["username"] = username
    session["role"] = user.get("role", "user")
    return redirect(next_path or url_for("index"))

@app.route('/logout')
def logout():
    session.pop("username", None)
    session.pop("role", None)
    return redirect(url_for("login"))

# 首页（检测页面），需要登录
@app.route('/')
@login_required
def index():
    return render_template("detect.html")

# 管理页（需要管理员）
@app.route('/admin')
@admin_required
def admin():
    return render_template("admin.html")

# 上传图片（单张/多张/文件夹内多张）并批量推理（登录用户可用）
@app.route('/upload_images', methods=['POST'])
@login_required
def upload_images():
    if model is None:
        return jsonify({"error": "当前没有加载任何模型，请联系管理员或上传模型。"}), 500

    files = request.files.getlist("files")
    if not files:
        files = request.files.getlist("files[]")
    if not files:
        return jsonify({"error": "没有收到任何文件"}), 400

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_folder = os.path.join(RESULT_FOLDER, timestamp)
    os.makedirs(out_folder, exist_ok=True)

    results_urls = []

    for f in files:
        filename = secure_filename(f.filename)
        if filename == "":
            continue
        if not allowed_file(filename):
            continue
        save_path = os.path.join(out_folder, filename)
        f.save(save_path)

        try:
            # 记录当前目录中文件，推理并保存后只收集新增的文件（避免返回原图）
            before_files = set(os.listdir(out_folder))
            cwd_before = os.getcwd()
            os.chdir(out_folder)
            res = model(save_path)
            res[0].save()
            os.chdir(cwd_before)
            after_files = set(os.listdir(out_folder))
            new_files = after_files - before_files
            for nf in new_files:
                if os.path.splitext(nf)[1].lower() in ALLOWED_EXTENSIONS:
                    rel_path = os.path.relpath(os.path.join(out_folder, nf), RESULT_FOLDER)
                    url = "/results/" + rel_path.replace("\\", "/")
                    results_urls.append(url)
        except Exception as e:
            try:
                os.chdir(cwd_before)
            except:
                pass
            # 继续处理其他文件
            continue

    return jsonify({
        "message": "推理完成",
        "timestamp": timestamp,
        "results": results_urls
    })

# 允许前端直接发送服务器上已有路径进行推理（登录用户可用）
@app.route('/run_yolo_path', methods=['POST'])
@login_required
def run_yolo_path():
    if model is None:
        return jsonify({"error": "当前没有加载任何模型，请联系管理员或上传模型。"}), 500

    data = request.get_json()
    image_path = data.get('image_path')
    if not image_path or not os.path.exists(image_path):
        return jsonify({"error": f"找不到图片路径: {image_path}"}), 400

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_folder = os.path.join(RESULT_FOLDER, timestamp)
    os.makedirs(out_folder, exist_ok=True)

    try:
        before_files = set(os.listdir(out_folder))
        cwd_before = os.getcwd()
        os.chdir(out_folder)
        results = model(image_path)
        results[0].save()
        os.chdir(cwd_before)
        after_files = set(os.listdir(out_folder))
        new_files = after_files - before_files
        results_urls = []
        for nf in new_files:
            if os.path.splitext(nf)[1].lower() in ALLOWED_EXTENSIONS:
                rel_path = os.path.relpath(os.path.join(out_folder, nf), RESULT_FOLDER)
                url = "/results/" + rel_path.replace("\\", "/")
                results_urls.append(url)
    except Exception as e:
        try:
            os.chdir(cwd_before)
        except:
            pass
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "message": "YOLO 推理完成",
        "input_image": image_path,
        "results": results_urls
    })

# 提供保存的结果文件访问（登录用户可用）
@app.route('/results/<path:filename>')
@login_required
def serve_results(filename):
    return send_from_directory(RESULT_FOLDER, filename)

# 管理员：列出模型、上传新模型、设置当前模型
@app.route('/models', methods=['GET'])
@admin_required
def list_models():
    files = [f for f in os.listdir(MODELS_DIR) if f.endswith(".pt")]
    return jsonify({
        "models": files,
        "active": active_model
    })

@app.route('/models/upload', methods=['POST'])
@admin_required
def upload_model():
    f = request.files.get("model")
    if not f:
        return jsonify({"error": "没有收到模型文件"}), 400
    filename = secure_filename(f.filename)
    if not filename.endswith(".pt"):
        return jsonify({"error": "只允许上传 .pt 文件"}), 400
    target = os.path.join(MODELS_DIR, filename)
    f.save(target)
    try:
        load_model(target)
    except Exception as e:
        return jsonify({"error": f"保存成功但加载模型失败: {e}"}), 500
    return jsonify({"message": "模型上传并加载成功", "active": active_model})

@app.route('/models/set', methods=['POST'])
@admin_required
def set_model():
    data = request.get_json()
    model_name = data.get("model")
    if not model_name:
        return jsonify({"error": "未指定 model 参数"}), 400
    target = os.path.join(MODELS_DIR, model_name)
    if not os.path.exists(target):
        return jsonify({"error": "指定的模型文件不存在"}), 404
    try:
        load_model(target)
    except Exception as e:
        return jsonify({"error": f"加载模型失败: {e}"}), 500
    return jsonify({"message": "已切换模型", "active": active_model})

# 后端静态文件访问（保留）
@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory(BASE_DIR, filename)

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)