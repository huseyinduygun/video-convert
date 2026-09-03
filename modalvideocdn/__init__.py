"""
modalvideocdn — Modal Video CDN Package

Kullanım:
  modal deploy -m modalvideocdn

Modül yapısı:
  ├── config/             → App, Volume, Sabitler
  │   ├── app.py
  │   └── settings.py
  ├── core/               → Görseller, Tracker, Yardımcı Fonksiyonlar
  │   ├── images.py
  │   ├── tracker.py
  │   └── utils.py
  ├── stages/             → İşlem Aşamaları
  │   ├── download.py     (Aşama 1: İndirme + Auto-GPU)
  │   ├── cpu.py          (Aşama 2A: CPU Encoding)
  │   ├── gpu.py          (Aşama 2B: GPU NVENC Encoding)
  │   └── upload.py       (Aşama 3: rsync Upload)
  └── endpoints/          → Web Endpointleri
      ├── convert.py      (POST /convert_request)
      └── delete.py       (POST /delete_request)
"""

from .config import app, volume
from .core import (
    image_cpu,
    image_gpu,
    ProgressTracker,
    build_web_base_url,
    verify_request_auth,
    check_storage_server_connection,
    detect_optimal_connections,
    generate_timeline_sprite_and_vtt,
    generate_metadata_and_poster,
    calc_target_dim,
    auto_cleanup_cron,
)
from .stages import download_stage, cpu_process_stage, gpu_process_stage, upload_stage
from .endpoints import convert_request, delete_request, cancel_request, billing_request

__all__ = [
    "app",
    "volume",
    "image_cpu",
    "image_gpu",
    "download_stage",
    "cpu_process_stage",
    "gpu_process_stage",
    "upload_stage",
    "convert_request",
    "delete_request",
    "cancel_request",
    "billing_request",
    "auto_cleanup_cron",
]
