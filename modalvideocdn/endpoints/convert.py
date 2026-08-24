import re
import time
import uuid

import modal

from ..config import app, volume, DEFAULT_TARGET_DIR, DEFAULT_WEB_DIR, STAGE_CFG_API
from ..core import image_cpu, verify_request_auth, check_storage_server_connection, build_web_base_url
from ..stages import download_stage


@app.function(image=image_cpu, **STAGE_CFG_API)
@modal.concurrent(max_inputs=100)
@modal.fastapi_endpoint(method="POST")
def convert_request(data: dict):
    if not verify_request_auth(data):
        return {
            "status": "error", "status_code": 401,
            "message": "Yetkisiz Erişim! Geçersiz erişim anahtarı veya güvenlik imzası."
        }, 401

    video_url          = data.get("video_url")
    webhook_url        = data.get("webhook_url")
    raw_domain         = data.get("cdn_domain") or data.get("domain") or data.get("cdn_url")
    raw_username       = data.get("username") or data.get("user")
    custom_id          = data.get("custom_id") or data.get("id") or data.get("external_id")
    qualities          = data.get("qualities")
    poster_url         = data.get("poster_url") or data.get("cover_url") or data.get("thumbnail_url")
    watermark_url      = data.get("watermark_url") or data.get("logo_url")
    watermark_position = str(data.get("watermark_position") or data.get("logo_position") or "rt").lower().strip()
    enable_sprite      = bool(data.get("sprite", False) or data.get("enable_sprite", False) or data.get("vtt", False))

    raw_gpu  = data.get("gpu")
    requested_gpu_type = data.get("gpu_type") or (str(raw_gpu).upper() if str(raw_gpu).upper() in ["T4", "L4", "A10", "A100", "L40S", "H100"] else None)
    auto_gpu = bool(data.get("auto_gpu", False) or data.get("auto_select_gpu", False) or str(raw_gpu).lower() == "auto")
    use_gpu  = bool(raw_gpu) if not auto_gpu else False
    gpu_mode = "auto" if auto_gpu else ("gpu" if use_gpu else "cpu")

    encrypt     = bool(data.get("encrypt", False) or data.get("encryption", False) or data.get("enable_encryption", False))
    raw_key_url = data.get("key_url") or data.get("key_api_url") or data.get("encryption_key_url")

    if encrypt:
        if not raw_key_url or not str(raw_key_url).strip():
            return {
                "status": "error", "status_code": 400,
                "message": "encrypt=true gönderildiğinde key_url parametresi zorunludur!"
            }, 400
        key_url = str(raw_key_url).strip()
    else:
        key_url = None

    if not video_url or not webhook_url:
        return {"status": "error", "status_code": 400, "message": "video_url ve webhook_url zorunludur!"}, 400

    if not raw_domain or not str(raw_domain).strip():
        return {"status": "error", "status_code": 400, "message": "cdn_domain parametresi zorunludur!"}, 400

    if not raw_username or not str(raw_username).strip():
        return {"status": "error", "status_code": 400, "message": "username parametresi zorunludur!"}, 400

    cdn_domain = str(raw_domain).strip().rstrip("/")
    if not cdn_domain.startswith("http://") and not cdn_domain.startswith("https://"):
        cdn_domain = f"https://{cdn_domain}"

    username = re.sub(r'[^a-zA-Z0-9_-]', '', str(raw_username).strip())
    if not username:
        return {"status": "error", "status_code": 400,
                "message": "Geçersiz username! Sadece harf, rakam, tire (-) ve alt çizgi (_) kullanılabilir."}, 400

    raw_storage_host = data.get("storage_host") or data.get("server_host") or data.get("host")
    raw_storage_user = data.get("storage_user") or data.get("server_user") or data.get("user")
    raw_storage_pass = data.get("storage_pass") or data.get("server_pass") or data.get("pass") or data.get("password")

    if not raw_storage_host or not str(raw_storage_host).strip():
        return {"status": "error", "status_code": 400, "message": "storage_host parametresi zorunludur!"}, 400
    if not raw_storage_user or not str(raw_storage_user).strip():
        return {"status": "error", "status_code": 400, "message": "storage_user parametresi zorunludur!"}, 400
    if not raw_storage_pass or not str(raw_storage_pass).strip():
        return {"status": "error", "status_code": 400, "message": "storage_pass parametresi zorunludur!"}, 400

    storage_host = str(raw_storage_host).strip()
    storage_user = str(raw_storage_user).strip()
    storage_pass = str(raw_storage_pass).strip()
    storage_port = int(data.get("storage_port") or data.get("server_port") or data.get("port") or 22)
    target_dir   = str(data.get("target_dir") or data.get("storage_dir") or DEFAULT_TARGET_DIR).strip().rstrip("/")
    web_dir      = str(data.get("web_dir") if "web_dir" in data else DEFAULT_WEB_DIR).strip().strip("/")

    if not check_storage_server_connection(storage_host, storage_port, storage_user, storage_pass, target_dir):
        return {
            "status": "error", "status_code": 503,
            "message": f"rsync/SSH depolama sunucusuna ({storage_host}:{storage_port}) erişilemiyor!"
        }, 503

    server_config = {
        "host": storage_host, "port": storage_port,
        "user": storage_user, "pass": storage_pass,
        "target_dir": target_dir, "web_dir": web_dir, "cdn_domain": cdn_domain
    }

    video_id   = str(uuid.uuid4())[:8]
    custom_id  = custom_id or video_id
    start_time = time.time()

    vol_sub = volume.with_mount_options(sub_path=f"/{video_id}")
    download_stage.with_options(volumes={"/vol": vol_sub}).spawn(
        video_url, webhook_url, video_id, custom_id, username, server_config, start_time,
        qualities, gpu_mode, poster_url, watermark_url, watermark_position, enable_sprite, encrypt, key_url,
        requested_gpu_type
    )

    if auto_gpu:
        engine_name = "Akıllı Otomatik Maliyet Seçimi (Auto-GPU / CPU)"
    elif use_gpu:
        engine_name = "NVIDIA T4 GPU (CUDA NVENC)"
    else:
        engine_name = "CPU (8x vCPU Superfast HQ)"

    expected_base_web_url = build_web_base_url(cdn_domain, web_dir, username, video_id)

    return {
        "status": "success", "status_code": 200,
        "message": f"Video dönüştürme görevi başlatıldı ({engine_name}).",
        "video_id": video_id, "custom_id": custom_id, "username": username,
        "cdn_domain": cdn_domain,
        "expected_master_url": f"{expected_base_web_url}/master.m3u8",
        "target_storage_path": f"{target_dir}/{username}/{video_id}",
        "requested_qualities": qualities or ["auto"],
        "encrypted": encrypt, "key_url": key_url if encrypt else None,
        "watermark_enabled": bool(watermark_url),
        "sprite_enabled": enable_sprite,
        "gpu_mode": gpu_mode, "auto_gpu_enabled": auto_gpu
    }, 200
