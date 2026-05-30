# YT Downloader Web - Flask + yt-dlp

## 🚀 Cara Menjalankan

### 1. Install
```bash
pip install -r requirements.txt
pip install -U yt-dlp
```

### 2. Jalankan Server
```bash
python app.py
# atau
start.bat
```

### 3. Buka Browser
- **PC**: http://localhost:5000
- **HP (WiFi sama)**: http://[IP_PC]:5000

## 📁 Struktur Folder Hasil Download

```
downloads/
├── audio/           ← Musik/Audio Only (M4A)
│   ├── Lagu_1.m4a
│   └── Lagu_2.m4a
├── video/           ← Video MP4
│   ├── Video_1.mp4
│   └── Video_2 (1).mp4  ← auto anti duplikat
├── Playlist 1/      ← Auto folder playlist
│   ├── 1 - Video_A.mp4
│   └── 2 - Video_B.mp4
├── Playlist 2/
│   └── ...
└── Playlist 1.zip   ← Auto ZIP playlist
```

## 🎬 ffmpeg

### Opsi A: Auto-detect (Paling Mudah)
Tambahkan folder `ffmpeg/bin` ke folder project:
```
YT-Downloader-Web/
├── app.py
├── index.html
├── ffmpeg/              ← ← ← TARUH DI SINI
│   ├── ffmpeg.exe
│   ├── ffprobe.exe
│   └── av*.dll
└── ...
```

Atau tambahkan ke **System PATH**.

### Opsi B: Tanpa ffmpeg
Kalau tidak ada ffmpeg, otomatis fallback ke format pre-merged:
- ✅ Audio Only: lancar
- ✅ 360p-480p: lancar
- ❌ 720p+: tidak tersedia (butuh ffmpeg)

## 🎵 Fitur

- ✅ 2 Mode: Video & Musik (Audio Only)
- ✅ Resolusi dinamis (hanya yang tersedia di video)
- ✅ Estimasi ukuran file per resolusi
- ✅ Playlist: auto-folder "Playlist 1", "Playlist 2", ...
- ✅ Nama file bersih (tanpa kode random)
- ✅ Anti duplikat: `(1)`, `(2)` otomatis
- ✅ Auto-ZIP untuk playlist
- ✅ Auto-detect ffmpeg (PATH atau folder project)

## 🛠️ Build EXE

### Install PyInstaller
```bash
pip install pyinstaller
```

### Build
```bash
build_with_ffmpeg.bat   ← dengan ffmpeg
build.bat               ← tanpa ffmpeg
```

Hasil: `dist/YT-Downloader.exe`

## ⚠️ Update yt-dlp
```bash
pip install -U yt-dlp
```
