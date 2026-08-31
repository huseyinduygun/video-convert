import os

# ── Varsayılan Dizin Ayarları ────────────────────────────────────────────────
DEFAULT_TARGET_DIR = os.environ.get("DEFAULT_TARGET_DIR", "hls")
DEFAULT_WEB_DIR = os.environ.get("DEFAULT_WEB_DIR", "")  # Boş → https://cdn.domain.com/{username}/{video_id}

# ── Güvenlik & Kimlik Doğrulama ──────────────────────────────────────────────
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "hls_adm_7f9c2e4a1b8d3f5e6a0b9c8d7e6f5a4b3c2d1e0f9a8b7c6d")
SECRET_KEY  = os.environ.get("SECRET_KEY",  "hls_sec_3b5a7d9e1f2c4b6a8d0e2f4a6b8c0d2e4f6a8b0c2d4e6f8a")

# ── GitLab CI/CD Pipeline & API Ayarları ────────────────────────────────────
GITLAB_API_URL = os.environ.get("GITLAB_API_URL", "https://gitlab.com/api/v4").rstrip("/")
# Proje ID veya URL-encoded path (örneğin "huseyinduygun/video-convert" veya ID numarası)
GITLAB_PROJECT_ID = os.environ.get("GITLAB_PROJECT_ID", "huseyinduygun/video-convert")
# GitLab CI/CD Pipeline Trigger Token (Settings -> CI/CD -> Pipeline trigger tokens)
GITLAB_TRIGGER_TOKEN = os.environ.get("GITLAB_TRIGGER_TOKEN", "")
# GitLab Kişisel veya Proje Access Token (Pipeline iptali ve detaylı API işlemleri için)
GITLAB_PRIVATE_TOKEN = os.environ.get("GITLAB_PRIVATE_TOKEN", "")
# Pipeline'ın çalışacağı Git branch'i
GITLAB_REF = os.environ.get("GITLAB_REF", "main")

# ── Filigran (Watermark) Pozisyonları ────────────────────────────────────────
WATERMARK_POSITIONS = {
    "lt": "x=10:y=10",             # Left Top  (Sol Üst)
    "lb": "x=10:y=H-h-10",         # Left Bottom (Sol Alt)
    "rt": "x=W-w-10:y=10",         # Right Top (Sağ Üst)
    "rb": "x=W-w-10:y=H-h-10",     # Right Bottom (Sağ Alt)
    "tb": "x=W-w-10:y=H-h-10",     # Right Bottom Alternatif
    "c":  "x=(W-w)/2:y=(H-h)/2",   # Center (Tam Orta)
    "tc": "x=(W-w)/2:y=10",         # Top Center (Üst Orta)
    "bc": "x=(W-w)/2:y=H-h-10",    # Bottom Center (Alt Orta)
    "lc": "x=10:y=(H-h)/2",         # Left Center (Sol Orta)
    "rc": "x=W-w-10:y=(H-h)/2",    # Right Center (Sağ Orta)
}

# ── Paralel Upload Konfigürasyonu ──────────────────────────────────────────
MAX_UPLOAD_WORKERS = int(os.environ.get("MAX_UPLOAD_WORKERS", 8))

# ── İç Ağ / Doğrudan IP Bağlantı Haritası (Cloudflare & TLS Baypas) ─────────
INTERNAL_DOMAIN_IP_MAP: dict = {
    "video.xfoy.dev": "192.99.199.60",
}

# ── Standart HLS Video Profilleri ────────────────────────────────────────────
DEFAULT_PROFILES = [
    {"name": "360p",  "height": 360,  "bitrate": "800k",  "maxrate": "1M",   "bufsize": "1.5M", "audio_bitrate": "96k",  "crf": "26", "bandwidth": 1000000},
    {"name": "720p",  "height": 720,  "bitrate": "2.5M",  "maxrate": "3M",   "bufsize": "4.5M", "audio_bitrate": "128k", "crf": "24", "bandwidth": 3000000},
    {"name": "1080p", "height": 1080, "bitrate": "5M",    "maxrate": "6M",   "bufsize": "9M",   "audio_bitrate": "192k", "crf": "22", "bandwidth": 6000000},
    {"name": "1440p", "height": 1440, "bitrate": "10M",   "maxrate": "12M",  "bufsize": "18M",  "audio_bitrate": "256k", "crf": "20", "bandwidth": 12000000},
    {"name": "2160p", "height": 2160, "bitrate": "20M",   "maxrate": "24M",  "bufsize": "36M",  "audio_bitrate": "320k", "crf": "18", "bandwidth": 25000000},
    {"name": "4320p", "height": 4320, "bitrate": "50M",   "maxrate": "60M",  "bufsize": "90M",  "audio_bitrate": "320k", "crf": "18", "bandwidth": 60000000},
]
