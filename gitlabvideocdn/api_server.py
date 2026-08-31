import json
import os
import re
import subprocess
import time
import urllib.parse
import uuid
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import (
    ADMIN_TOKEN,
    DEFAULT_TARGET_DIR,
    DEFAULT_WEB_DIR,
    GITLAB_API_URL,
    GITLAB_PRIVATE_TOKEN,
    GITLAB_PROJECT_ID,
    GITLAB_REF,
    GITLAB_TRIGGER_TOKEN,
    SECRET_KEY,
)
from .core.tracker import send_webhook_sync
from .core.utils import (
    build_web_base_url,
    check_storage_server_connection,
    verify_request_auth,
)

app = FastAPI(
    title="GitLab CI/CD Video HLS Converter API Gateway",
    description="Modal.com ile %100 uyumlu, GitLab CI/CD üzerinden video dönüştürme başlatan REST API servisi.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_encoded_project_id() -> str:
    """GitLab Proje ID veya yolunu URL-safe hale getirir."""
    pid = str(GITLAB_PROJECT_ID).strip()
    if pid.isdigit():
        return pid
    return urllib.parse.quote(pid, safe="")


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "gitlabvideocdn",
        "gitlab_project": GITLAB_PROJECT_ID,
        "gitlab_ref": GITLAB_REF
    }


@app.post("/convert_request")
async def convert_request(request: Request):
    """
    Video dönüştürme isteğini kabul eder, doğrular ve GitLab CI/CD Pipeline'ını tetikler.
    Modal.com /convert_request endpoint'i ile %100 uyumlu payload kabul eder.
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Geçersiz JSON verisi!")

    if not verify_request_auth(data):
        return {
            "status": "error", "status_code": 401,
            "message": "Yetkisiz Erişim! Geçersiz erişim anahtarı veya güvenlik imzası."
        }

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
    encrypt            = bool(data.get("encrypt", False) or data.get("encryption", False) or data.get("enable_encryption", False))
    raw_key_url        = data.get("key_url") or data.get("key_api_url") or data.get("encryption_key_url")

    if encrypt:
        if not raw_key_url or not str(raw_key_url).strip():
            return {
                "status": "error", "status_code": 400,
                "message": "encrypt=true gönderildiğinde key_url parametresi zorunludur!"
            }
        key_url = str(raw_key_url).strip()
    else:
        key_url = None

    if not video_url or not webhook_url:
        return {"status": "error", "status_code": 400, "message": "video_url ve webhook_url zorunludur!"}

    if not raw_domain or not str(raw_domain).strip():
        return {"status": "error", "status_code": 400, "message": "cdn_domain parametresi zorunludur!"}

    if not raw_username or not str(raw_username).strip():
        return {"status": "error", "status_code": 400, "message": "username parametresi zorunludur!"}

    cdn_domain = str(raw_domain).strip().rstrip("/")
    if not cdn_domain.startswith("http://") and not cdn_domain.startswith("https://"):
        cdn_domain = f"https://{cdn_domain}"

    username = re.sub(r'[^a-zA-Z0-9_-]', '', str(raw_username).strip())
    if not username:
        return {"status": "error", "status_code": 400, "message": "Geçersiz username! Sadece harf, rakam ve tire kullanılabilir."}

    raw_storage_host = data.get("storage_host") or data.get("server_host") or data.get("host")
    raw_storage_user = data.get("storage_user") or data.get("server_user") or data.get("user")
    raw_storage_pass = data.get("storage_pass") or data.get("server_pass") or data.get("pass") or data.get("password")

    if not raw_storage_host or not raw_storage_user or not raw_storage_pass:
        return {"status": "error", "status_code": 400, "message": "storage_host, storage_user ve storage_pass zorunludur!"}

    storage_host = str(raw_storage_host).strip()
    storage_user = str(raw_storage_user).strip()
    storage_pass = str(raw_storage_pass).strip()
    storage_port = int(data.get("storage_port") or data.get("server_port") or data.get("port") or 22)
    target_dir   = str(data.get("target_dir") or data.get("storage_dir") or DEFAULT_TARGET_DIR).strip().rstrip("/")
    web_dir      = str(data.get("web_dir") if "web_dir" in data else DEFAULT_WEB_DIR).strip().strip("/")

    # Depolama sunucusuna erişim testi
    if not check_storage_server_connection(storage_host, storage_port, storage_user, storage_pass, target_dir):
        return {
            "status": "error", "status_code": 503,
            "message": f"rsync/SSH depolama sunucusuna ({storage_host}:{storage_port}) erişilemiyor!"
        }

    video_id  = str(uuid.uuid4())[:8]
    custom_id = custom_id or video_id

    # Pipeline Payload verisini hazırla
    runner_payload = {
        "video_url": video_url,
        "webhook_url": webhook_url,
        "cdn_domain": cdn_domain,
        "username": username,
        "custom_id": custom_id,
        "video_id": video_id,
        "qualities": qualities,
        "poster_url": poster_url,
        "watermark_url": watermark_url,
        "watermark_position": watermark_position,
        "sprite": enable_sprite,
        "encrypt": encrypt,
        "key_url": key_url,
        "storage_host": storage_host,
        "storage_user": storage_user,
        "storage_pass": storage_pass,
        "storage_port": storage_port,
        "target_dir": target_dir,
        "web_dir": web_dir
    }

    project_slug = get_encoded_project_id()
    pipeline_id = None
    web_url = None

    # GitLab Pipeline Trigger API ile tetikle
    if GITLAB_TRIGGER_TOKEN:
        trigger_url = f"{GITLAB_API_URL}/projects/{project_slug}/trigger/pipeline"
        trigger_data = {
            "token": GITLAB_TRIGGER_TOKEN,
            "ref": GITLAB_REF,
            "variables[PAYLOAD_JSON]": json.dumps(runner_payload),
            "variables[VIDEO_ID]": video_id,
            "variables[CUSTOM_ID]": custom_id
        }
        resp = requests.post(trigger_url, data=trigger_data, timeout=10)
        if resp.status_code in [200, 201]:
            resp_json = resp.json()
            pipeline_id = resp_json.get("id")
            web_url = resp_json.get("web_url")
        else:
            return {
                "status": "error", "status_code": 502,
                "message": f"GitLab Trigger API hatası (HTTP {resp.status_code}): {resp.text}"
            }
    elif GITLAB_PRIVATE_TOKEN:
        # Fallback: Private/Personal Access Token ile tetikleme
        create_url = f"{GITLAB_API_URL}/projects/{project_slug}/pipeline"
        headers = {"PRIVATE-TOKEN": GITLAB_PRIVATE_TOKEN}
        pipeline_req = {
            "ref": GITLAB_REF,
            "variables": [
                {"key": "PAYLOAD_JSON", "value": json.dumps(runner_payload)},
                {"key": "VIDEO_ID", "value": video_id},
                {"key": "CUSTOM_ID", "value": custom_id}
            ]
        }
        resp = requests.post(create_url, headers=headers, json=pipeline_req, timeout=10)
        if resp.status_code in [200, 201]:
            resp_json = resp.json()
            pipeline_id = resp_json.get("id")
            web_url = resp_json.get("web_url")
        else:
            return {
                "status": "error", "status_code": 502,
                "message": f"GitLab Pipeline API hatası (HTTP {resp.status_code}): {resp.text}"
            }
    else:
        return {
            "status": "error", "status_code": 500,
            "message": "GITLAB_TRIGGER_TOKEN veya GITLAB_PRIVATE_TOKEN ortam değişkeni tanımlı değil!"
        }

    expected_base_web_url = build_web_base_url(cdn_domain, web_dir, username, video_id)

    return {
        "status": "success",
        "status_code": 200,
        "message": "Video dönüştürme görevi GitLab CI/CD üzerinde başarıyla başlatıldı.",
        "video_id": video_id,
        "custom_id": custom_id,
        "pipeline_id": pipeline_id,
        "pipeline_web_url": web_url,
        "username": username,
        "cdn_domain": cdn_domain,
        "expected_master_url": f"{expected_base_web_url}/master.m3u8",
        "target_storage_path": f"{target_dir}/{username}/{video_id}",
        "requested_qualities": qualities or ["auto"],
        "encrypted": encrypt,
        "key_url": key_url if encrypt else None,
        "watermark_enabled": bool(watermark_url),
        "sprite_enabled": enable_sprite
    }


@app.post("/cancel_request")
async def cancel_request(request: Request):
    """GitLab CI/CD üzerinde çalışan bir pipeline görevini iptal eder."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Geçersiz JSON verisi!")

    if not verify_request_auth(data):
        return {"status": "error", "status_code": 401, "message": "Yetkisiz Erişim!"}

    pipeline_id = data.get("pipeline_id")
    video_id    = data.get("video_id")
    webhook_url = data.get("webhook_url")
    custom_id   = data.get("custom_id", video_id)

    if not pipeline_id:
        return {"status": "error", "status_code": 400, "message": "pipeline_id parametresi zorunludur!"}

    if not GITLAB_PRIVATE_TOKEN:
        return {
            "status": "error", "status_code": 500,
            "message": "Pipeline iptal edebilmek için GITLAB_PRIVATE_TOKEN gereklidir."
        }

    project_slug = get_encoded_project_id()
    cancel_url = f"{GITLAB_API_URL}/projects/{project_slug}/pipelines/{pipeline_id}/cancel"
    headers = {"PRIVATE-TOKEN": GITLAB_PRIVATE_TOKEN}

    resp = requests.post(cancel_url, headers=headers, timeout=10)
    if resp.status_code in [200, 201]:
        if webhook_url and video_id:
            send_webhook_sync(webhook_url, {
                "status": "cancelled",
                "step": "cancelled",
                "progress": 0,
                "video_id": video_id,
                "custom_id": custom_id,
                "message": f"GitLab CI/CD Pipeline (#{pipeline_id}) iptal edildi."
            })
        return {
            "status": "success",
            "message": f"Pipeline #{pipeline_id} başarıyla iptal edildi.",
            "pipeline_id": pipeline_id
        }
    else:
        return {
            "status": "error", "status_code": resp.status_code,
            "message": f"GitLab iptal hatası: {resp.text}"
        }


@app.post("/delete_request")
async def delete_request(request: Request):
    """Depolama sunucusundaki video dosyalarını siler."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Geçersiz JSON verisi!")

    if not verify_request_auth(data):
        return {"status": "error", "status_code": 401, "message": "Yetkisiz Erişim!"}

    raw_username = data.get("username") or data.get("user")
    video_id     = data.get("video_id") or data.get("custom_id") or data.get("id")

    if not raw_username or not video_id:
        return {"status": "error", "status_code": 400, "message": "username ve video_id zorunludur!"}

    username = re.sub(r'[^a-zA-Z0-9_-]', '', str(raw_username).strip())

    raw_storage_host = data.get("storage_host") or data.get("server_host") or data.get("host")
    raw_storage_user = data.get("storage_user") or data.get("server_user") or data.get("user")
    raw_storage_pass = data.get("storage_pass") or data.get("server_pass") or data.get("pass") or data.get("password")

    if not raw_storage_host or not raw_storage_user or not raw_storage_pass:
        return {"status": "error", "status_code": 400, "message": "storage_host, storage_user ve storage_pass zorunludur!"}

    storage_host = str(raw_storage_host).strip()
    storage_user = str(raw_storage_user).strip()
    storage_pass = str(raw_storage_pass).strip()
    storage_port = int(data.get("storage_port") or data.get("server_port") or data.get("port") or 22)
    target_dir   = str(data.get("target_dir") or data.get("storage_dir") or DEFAULT_TARGET_DIR).strip().rstrip("/")

    remote_delete_path = f"{target_dir}/{username}/{video_id}"

    env = os.environ.copy()
    env["SSHPASS"] = storage_pass

    del_cmd = [
        "sshpass", "-e",
        "ssh", "-p", str(storage_port),
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "PreferredAuthentications=password",
        f"{storage_user}@{storage_host}",
        f"rm -rf {remote_delete_path}"
    ]

    print(f"[{video_id}] Sunucudan siliniyor → {storage_host}:{remote_delete_path}")
    res = subprocess.run(del_cmd, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        return {
            "status": "error", "status_code": 500,
            "message": f"Sunucudan silme başarısız: {res.stderr}"
        }

    return {
        "status": "success", "status_code": 200,
        "message": "Video ve HLS dosyaları depolama sunucusundan silindi.",
        "video_id": video_id, "username": username,
        "deleted_path": remote_delete_path
    }


@app.get("/status/{pipeline_id}")
def get_pipeline_status(pipeline_id: int):
    """GitLab CI/CD Pipeline durumunu sorgular."""
    if not GITLAB_PRIVATE_TOKEN:
        return {"status": "error", "message": "GITLAB_PRIVATE_TOKEN tanımlı değil."}

    project_slug = get_encoded_project_id()
    url = f"{GITLAB_API_URL}/projects/{project_slug}/pipelines/{pipeline_id}"
    headers = {"PRIVATE-TOKEN": GITLAB_PRIVATE_TOKEN}

    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code == 200:
        return resp.json()
    else:
        return {"status": "error", "status_code": resp.status_code, "message": resp.text}
