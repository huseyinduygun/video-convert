import os
import re
import subprocess

import modal

from ..config import app, DEFAULT_TARGET_DIR
from ..core import image_cpu, verify_request_auth


@app.function(image=image_cpu)
@modal.fastapi_endpoint(method="POST")
def delete_request(data: dict):
    if not verify_request_auth(data):
        return {
            "status": "error", "status_code": 401,
            "message": "Yetkisiz Erişim! Geçersiz erişim anahtarı veya güvenlik imzası."
        }, 401

    raw_username = data.get("username") or data.get("user")
    video_id     = data.get("video_id") or data.get("custom_id") or data.get("id")

    if not raw_username or not str(raw_username).strip():
        return {"status": "error", "status_code": 400, "message": "username parametresi zorunludur!"}, 400
    if not video_id or not str(video_id).strip():
        return {"status": "error", "status_code": 400, "message": "video_id parametresi zorunludur!"}, 400

    username = re.sub(r'[^a-zA-Z0-9_-]', '', str(raw_username).strip())

    raw_storage_host = data.get("storage_host") or data.get("server_host") or data.get("host")
    raw_storage_user = data.get("storage_user") or data.get("server_user") or data.get("user")
    raw_storage_pass = data.get("storage_pass") or data.get("server_pass") or data.get("pass") or data.get("password")

    if not raw_storage_host or not raw_storage_user or not raw_storage_pass:
        return {
            "status": "error", "status_code": 400,
            "message": "storage_host, storage_user ve storage_pass parametreleri zorunludur!"
        }, 400

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
        }, 500

    return {
        "status": "success", "status_code": 200,
        "message": "Video ve HLS dosyaları depolama sunucusundan silindi.",
        "video_id": video_id, "username": username,
        "deleted_path": remote_delete_path
    }, 200
