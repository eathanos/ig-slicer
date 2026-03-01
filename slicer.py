import os
import json
import shutil
import subprocess
from PIL import Image

from config import ALLOWED_IMAGE_EXTENSIONS, ALLOWED_VIDEO_EXTENSIONS, SLICE_OUTPUT_WIDTH


def get_media_info(filepath):
    """Return dimensions, media type, and duration (for video) of a media file."""
    ext = os.path.splitext(filepath)[1].lower()

    if ext in ALLOWED_IMAGE_EXTENSIONS:
        with Image.open(filepath) as img:
            width, height = img.size
        return {
            "type": "image",
            "width": width,
            "height": height,
            "duration": None,
            "suggested_slices": _suggest_slices(width, height),
        }

    if ext in ALLOWED_VIDEO_EXTENSIONS:
        width, height, duration = _get_video_dimensions(filepath)
        return {
            "type": "video",
            "width": width,
            "height": height,
            "duration": duration,
            "suggested_slices": _suggest_slices(width, height),
        }

    raise ValueError(f"Unsupported file extension: {ext}")


def _suggest_slices(width, height):
    """Auto-detect suggested slide count based on aspect ratio."""
    if height == 0:
        return 2
    suggested = round(width / (height * 4 / 5))
    return max(2, min(20, suggested))


def _get_video_dimensions(filepath):
    """Use ffprobe to get video width, height, and duration."""
    if not ffprobe_available():
        raise RuntimeError(
            "ffmpeg/ffprobe is not installed. Install ffmpeg to enable video support: "
            "https://ffmpeg.org/download.html"
        )

    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        filepath,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, OSError) as e:
        raise RuntimeError(
            "ffmpeg/ffprobe is not installed. Install ffmpeg to enable video support: "
            "https://ffmpeg.org/download.html"
        ) from e
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    data = json.loads(result.stdout)
    width = height = 0
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = int(stream["width"])
            height = int(stream["height"])
            break

    duration = None
    fmt = data.get("format", {})
    if "duration" in fmt:
        duration = float(fmt["duration"])

    return width, height, duration


def ffmpeg_available():
    """Check if ffmpeg is installed and accessible."""
    return shutil.which("ffmpeg") is not None


def ffprobe_available():
    """Check if ffprobe is installed and accessible."""
    return shutil.which("ffprobe") is not None


def slice_image(filepath, num_slices, output_dir):
    """Slice an image into equal-width segments, resized to SLICE_OUTPUT_WIDTH."""
    os.makedirs(output_dir, exist_ok=True)

    with Image.open(filepath) as img:
        width, height = img.size
        slice_width = width // num_slices
        outputs = []

        for i in range(num_slices):
            left = i * slice_width
            # Last slice absorbs remaining pixels
            right = width if i == num_slices - 1 else left + slice_width

            cropped = img.crop((left, 0, right, height))

            # Resize to target width, maintaining aspect ratio
            crop_w, crop_h = cropped.size
            scale = SLICE_OUTPUT_WIDTH / crop_w
            new_height = round(crop_h * scale)
            resized = cropped.resize((SLICE_OUTPUT_WIDTH, new_height), Image.LANCZOS)

            filename = f"slide_{i + 1:02d}.png"
            out_path = os.path.join(output_dir, filename)
            resized.save(out_path, "PNG")
            outputs.append(filename)

    return outputs


def slice_video(filepath, num_slices, output_dir):
    """Slice a video into equal-width segments using ffmpeg."""
    if not ffmpeg_available():
        raise RuntimeError(
            "ffmpeg is not installed. Install it to enable video slicing: https://ffmpeg.org/download.html"
        )

    os.makedirs(output_dir, exist_ok=True)

    width, height, _ = _get_video_dimensions(filepath)
    slice_width = width // num_slices
    outputs = []

    for i in range(num_slices):
        x_offset = i * slice_width
        # Last slice absorbs remaining pixels
        crop_w = (width - x_offset) if i == num_slices - 1 else slice_width

        filename = f"slide_{i + 1:02d}.mp4"
        out_path = os.path.join(output_dir, filename)

        # Scale height to be even (required by h264)
        cmd = [
            "ffmpeg", "-y",
            "-i", filepath,
            "-vf", f"crop={crop_w}:{height}:{x_offset}:0,scale={SLICE_OUTPUT_WIDTH}:-2",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            out_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except (FileNotFoundError, OSError) as e:
            raise RuntimeError(
                "ffmpeg is not installed. Install it to enable video slicing: "
                "https://ffmpeg.org/download.html"
            ) from e
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed on slice {i + 1}: {result.stderr[-500:]}")

        outputs.append(filename)

    return outputs
