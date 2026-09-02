import os

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "7b6bcfdf9f086fb4b5bfefcbbcfd6f8f")
SECRET_KEY = os.environ.get("SECRET_KEY", "hls_sec_3b5a7d9e1f2c4b6a8d0e2f4a6b8c0d2e4f6a8b0c2d4e6f8a")

DEFAULT_PROFILES = [
    {
        "name": "360p",
        "height": 360,
        "bitrate": "800k",
        "maxrate": "856k",
        "bufsize": "1200k",
        "crf": "24",
        "bandwidth": 800000,
    },
    {
        "name": "720p",
        "height": 720,
        "bitrate": "2800k",
        "maxrate": "2996k",
        "bufsize": "4200k",
        "crf": "22",
        "bandwidth": 2800000,
    },
    {
        "name": "1080p",
        "height": 1080,
        "bitrate": "5000k",
        "maxrate": "5350k",
        "bufsize": "7500k",
        "crf": "21",
        "bandwidth": 5000000,
    },
    {
        "name": "1440p",
        "height": 1440,
        "bitrate": "9000k",
        "maxrate": "9630k",
        "bufsize": "13500k",
        "crf": "20",
        "bandwidth": 9000000,
    },
    {
        "name": "2160p",
        "height": 2160,
        "bitrate": "17000k",
        "maxrate": "18190k",
        "bufsize": "25500k",
        "crf": "19",
        "bandwidth": 17000000,
    },
    {
        "name": "4320p",
        "height": 4320,
        "bitrate": "35000k",
        "maxrate": "37450k",
        "bufsize": "52500k",
        "crf": "18",
        "bandwidth": 35000000,
    },
]

WATERMARK_POSITIONS = {
    "lt": "20:20",
    "lb": "20:main_h-overlay_h-20",
    "rt": "main_w-overlay_w-20:20",
    "rb": "main_w-overlay_w-20:main_h-overlay_h-20",
    "c": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
    "tc": "(main_w-overlay_w)/2:20",
    "bc": "(main_w-overlay_w)/2:main_h-overlay_h-20",
    "lc": "20:(main_h-overlay_h)/2",
    "rc": "main_w-overlay_w-20:(main_h-overlay_h)/2",
}

INTERNAL_DOMAIN_IP_MAP = {
    "test-videos.co.uk": None,
}

DEFAULT_TARGET_DIR = "hls"
DEFAULT_WEB_DIR = ""
MAX_UPLOAD_WORKERS = 4
