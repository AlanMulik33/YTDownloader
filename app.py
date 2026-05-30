from flask import Flask, request, jsonify, send_file, after_this_request, send_from_directory
from flask_cors import CORS
import yt_dlp
import os
import uuid
import threading
import re
import shutil
import zipfile
import time
from pathlib import Path
from datetime import datetime

app = Flask(__name__)
CORS(app)

DOWNLOAD_FOLDER = Path("downloads")
DOWNLOAD_FOLDER.mkdir(exist_ok=True)
(DOWNLOAD_FOLDER / "audio").mkdir(exist_ok=True)
(DOWNLOAD_FOLDER / "video").mkdir(exist_ok=True)

download_jobs = {}
lock = threading.Lock()

def clean_error_message(error):
    message = re.sub(r'\x1b\[[0-9;]*m', '', str(error)).strip()
    message = re.sub(r'\s+', ' ', message)
    return message or 'Terjadi error tanpa pesan detail'

def guess_error_stage(message, fallback_stage):
    lower = message.lower()
    if 'url tidak boleh kosong' in lower or 'hanya mendukung url youtube' in lower:
        return 'Validasi link'
    if any(text in lower for text in ['requested format is not available', 'format is not available', 'no video formats found']):
        return 'Format atau kualitas video'
    if any(text in lower for text in ['ffmpeg', 'ffprobe', 'postprocessor', 'merge', 'merging']):
        return 'ffmpeg / penggabungan file'
    if any(text in lower for text in ['permission', 'access is denied', 'winerror 32', 'being used by another process', 'rename']):
        return 'Penyimpanan file'
    if any(text in lower for text in ['timed out', 'timeout', 'connection', 'network', 'unable to download webpage']):
        return 'Koneksi ke YouTube'
    if any(text in lower for text in ['private video', 'sign in', 'login', 'members-only', 'age-restricted', '403', '429', 'unavailable']):
        return 'Akses video YouTube'
    if any(text in lower for text in ['extract', 'video unavailable', 'unsupported url']):
        return 'Analisis video'
    return fallback_stage

def guess_error_hint(message, stage):
    lower = message.lower()
    if stage == 'Validasi link':
        return 'Periksa lagi link yang dimasukkan, lalu coba Analisis ulang.'
    if stage == 'Format atau kualitas video':
        return 'Coba pilih kualitas lain atau gunakan Best. Beberapa video tidak menyediakan semua resolusi.'
    if stage == 'ffmpeg / penggabungan file':
        return 'Pastikan ffmpeg terpasang atau gunakan kualitas lebih rendah/audio only bila ffmpeg belum tersedia.'
    if stage == 'Penyimpanan file':
        return 'Tutup file hasil download yang sedang dibuka, lalu coba lagi. Pastikan folder downloads bisa ditulis.'
    if stage == 'Koneksi ke YouTube':
        return 'Periksa koneksi internet PC server dan coba ulang beberapa saat lagi.'
    if stage == 'Akses video YouTube':
        return 'Video mungkin private, dibatasi umur/wilayah, perlu login, atau sedang dibatasi oleh YouTube.'
    if 'yt-dlp' in lower:
        return 'Coba update yt-dlp dengan perintah: pip install -U yt-dlp'
    return 'Lihat detail error di bawah, lalu coba ulang setelah bagian tersebut diperbaiki.'

def error_payload(error, fallback_stage):
    message = clean_error_message(error)
    stage = guess_error_stage(message, fallback_stage)
    return {
        'error': message,
        'error_stage': stage,
        'error_part': stage,
        'error_hint': guess_error_hint(message, stage)
    }

def sanitize_title(title):
    return yt_dlp.utils.sanitize_filename(title, restricted=True)

def get_next_playlist_number():
    existing = set()
    for item in DOWNLOAD_FOLDER.iterdir():
        if item.is_dir() and item.name.startswith("Playlist "):
            try:
                num = int(item.name.replace("Playlist ", ""))
                existing.add(num)
            except:
                pass
    n = 1
    while n in existing:
        n += 1
    return n

def get_unique_path(folder, title, ext_hint):
    safe = sanitize_title(title)
    counter = 1
    name = safe
    while True:
        test = folder / f"{name}.{ext_hint}"
        if not test.exists():
            return folder / f"{name}.%(ext)s"
        counter += 1
        name = f"{safe} ({counter})"

def get_ffmpeg_path():
    ffmpeg_in_path = shutil.which('ffmpeg')
    if ffmpeg_in_path:
        return os.path.dirname(ffmpeg_in_path)
    base_dir = Path(__file__).parent
    for sub in ['ffmpeg/bin', 'ffmpeg']:
        test = base_dir / sub / 'ffmpeg.exe'
        if test.exists():
            return str(base_dir / sub)
    return None

class ProgressHook:
    def __init__(self, job_id):
        self.job_id = job_id

    def __call__(self, d):
        with lock:
            job = download_jobs.get(self.job_id)
            if not job or job.get('status') == 'cancelled':
                raise Exception("Cancelled")
            if d['status'] == 'downloading':
                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
                job['step'] = 'Mengunduh file'
                if total > 0:
                    percent = (downloaded / total) * 100
                    job['progress'] = round(percent, 1)
                    job['speed'] = d.get('speed_string', 'N/A')
                    job['eta'] = d.get('eta_string', 'N/A')
            elif d['status'] == 'finished':
                job['progress'] = 100
                job['status'] = 'processing'
                job['step'] = 'Memproses hasil download'

def download_task(job_id, url, resolution, mode):
    try:
        with lock:
            download_jobs[job_id]['status'] = 'downloading'
            download_jobs[job_id]['step'] = 'Mengambil info video'

        info_opts = {'quiet': True, 'cookiesfrombrowser': None}
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        with lock:
            job = download_jobs.get(job_id)
            if not job or job.get('status') == 'cancelled':
                return

            is_playlist = info.get('_type') == 'playlist' or 'entries' in info
            title = info.get('title', 'Unknown')
            job['title'] = title
            job['duration'] = info.get('duration_string', 'N/A')
            job['thumbnail'] = info.get('thumbnail', '')
            job['uploader'] = info.get('uploader', 'Unknown')
            job['is_playlist'] = is_playlist
            job['step'] = 'Menyiapkan folder download'

        if is_playlist:
            pnum = get_next_playlist_number()
            folder = DOWNLOAD_FOLDER / f"Playlist {pnum}"
            folder.mkdir(exist_ok=True)
            with lock:
                job = download_jobs.get(job_id)
                if not job or job.get('status') == 'cancelled':
                    return
                job['playlist_folder'] = str(folder)
                job['playlist_name'] = f"Playlist {pnum}"
            outtmpl = str(folder / "%(playlist_index)s - %(title)s.%(ext)s")
        elif mode == 'audio':
            folder = DOWNLOAD_FOLDER / "audio"
            folder.mkdir(exist_ok=True)
            safe_title = sanitize_title(title)
            unique_path = get_unique_path(folder, safe_title, 'm4a')
            outtmpl = str(unique_path)
        else:
            folder = DOWNLOAD_FOLDER / "video"
            folder.mkdir(exist_ok=True)
            safe_title = sanitize_title(title)
            unique_path = get_unique_path(folder, safe_title, 'mp4')
            outtmpl = str(unique_path)

        with lock:
            job = download_jobs.get(job_id)
            if job and job.get('status') != 'cancelled':
                job['step'] = 'Memilih format dan kualitas'

        ffmpeg_path = get_ffmpeg_path()
        has_ffmpeg = ffmpeg_path is not None

        if mode == 'audio':
            format_spec = 'bestaudio[ext=m4a]/bestaudio/best'
            merge_format = 'm4a'
        elif not has_ffmpeg:
            format_spec = 'best[ext=mp4]/best'
            merge_format = 'mp4'
        elif resolution == 'best':
            format_spec = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            merge_format = 'mp4'
        else:
            height = resolution.replace('p', '')
            format_spec = f'bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}]/best'
            merge_format = 'mp4'

        node_path = shutil.which('node')
        js_opt = {}
        if node_path:
            js_opt['js_location'] = node_path

        ydl_opts = {
            'format': format_spec,
            'merge_output_format': merge_format,
            'outtmpl': outtmpl,
            'restrictfilenames': True,
            'progress_hooks': [ProgressHook(job_id)],
            'retries': 10,
            'fragment_retries': 10,
            'skip_unavailable_fragments': True,
            'verbose': False,
            'windowsfilenames': True,
            'nooverwrites': True,
        }

        if ffmpeg_path:
            ydl_opts['ffmpeg_location'] = ffmpeg_path

        success = False
        for attempt in range(3):
            try:
                with lock:
                    job = download_jobs.get(job_id)
                    if job and job.get('status') != 'cancelled':
                        job['step'] = 'Mengunduh file'
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                success = True
                break
            except Exception as e:
                if 'WinError 32' in str(e) or 'rename' in str(e).lower():
                    with lock:
                        job = download_jobs.get(job_id)
                        if job and job.get('status') != 'cancelled':
                            job['step'] = 'Menunggu file siap disimpan'
                            job['last_warning'] = clean_error_message(e)
                    time.sleep(3)
                    continue
                if 'Cancelled' in str(e):
                    with lock:
                        job = download_jobs.get(job_id)
                        if job:
                            job['status'] = 'cancelled'
                    return
                raise

        if not success:
            raise Exception("Gagal download setelah 3 kali percobaan")

        time.sleep(2)

        with lock:
            job = download_jobs.get(job_id)
            if not job or job.get('status') == 'cancelled':
                return
            job['step'] = 'Memproses hasil download'

            if is_playlist:
                downloaded = list(folder.glob("*"))
                job['status'] = 'completed'
                job['progress'] = 100
                job['step'] = 'Selesai'
                job['file_count'] = len([f for f in downloaded if f.is_file()])
                zip_path = folder.parent / f"{folder.name}.zip"
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for file in folder.glob("*"):
                        if file.is_file():
                            zf.write(file, file.name)
                job['zip_path'] = str(zip_path)
                job['zip_name'] = zip_path.name
            else:
                actual = None
                for attempt in range(5):
                    try:
                        files = [f for f in folder.glob("*") if f.is_file() and f.stat().st_mtime > datetime.now().timestamp() - 120]
                        if not files:
                            pattern = sanitize_title(title) + "*"
                            files = list(folder.glob(pattern))
                        if files:
                            actual = max(files, key=lambda p: p.stat().st_mtime)
                            break
                    except (PermissionError, OSError):
                        time.sleep(1)

                if actual:
                    job['filename'] = actual.name
                    job['filepath'] = str(actual)
                    job['filesize'] = actual.stat().st_size

                job['status'] = 'completed'
                job['progress'] = 100
                job['step'] = 'Selesai'

    except Exception as e:
        with lock:
            job = download_jobs.get(job_id)
            if job and job.get('status') != 'cancelled':
                detail = error_payload(e, job.get('step') or 'Download')
                job['status'] = 'error'
                job['error'] = detail['error']
                job['error_stage'] = detail['error_stage']
                job['error_part'] = detail['error_part']
                job['error_hint'] = detail['error_hint']
                job['step'] = detail['error_stage']

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/info', methods=['POST'])
def get_video_info():
    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()

    if not url:
        return jsonify({'success': False, **error_payload('URL tidak boleh kosong', 'Validasi link')}), 400

    if 'youtube.com' not in url and 'youtu.be' not in url:
        return jsonify({'success': False, **error_payload('Hanya mendukung URL YouTube', 'Validasi link')}), 400

    try:
        ydl_opts = {'quiet': True, 'cookiesfrombrowser': None}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            is_playlist = info.get('_type') == 'playlist' or 'entries' in info
            title = info.get('title', 'Unknown')

            resolutions = set()
            formats = info.get('formats', [])

            for f in formats:
                if f.get('vcodec') != 'none' and f.get('height'):
                    resolutions.add(f['height'])

            label_map = {144:'144p', 240:'240p', 360:'360p', 480:'480p',
                        720:'720p', 1080:'1080p', 1440:'1440p', 2160:'4K', 4320:'8K'}

            available = []
            for h in sorted(resolutions):
                label = label_map.get(h, f'{h}p')
                size_mb = estimate_size(h, info.get('duration', 0))
                available.append({'value': str(h), 'label': label, 'size': size_mb})

            best_size = estimate_size(max(resolutions) if resolutions else 720, info.get('duration', 0))
            available.append({'value': 'best', 'label': 'Best (Maksimal)', 'size': best_size})

            return jsonify({
                'success': True,
                'title': title,
                'is_playlist': is_playlist,
                'duration': info.get('duration_string', 'N/A'),
                'thumbnail': info.get('thumbnail', ''),
                'uploader': info.get('uploader', 'Unknown'),
                'resolutions': available,
                'has_ffmpeg': get_ffmpeg_path() is not None
            })
    except Exception as e:
        return jsonify({'success': False, **error_payload(e, 'Analisis video')}), 500

def estimate_size(height, duration):
    if not duration:
        return "~? MB"
    bitrate = {
        144: 200, 240: 400, 360: 800, 480: 1200,
        720: 2500, 1080: 5000, 1440: 8000, 2160: 15000, 4320: 30000
    }.get(height, 2500)

    size_mb = (bitrate * duration) / (8 * 1024)
    if size_mb < 1:
        return "<1 MB"
    elif size_mb < 1024:
        return f"~{int(size_mb)} MB"
    else:
        return f"~{size_mb/1024:.1f} GB"

@app.route('/api/download', methods=['POST'])
def start_download():
    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()
    resolution = data.get('resolution', 'best')
    mode = data.get('mode', 'video')

    if not url:
        return jsonify({'success': False, **error_payload('URL tidak boleh kosong', 'Validasi link')}), 400

    if 'youtube.com' not in url and 'youtu.be' not in url:
        return jsonify({'success': False, **error_payload('Hanya mendukung URL YouTube', 'Validasi link')}), 400

    job_id = str(uuid.uuid4())
    with lock:
        download_jobs[job_id] = {
            'id': job_id,
            'url': url,
            'resolution': resolution,
            'mode': mode,
            'status': 'queued',
            'progress': 0,
            'title': 'Memuat...',
            'filename': None,
            'error': None,
            'error_stage': None,
            'error_part': None,
            'error_hint': None,
            'step': 'Masuk antrian',
            'is_playlist': False
        }

    thread = threading.Thread(target=download_task, args=(job_id, url, resolution, mode))
    thread.daemon = True
    thread.start()

    return jsonify({
        'success': True,
        'job_id': job_id,
        'message': 'Download dimulai'
    })

@app.route('/api/cancel/<job_id>', methods=['POST'])
def cancel_job(job_id):
    with lock:
        job = download_jobs.get(job_id)
        if not job:
            return jsonify({'success': False, **error_payload('Job tidak ditemukan', 'Batal download')}), 404
        if job['status'] in ['completed', 'error', 'cancelled']:
            return jsonify({'success': False, **error_payload('Job sudah selesai atau gagal', 'Batal download')}), 400
        job['status'] = 'cancelled'
        job['step'] = 'Dibatalkan'
        return jsonify({'success': True, 'message': 'Download dibatalkan'})

@app.route('/api/status/<job_id>', methods=['GET'])
def get_status(job_id):
    with lock:
        job = download_jobs.get(job_id)
    if not job:
        return jsonify({'success': False, **error_payload('Job tidak ditemukan', 'Cek status download')}), 404
    return jsonify({'success': True, 'data': job})

@app.route('/api/file/<job_id>', methods=['GET'])
def download_file(job_id):
    with lock:
        job = download_jobs.get(job_id)
    if not job:
        return jsonify({'success': False, **error_payload('Job tidak ditemukan', 'Ambil file hasil download')}), 404

    if job.get('is_playlist') and job.get('zip_path'):
        zip_path = job['zip_path']
        if not os.path.exists(zip_path):
            return jsonify({'success': False, **error_payload('ZIP tidak ditemukan', 'Ambil file playlist')}), 404
        return send_file(zip_path, as_attachment=True, download_name=job['zip_name'], mimetype='application/zip')

    if not job.get('filepath') or not os.path.exists(job['filepath']):
        return jsonify({'success': False, **error_payload('File tidak tersedia', 'Ambil file hasil download')}), 404

    filepath = job['filepath']
    filename = job['filename']
    mimetype = 'audio/mp4' if job.get('mode') == 'audio' else 'video/mp4'

    @after_this_request
    def cleanup(response):
        return response

    return send_file(filepath, as_attachment=True, download_name=filename, mimetype=mimetype)

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        'success': True,
        'status': 'online',
        'yt_dlp_version': yt_dlp.version.__version__,
        'ffmpeg': get_ffmpeg_path() is not None
    })

if __name__ == '__main__':
    import socket
    hostname = socket.gethostname()
    try:
        local_ip = socket.getaddrinfo(hostname, None, socket.AF_INET)[0][4][0]
    except:
        local_ip = '127.0.0.1'

    ffmpeg_path = get_ffmpeg_path()
    ffmpeg_status = "Terdeteksi" if ffmpeg_path else "Tidak ada (fallback aktif)"

    print("=" * 55)
    print("YT DOWNLOADER SERVER AKTIF!")
    print("=" * 55)
    print(f"yt-dlp : {yt_dlp.version.__version__}")
    print(f"ffmpeg : {ffmpeg_status}")
    if ffmpeg_path:
        print(f"  path : {ffmpeg_path}")
    print(f"audio  : {DOWNLOAD_FOLDER / 'audio'}")
    print(f"video  : {DOWNLOAD_FOLDER / 'video'}")
    print(f"playlist: {DOWNLOAD_FOLDER}")
    print()
    print("URL AKSES:")
    print(f"  PC : http://localhost:5000")
    print(f"  HP : http://{local_ip}:5000")
    print()
    print("Update yt-dlp: pip install -U yt-dlp")
    print("=" * 55)
    app.run(host='0.0.0.0', port=5000, debug=True)
