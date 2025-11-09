from flask import Flask, render_template, request, jsonify, send_from_directory
from ultralytics import YOLO
import os
from datetime import datetime

app = Flask(__name__)

# === 文件夹配置 ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULT_FOLDER = os.path.join(BASE_DIR, "static/results")
os.makedirs(RESULT_FOLDER, exist_ok=True)

# === 加载 YOLO 模型 ===
model = YOLO("yolo11n.pt")

@app.route('/')
def index():
    return render_template("detect.html")

# 前端提交图片路径
@app.route('/run_yolo', methods=['POST'])
def run_yolo():
    data = request.get_json()  # 从前端 JSON 获取数据
    image_path = data.get('image_path')

    if not image_path or not os.path.exists(image_path):
        return jsonify({"error": f"找不到图片路径: {image_path}"}), 400
    print(image_path)
    # === 执行 YOLO 推理 ===
    results = model(image_path)
    results[0].show()  # Display results
    # === 生成保存路径 ===
    timestamp_folder = os.path.join(RESULT_FOLDER, datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(timestamp_folder, exist_ok=True)
    now_DIR = os.path.dirname(os.path.abspath(__file__))
    os.chdir(timestamp_folder)
    results[0].save()
    os.chdir(now_DIR)

    # === 获取 YOLO 输出结果文件路径 ===
    saved_files = os.listdir(timestamp_folder)
    if not saved_files:
        return jsonify({"error": "YOLO 没有输出结果"}), 500

    result_image = os.path.join(timestamp_folder, saved_files[0])
    result_image_url = f"/{os.path.relpath(result_image, BASE_DIR)}"

    return jsonify({
        "message": "YOLO 推理完成",
        "input_image": image_path,
        "result_image": result_image_url
    })

# 允许访问静态图片
@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory(BASE_DIR, filename)

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)


