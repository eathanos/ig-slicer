import io
import os
import shutil
import threading
import time
import traceback
import uuid
import zipfile

from flask import Flask, jsonify, request, send_from_directory, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

import config
from slicer import get_media_info, slice_image, slice_video, ffmpeg_available, ffprobe_available

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH


# --- Cleanup thread ---

def cleanup_old_sessions():
    """Delete upload/output folders older than SESSION_MAX_AGE_SECONDS."""
    while True:
        time.sleep(300)  # check every 5 minutes
        now = time.time()
        for base in (config.UPLOAD_DIR, config.OUTPUT_DIR):
            if not os.path.isdir(base):
                continue
            for name in os.listdir(base):
                path = os.path.join(base, name)
                if not os.path.isdir(path):
                    continue
                try:
                    age = now - os.path.getmtime(path)
                    if age > config.SESSION_MAX_AGE_SECONDS:
                        shutil.rmtree(path, ignore_errors=True)
                except OSError:
                    pass


cleanup_thread = threading.Thread(target=cleanup_old_sessions, daemon=True)
cleanup_thread.start()


# --- Routes ---

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Unsupported file type: {ext}"}), 400

    session_id = uuid.uuid4().hex
    session_dir = os.path.join(config.UPLOAD_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    # Sanitize filename: keep only the extension, use a fixed name
    safe_name = f"source{ext}"
    filepath = os.path.join(session_dir, safe_name)
    file.save(filepath)

    # If it's a video and ffmpeg/ffprobe aren't installed, skip probing
    is_video = ext in config.ALLOWED_VIDEO_EXTENSIONS
    if is_video and not ffprobe_available():
        return jsonify({
            "session_id": session_id,
            "filename": safe_name,
            "type": "video",
            "width": 0,
            "height": 0,
            "duration": None,
            "suggested_slices": 3,
            "ffmpeg_available": False,
        })

    try:
        info = get_media_info(filepath)
    except Exception as e:
        print(f"[ERROR] Could not read media: {e}")
        traceback.print_exc()
        shutil.rmtree(session_dir, ignore_errors=True)
        return jsonify({"error": f"Could not read media: {e}"}), 400

    return jsonify({
        "session_id": session_id,
        "filename": safe_name,
        "type": info["type"],
        "width": info["width"],
        "height": info["height"],
        "duration": info["duration"],
        "suggested_slices": info["suggested_slices"],
        "ffmpeg_available": ffmpeg_available(),
    })


@app.route("/api/slice", methods=["POST"])
def slice_media():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    session_id = data.get("session_id")
    num_slices = data.get("num_slices")

    if not session_id or not num_slices:
        return jsonify({"error": "session_id and num_slices are required"}), 400

    try:
        num_slices = int(num_slices)
    except (ValueError, TypeError):
        return jsonify({"error": "num_slices must be an integer"}), 400

    if not 2 <= num_slices <= 20:
        return jsonify({"error": "num_slices must be between 2 and 20"}), 400

    # Find the uploaded file
    upload_dir = os.path.join(config.UPLOAD_DIR, session_id)
    if not os.path.isdir(upload_dir):
        return jsonify({"error": "Session not found. Please re-upload."}), 404

    files = os.listdir(upload_dir)
    if not files:
        return jsonify({"error": "No uploaded file found"}), 404

    filepath = os.path.join(upload_dir, files[0])
    ext = os.path.splitext(filepath)[1].lower()

    output_dir = os.path.join(config.OUTPUT_DIR, session_id)
    # Clear previous output for this session
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)

    try:
        if ext in config.ALLOWED_IMAGE_EXTENSIONS:
            outputs = slice_image(filepath, num_slices, output_dir)
            media_type = "image"
        elif ext in config.ALLOWED_VIDEO_EXTENSIONS:
            outputs = slice_video(filepath, num_slices, output_dir)
            media_type = "video"
        else:
            return jsonify({"error": "Unsupported file type"}), 400
    except RuntimeError as e:
        print(f"[ERROR] Slicing failed: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        print(f"[ERROR] Slicing failed: {e}")
        traceback.print_exc()
        return jsonify({"error": f"Slicing failed: {e}"}), 500

    return jsonify({
        "session_id": session_id,
        "type": media_type,
        "slices": outputs,
    })


@app.route("/api/preview/<session_id>/<filename>")
def preview(session_id, filename):
    output_dir = os.path.join(config.OUTPUT_DIR, session_id)
    if not os.path.isdir(output_dir):
        return jsonify({"error": "Session not found"}), 404
    # Prevent directory traversal
    safe_path = os.path.join(output_dir, os.path.basename(filename))
    if not os.path.isfile(safe_path):
        return jsonify({"error": "File not found"}), 404
    return send_from_directory(output_dir, os.path.basename(filename))


@app.route("/api/download/<session_id>/<filename>")
def download(session_id, filename):
    output_dir = os.path.join(config.OUTPUT_DIR, session_id)
    if not os.path.isdir(output_dir):
        return jsonify({"error": "Session not found"}), 404
    safe_name = os.path.basename(filename)
    safe_path = os.path.join(output_dir, safe_name)
    if not os.path.isfile(safe_path):
        return jsonify({"error": "File not found"}), 404
    return send_from_directory(output_dir, safe_name, as_attachment=True)


@app.route("/api/download-zip/<session_id>")
def download_zip(session_id):
    output_dir = os.path.join(config.OUTPUT_DIR, session_id)
    if not os.path.isdir(output_dir):
        return jsonify({"error": "Session not found"}), 404

    files = sorted(os.listdir(output_dir))
    if not files:
        return jsonify({"error": "No slices found"}), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(os.path.join(output_dir, f), f)
    buf.seek(0)

    return (
        buf.getvalue(),
        200,
        {
            "Content-Type": "application/zip",
            "Content-Disposition": f"attachment; filename=ig_slices_{session_id[:8]}.zip",
        },
    )


@app.route("/api/source/<session_id>/<filename>")
def source_preview(session_id, filename):
    """Serve the original uploaded file for preview."""
    upload_dir = os.path.join(config.UPLOAD_DIR, session_id)
    if not os.path.isdir(upload_dir):
        return jsonify({"error": "Session not found"}), 404
    safe_name = os.path.basename(filename)
    safe_path = os.path.join(upload_dir, safe_name)
    if not os.path.isfile(safe_path):
        return jsonify({"error": "File not found"}), 404
    return send_from_directory(upload_dir, safe_name)


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5000)
