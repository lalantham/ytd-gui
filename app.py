import os
import uuid
import threading
import tempfile
import shutil
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file, after_this_request
from flask_socketio import SocketIO, emit
import yt_dlp
from functools import lru_cache

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Temp dir for in-progress downloads — files are deleted after browser grabs them
TEMP_DIR = Path(tempfile.gettempdir()) / "ytdl"
TEMP_DIR.mkdir(exist_ok=True)

# Track completed downloads: sid -> filepath
completed_files: dict[str, Path] = {}


def format_bytes(b):
    if b is None:
        return "N/A"
    for unit in ["B", "KB", "MB", "GB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def make_progress_hook(sid: str, prefix: str = ""):
    """Returns a progress hook that emits to the specific socket session."""
    phase = {"current": prefix + "Downloading"}

    def hook(d):
        status = d.get("status")

        if status == "downloading":
            downloaded = d.get("downloaded_bytes", 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            pct = round((downloaded / total * 100), 1) if total else 0

            socketio.emit("progress", {
                "progress": pct,
                "phase": phase["current"],
                "speed": d.get("_speed_str", "N/A").strip(),
                "eta": d.get("_eta_str", "N/A").strip(),
                "downloaded": format_bytes(downloaded),
                "total": format_bytes(total),
            }, to=sid)

        elif status == "finished":
            # finished means the individual file piece is done (pre-merge)
            phase["current"] = prefix + "Merging…"
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            socketio.emit("progress", {
                "progress": 99,
                "phase": phase["current"],
                "speed": "—",
                "eta": "—",
                "downloaded": format_bytes(total),
                "total": format_bytes(total),
            }, to=sid)

        elif status == "error":
            socketio.emit("error", {"message": "yt-dlp error during download."}, to=sid)

    return hook


def build_format_string(mode: str, quality: str) -> str:
    """
    Build a yt-dlp format string that avoids fragmented HLS/DASH streams
    by preferring direct mp4/webm container formats.

    This mirrors what yt-dlp picks when run from the terminal without flags —
    it naturally selects non-fragmented streams when available.
    """
    if mode == "audio":
        # prefer native audio containers, fall back to anything
        return "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best"

    if quality == "best":
        # Prefer non-fragmented: mp4 video + m4a audio — same as terminal default
        return (
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]"
            "/bestvideo[ext=mp4]+bestaudio"
            "/bestvideo+bestaudio"
            "/best[ext=mp4]/best"
        )
    else:
        h = quality
        return (
            f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]"
            f"/bestvideo[height<={h}][ext=mp4]+bestaudio"
            f"/bestvideo[height<={h}]+bestaudio"
            f"/best[height<={h}][ext=mp4]"
            f"/best[height<={h}]"
            f"/best"
        )


@app.route("/")
def index():
    return render_template("index.html")


@lru_cache(maxsize=1)
def get_supported_sites():
    sites = []
    # Using gen_extractors avoids full instantation where possible
    for e in yt_dlp.extractor.gen_extractors():
        name = e.ie_key()
        if name == 'Generic': continue
        desc = getattr(e, 'IE_DESC', None)
        if desc is False: continue
        sites.append({
            'name': name,
            'desc': desc if desc and desc is not True else name
        })
    sites.sort(key=lambda x: x['name'].lower())
    return sites


@app.route("/supported_sites")
def supported_sites_route():
    try:
        return jsonify(get_supported_sites())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/fetch_qualities", methods=["POST"])
def fetch_qualities():
    url = request.json.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "remote_components": ["ejs:github"],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = info.get("formats", [])
        heights = set()
        for f in formats:
            h = f.get("height")
            if h and f.get("vcodec", "none") != "none":
                note = f.get("format_note", "")
                parsed_h = None
                
                # Check format_note for strings like "1080p" or "1080p60"
                if isinstance(note, str) and "p" in note:
                    import re
                    m = re.match(r'^(\d+)p', note)
                    if m:
                        parsed_h = int(m.group(1))
                
                # Fallback to standard tier mapping based on video width for letterboxed videos
                if not parsed_h:
                    w = f.get("width", 0) or 0
                    if w >= 7680: parsed_h = 4320
                    elif w >= 3840: parsed_h = 2160
                    elif w >= 2560: parsed_h = 1440
                    elif w >= 1920: parsed_h = 1080
                    elif w >= 1280: parsed_h = 720
                    elif w >= 854: parsed_h = 480
                    elif w >= 640: parsed_h = 360
                    elif w >= 426: parsed_h = 240
                    elif w >= 256: parsed_h = 144
                    else:
                        parsed_h = h
                
                heights.add(parsed_h)

        return jsonify({
            "qualities": sorted(heights, reverse=True),
            "site": info.get("extractor_key", "Unknown"),
            "title": info.get("title", ""),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail", ""),
        })

    except yt_dlp.utils.DownloadError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500


@app.route("/download/<file_id>")
def serve_file(file_id):
    """
    Stream the completed file to the browser, then delete it from temp storage.
    file_id is a UUID generated per download session — not a filename, so
    no path traversal is possible.
    """
    filepath = completed_files.pop(file_id, None)
    if not filepath or not filepath.exists():
        return jsonify({"error": "File not found or already downloaded"}), 404

    filename = filepath.name

    @after_this_request
    def cleanup(response):
        try:
            filepath.unlink(missing_ok=True)
        except Exception:
            pass
        return response

    return send_file(
        filepath,
        as_attachment=True,
        download_name=filename,
    )


@socketio.on("start_download")
def handle_download(data):
    sid = request.sid
    
    urls_data = data.get("urls", [])
    if data.get("url"):
        urls_data.append(data.get("url"))
    
    urls = [u.strip() for u in urls_data if u.strip()]
    mode = data.get("mode", "video")
    quality = data.get("quality", "best")
    zip_batch = data.get("zip", False)

    if not urls:
        emit("error", {"message": "No URL provided."})
        return

    # Each download session gets its own isolated temp subdirectory
    job_id = uuid.uuid4().hex
    job_dir = TEMP_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    def run_download():
        try:
            total = len(urls)
            downloaded_files = []

            for i, url in enumerate(urls, 1):
                prefix = f"[{i}/{total}] " if total > 1 else ""
                fmt = build_format_string(mode, quality)

                ydl_opts = {
                    "format": fmt,
                    "outtmpl": str(job_dir / "%(title)s.%(ext)s"),
                    "noplaylist": True,
                    "progress_hooks": [make_progress_hook(sid, prefix=prefix)],
                    "remote_components": ["ejs:github"],
                    # --- These options eliminate the slow fragment behaviour ---
                    "concurrent_fragment_downloads": 1,
                    "noresizebuffer": True,
                    "http_chunk_size": 10 * 1024 * 1024,
                    "retries": 5,
                    "no_part": True,
                    # Force ffmpeg merge into mp4 for video
                    **({"merge_output_format": "mp4"} if mode != "audio" else {}),
                    # Audio post-processing
                    **({"postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }]} if mode == "audio" else {}),
                }

                before_files = set(job_dir.iterdir())
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])
                except yt_dlp.utils.DownloadError as e:
                    socketio.emit("error", {"message": f"{prefix}Error: {str(e)}"}, to=sid)
                    continue
                except Exception as e:
                    socketio.emit("error", {"message": f"{prefix}Unexpected error: {str(e)}"}, to=sid)
                    continue

                after_files = set(job_dir.iterdir())
                new_files = list(after_files - before_files)

                if new_files:
                    out_file = new_files[0]
                    downloaded_files.append(out_file)

                    # If not zipping the batch, dispatch each file immediately to the client
                    if not zip_batch:
                        file_id = uuid.uuid4().hex
                        completed_files[file_id] = out_file
                        socketio.emit("ready", {
                            "file_id": file_id,
                            "filename": out_file.name,
                        }, to=sid)

            if not downloaded_files:
                raise RuntimeError("No files were successfully downloaded.")

            # If user wants a zip container (useful for large batches)
            if zip_batch and len(urls) > 0:
                socketio.emit("progress", {
                    "progress": 99,
                    "phase": "Zipping files…",
                    "speed": "—",
                    "eta": "—",
                    "downloaded": "—",
                    "total": "—",
                }, to=sid)

                import shutil
                zip_filename = f"ytdl_batch_{job_id[:8]}"
                # make_archive outputs to zip_filename.zip
                zip_path = shutil.make_archive(str(job_dir / zip_filename), 'zip', str(job_dir))
                zip_file = Path(zip_path)

                file_id = uuid.uuid4().hex
                completed_files[file_id] = zip_file

                socketio.emit("ready", {
                    "file_id": file_id,
                    "filename": zip_file.name,
                }, to=sid)

            # Inform client the entire process is completed
            socketio.emit("job_complete", {}, to=sid)

        except Exception as e:
            socketio.emit("error", {"message": f"Fatal error: {str(e)}"}, to=sid)
            socketio.emit("job_complete", {}, to=sid)
            shutil.rmtree(job_dir, ignore_errors=True)

    threading.Thread(target=run_download, daemon=True).start()


@socketio.on("disconnect")
def on_disconnect():
    """Clean up any leftover temp files if client disconnects mid-download."""
    # completed_files entries are cleaned up on /download fetch
    # job_dirs are cleaned up after send_file in serve_file
    pass


if __name__ == "__main__":
    debug = os.environ.get("FLASK_ENV") != "production"
    socketio.run(app, host="0.0.0.0", port=5000, debug=debug)
