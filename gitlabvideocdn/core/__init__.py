"""
gitlabvideocdn.core — Core Utilities and Helpers for GitLab CI/CD Video Converter
"""

from .tracker import (
    ProgressTracker,
    TaskCancelledOrTimeout,
    send_webhook_async,
    send_webhook_sync,
    setup_cancellation_and_timeout_handlers,
    check_and_raise_cancellation,
)
from .utils import (
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

__all__ = [
    "ProgressTracker",
    "TaskCancelledOrTimeout",
    "send_webhook_async",
    "send_webhook_sync",
    "setup_cancellation_and_timeout_handlers",
    "check_and_raise_cancellation",
    "ResourceMonitor",
    "build_web_base_url",
    "verify_request_auth",
    "check_storage_server_connection",
    "detect_optimal_connections",
    "generate_timeline_sprite_and_vtt",
    "generate_metadata_and_poster",
    "calc_target_dim",
    "build_accumulated_perf_stats",
]
