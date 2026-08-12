import os

DEFAULT_TARGET_DIR = "hls"
DEFAULT_WEB_DIR = ""  # Boş → https://cdn.domain.com/{username}/{video_id}

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "hls_adm_7f9c2e4a1b8d3f5e6a0b9c8d7e6f5a4b3c2d1e0f9a8b7c6d")
SECRET_KEY  = os.environ.get("SECRET_KEY",  "hls_sec_3b5a7d9e1f2c4b6a8d0e2f4a6b8c0d2e4f6a8b0c2d4e6f8a")

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
