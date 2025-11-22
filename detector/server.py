# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, session
from ultralytics import YOLO
import os
from datetime import datetime
from werkzeug.utils import secure_filename
import json
import shutil
from functools import wraps
import uuid

# === 基本路径配置 ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_FOLDER = BASE_DIR  # 把 demo 目录当作模板目录
STATIC_FOLDER = os.path.join(BASE_DIR, "static")
RESULT_FOLDER = os.path.join(STATIC_FOLDER, "results")   # 保存推理生成的带框图片等结果
MODELS_DIR = os.path.join(BASE_DIR, "models")
MODEL_CONFIG = os.path.join(BASE_DIR, "model_config.json")
UPLOADS_FOLDER = os.path.join(STATIC_FOLDER, "uploads")  # 中央上传目录，用于“已上传图片”栏

# 确保目录存在
os.makedirs(RESULT_FOLDER, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(STATIC_FOLDER, exist_ok=True)
os.makedirs(UPLOADS_FOLDER, exist_ok=True)

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

# ===== 新增：清空上传目录的辅助函数 =====
def clear_uploads():
    """
    清空 UPLOADS_FOLDER 下的所有文件和子目录。
    在每次用户登录后调用，以保证重新登录时“已上传图片”为空。
    """
    try:
        for entry in os.listdir(UPLOADS_FOLDER):
            path = os.path.join(UPLOADS_FOLDER, entry)
            try:
                if os.path.isfile(path) or os.path.islink(path):
                    os.remove(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path)
            except Exception as e:
                # 忽略单个文件删除错误，继续删除其他文件
                print(f"[WARN] 删除上传文件时出错: {path} -> {e}")
    except Exception as e:
        print(f"[WARN] 清空 uploads 目录失败: {e}")

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
    # 登录成功：设置会话
    session["username"] = username
    session["role"] = user.get("role", "user")
    # 在每次成功登录后清空已上传图片目录（保证重新登录后“已上传图片”为空）
    try:
        clear_uploads()
    except Exception as e:
        print(f"[WARN] 登录时清空上传目录出现错误: {e}")
    return redirect(next_path or url_for("index"))

@app.route('/logout')
def logout():
    # 退出时也尝试清空上传目录（额外的清理）
    try:
        clear_uploads()
    except Exception as e:
        print(f"[WARN] 登出时清空上传目录出现错误: {e}")
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

# ===== 辅助工具函数 =====
def make_safe_filename(orig_name: str) -> str:
    """
    将上传时可能包含子文件夹的文件名（比如 webkitRelativePath）
    转换为安全的单一文件名，保留一定的可读性。
    示例："dir/sub/img.jpg" -> "dir_sub_img.jpg"
    """
    if not orig_name:
        return ""
    name = orig_name.replace("\\", "/")
    # 去掉可能的前导 ./ 或 /
    name = name.lstrip("./").lstrip("/")
    # 将路径分隔符替换为下划线避免创建子目录
    name = name.replace("/", "_")
    # 然后使用 secure_filename 清理不安全字符
    return secure_filename(name)

def ensure_unique_path(target_path: str) -> str:
    """
    如果 target_path 已存在，则在文件名中加入短 uuid 保证唯一。
    返回最终可用的目标路径（包含文件名）。
    """
    if not os.path.exists(target_path):
        return target_path
    base, ext = os.path.splitext(target_path)
    unique = f"{base}_{uuid.uuid4().hex[:8]}{ext}"
    return unique

# 上传图片（单张/多张/文件夹内多张） —— 仅保存，不触发推理
# 说明：
# - 不再在此端点执行模型推理（避免上传后自动检测）
# - 前端在选择图片/文件夹后会把文件 POST 到该端点，服务端仅保存到 UPLOADS_FOLDER
# - 要触发检测，请调用 /detect_one 或 /detect_all 接口（保持原有设计）
@app.route('/upload_images', methods=['POST'])
@login_required
def upload_images():
    files = request.files.getlist("files")
    if not files:
        files = request.files.getlist("files[]")
    if not files:
        return jsonify({"error": "没有收到任何文件"}), 400

    saved_names = []
    # 我们为上传批次生成时间戳，仅用于日志或返回信息（不用于推理）
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for f in files:
        # f.filename 可能包含相对路径（webkitRelativePath），使用 make_safe_filename 处理
        safe_name = make_safe_filename(f.filename)
        if safe_name == "":
            continue
        if not allowed_file(safe_name):
            continue

        target = os.path.join(UPLOADS_FOLDER, safe_name)
        target = ensure_unique_path(target)
        try:
            f.save(target)
            saved_names.append(os.path.basename(target))
        except Exception as e:
            print(f"[WARN] 保存上传文件失败: {e}")
            continue

    return jsonify({
        "message": "文件已保存（未触发检测）",
        "timestamp": timestamp,
        "saved": saved_names
    })

# 提供已上传文件列表（用于前端“已上传图片”栏）
@app.route('/list_uploads', methods=['GET'])
@login_required
def list_uploads():
    try:
        files = [f for f in os.listdir(UPLOADS_FOLDER) if allowed_file(f)]
        files.sort()
        return jsonify({"files": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 提供上传文件的直接访问（用于前端缩略图展示）
@app.route('/uploads/<path:filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory(UPLOADS_FOLDER, filename)

# 单张检测接口（基于 UPLOADS_FOLDER 中的文件）
@app.route('/detect_one', methods=['POST'])
@login_required
def detect_one():
    if model is None:
        return jsonify({"error": "当前没有加载任何模型，请联系管理员或上传模型。"}), 500

    data = request.get_json() or {}
    filename = data.get('filename')
    if not filename:
        return jsonify({"error": "缺少 filename"}), 400

    src_path = os.path.join(UPLOADS_FOLDER, filename)
    if not os.path.exists(src_path):
        return jsonify({"error": f"文件不存在: {filename}"}), 404

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 使用 batch + uuid 保证每次输出目录唯一，避免不同请求间冲突
    out_folder = os.path.join(RESULT_FOLDER, f"{timestamp}_{uuid.uuid4().hex[:8]}")
    os.makedirs(out_folder, exist_ok=True)

    # 复制文件到 out_folder（模型会在 out_folder 中写出结果）
    temp_input_path = os.path.join(out_folder, filename)
    try:
        shutil.copyfile(src_path, temp_input_path)
    except Exception:
        temp_input_path = src_path

    try:
        before_files = set(os.listdir(out_folder))
        cwd_before = os.getcwd()
        os.chdir(out_folder)
        res = model(temp_input_path)
        res[0].save()
        os.chdir(cwd_before)
        after_files = set(os.listdir(out_folder))
        new_files = after_files - before_files
        results_urls = []
        for nf in sorted(new_files):
            if os.path.splitext(nf)[1].lower() in ALLOWED_EXTENSIONS:
                rel_path = os.path.relpath(os.path.join(out_folder, nf), RESULT_FOLDER)
                url = "/results/" + rel_path.replace("\\", "/")
                results_urls.append(url)
        # 返回该图片对应的所有带框结果，并指明保存目录
        rel_out = os.path.relpath(out_folder, BASE_DIR)
        return jsonify({
            "message": "单张检测完成",
            "input": filename,
            "results": results_urls,
            "result_image": results_urls[0] if results_urls else None,
            "saved_dir": rel_out,
            "saved_dir_abs": out_folder
        })
    except Exception as e:
        try:
            os.chdir(cwd_before)
        except:
            pass
        return jsonify({"error": str(e)}), 500

# 全部检测接口：对 UPLOADS_FOLDER 中所有图片逐一检测（同步）
# 返回每张输入文件对应的结果列表，便于前端展示全部结果并支持点击放大
@app.route('/detect_all', methods=['POST'])
@login_required
def detect_all():
    if model is None:
        return jsonify({"error": "当前没有加载任何模型，请联系管理员或上传模型。"}), 500

    try:
        files = [f for f in os.listdir(UPLOADS_FOLDER) if allowed_file(f)]
        files.sort()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    results = []
    batch_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 同步处理：逐张推理并收集结果（可按需改为并发）
    for idx, fn in enumerate(files):
        src_path = os.path.join(UPLOADS_FOLDER, fn)
        # 每个输入文件使用单独子目录，避免文件冲突
        out_folder = os.path.join(RESULT_FOLDER, f"{batch_timestamp}_{idx}_{uuid.uuid4().hex[:6]}")
        os.makedirs(out_folder, exist_ok=True)
        temp_input_path = os.path.join(out_folder, fn)
        try:
            shutil.copyfile(src_path, temp_input_path)
        except Exception:
            temp_input_path = src_path

        try:
            before_files = set(os.listdir(out_folder))
            cwd_before = os.getcwd()
            os.chdir(out_folder)
            res = model(temp_input_path)
            res[0].save()
            os.chdir(cwd_before)
            after_files = set(os.listdir(out_folder))
            new_files = sorted(list(after_files - before_files))
            result_urls = []
            for nf in new_files:
                if os.path.splitext(nf)[1].lower() in ALLOWED_EXTENSIONS:
                    rel_path = os.path.relpath(os.path.join(out_folder, nf), RESULT_FOLDER)
                    url = "/results/" + rel_path.replace("\\", "/")
                    result_urls.append(url)
            rel_out = os.path.relpath(out_folder, BASE_DIR)
            if result_urls:
                results.append({"filename": fn, "result_image": result_urls[0], "results": result_urls, "saved_dir": rel_out, "saved_dir_abs": out_folder})
            else:
                results.append({"filename": fn, "result_json": {"message": "未生成带框图像"}, "results": [], "saved_dir": rel_out, "saved_dir_abs": out_folder})
        except Exception as e:
            try:
                os.chdir(cwd_before)
            except:
                pass
            results.append({"filename": fn, "error": str(e), "results": [], "saved_dir": rel_out, "saved_dir_abs": out_folder})

    # 返回所有文件的检测结果（前端可据此在 gallery 中显示所有结果并支持点击放大）
    # 同时返回 batch 级别的信息（如批次目录）以便前端显示“结果已保存至XX路径下”样式的说明
    batch_dirs = list({item.get('saved_dir') for item in results})
    return jsonify({"results": results, "batch_dirs": batch_dirs})

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
        "results": results_urls,
        "saved_dir": os.path.relpath(out_folder, BASE_DIR),
        "saved_dir_abs": out_folder
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