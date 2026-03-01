import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
UPLOAD_DIR = os.path.join(TEMP_DIR, "uploads")
OUTPUT_DIR = os.path.join(TEMP_DIR, "outputs")

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
ALLOWED_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS

MAX_CONTENT_LENGTH = 300 * 1024 * 1024  # 300 MB

SLICE_OUTPUT_WIDTH = 1080  # Instagram standard width

SESSION_MAX_AGE_SECONDS = 1800  # 30 minutes

# Ensure temp directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
