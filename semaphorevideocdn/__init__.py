"""
semaphorevideocdn — Semaphore CI Video HLS Processor & Converter Service

Semaphore CI altyapısı üzerinde çalışan, Hetzner Storage Box ve SSH depolama sunucularına
yükleme yapan, çoklu çözünürlük HLS AES-128 şifrelemeyi, timeline sprite haritasını ve
3 seviyeli performans/darboğaz metrik loglama sistemini destekleyen video dönüştürme mikroservisi.
"""

from .config import (
    DEFAULT_TARGET_DIR,
    DEFAULT_WEB_DIR,
    ADMIN_TOKEN,
    SECRET_KEY,
    WATERMARK_POSITIONS,
    INTERNAL_DOMAIN_IP_MAP,
    DEFAULT_PROFILES,
)
from .core import (
    ProgressTracker,
    ResourceMonitor,
    build_web_base_url,
    verify_request_auth,
    check_storage_server_connection,
    detect_optimal_connections,
    generate_timeline_sprite_and_vtt,
    generate_metadata_and_poster,
    calc_target_dim,
    build_accumulated_perf_stats,
)
from .runner import run_conversion

__all__ = [
    "DEFAULT_TARGET_DIR",
    "DEFAULT_WEB_DIR",
    "ADMIN_TOKEN",
    "SECRET_KEY",
    "WATERMARK_POSITIONS",
    "INTERNAL_DOMAIN_IP_MAP",
    "DEFAULT_PROFILES",
    "ProgressTracker",
    "ResourceMonitor",
    "build_web_base_url",
    "verify_request_auth",
    "check_storage_server_connection",
    "detect_optimal_connections",
    "generate_timeline_sprite_and_vtt",
    "generate_metadata_and_poster",
    "calc_target_dim",
    "build_accumulated_perf_stats",
    "run_conversion",
]
