import os
import subprocess
import traceback
import shutil
import time
import json

from ..config import app, volume
from ..core import image_cpu, ProgressTracker, setup_cancellation_and_timeout_handlers, build_web_base_url


@app.function(image=image_cpu, cpu=0.25, memory=1024, timeout=1200, scaledown_window=0, volumes={"/vol": volume})
def upload_stage(
    video_url: str, webhook_url: str, video_id: str, custom_id: str,
    username: str, server_config: dict, start_time: float, target_qualities: list
):
    work_dir = f"/vol/{video_id}"
    tracker = ProgressTracker(webhook_url, video_id, custom_id)
    setup_cancellation_and_timeout_handlers(tracker, start_time, work_dir)

    try:
        volume.reload()

        for secret_file in ["enc.key", "enc.keyinfo"]:
            path = f"{work_dir}/{secret_file}"
            if os.path.exists(path):
                os.remove(path)

        base_target_dir    = server_config["target_dir"].rstrip("/")
        remote_target_path = f"{base_target_dir}/{username}/{video_id}"

        print(f"[{video_id}] 4. rsync ile CDN yüklemesi → {server_config['host']}:{remote_target_path}")
        tracker.send_event(step="upload_started", progress=90)

        env = os.environ.copy()
        env["SSHPASS"] = server_config["pass"]

        ssh_opts = (
            f"ssh -p {server_config['port']} "
            f"-o StrictHostKeyChecking=no "
            f"-o UserKnownHostsFile=/dev/null "
            f"-o PreferredAuthentications=password "
            f"-o PubkeyAuthentication=no"
        )

        rsync_cmd = [
            "sshpass", "-e",
            "rsync", "-rtz", "--quiet", "--mkpath",
            "-e", ssh_opts,
            f"{work_dir}/",
            f"{server_config['user']}@{server_config['host']}:{remote_target_path}/"
        ]

        rsync_res = subprocess.run(rsync_cmd, capture_output=True, text=True, env=env)
        if rsync_res.returncode != 0:
            raise Exception(f"rsync Yükleme Hatası ({server_config['host']}): {rsync_res.stderr}")

        base_web_url = build_web_base_url(
            server_config["cdn_domain"],
            server_config.get("web_dir", ""),
            username, video_id
        )

        hls_final_url       = f"{base_web_url}/master.m3u8"
        poster_final_url    = f"{base_web_url}/poster.jpg"     if os.path.exists(f"{work_dir}/poster.jpg")      else None
        sprite_final_url    = f"{base_web_url}/sprite.jpg"     if os.path.exists(f"{work_dir}/sprite.jpg")      else None
        vtt_final_url       = f"{base_web_url}/thumbnails.vtt" if os.path.exists(f"{work_dir}/thumbnails.vtt")  else None
        info_json_final_url = f"{base_web_url}/info.json"

        has_encryption    = os.path.exists(f"{work_dir}/is_encrypted.flag")
        encrypted_key_url = None
        if has_encryption:
            with open(f"{work_dir}/is_encrypted.flag", "r", encoding="utf-8") as ef:
                encrypted_key_url = ef.read().strip()

        video_duration_seconds   = 0.0
        video_duration_formatted = "00:00:00"
        info_json_path = f"{work_dir}/info.json"
        if os.path.exists(info_json_path):
            try:
                with open(info_json_path, "r", encoding="utf-8") as ij_file:
                    ij_data = json.load(ij_file)
                    video_duration_seconds   = ij_data.get("duration_seconds", 0.0)
                    video_duration_formatted = ij_data.get("duration_formatted", "00:00:00")
            except Exception:
                pass

        elapsed_sec = round(time.time() - start_time, 2)
        print(f"[{video_id}] 5. İşlem bitti ({elapsed_sec}s, Video Süresi: {video_duration_seconds}s)")
        tracker.send_event(step="completed", progress=100, status="completed", extra={
            "hls_url": hls_final_url, "master_url": hls_final_url,
            "poster_url": poster_final_url, "sprite_url": sprite_final_url,
            "vtt_url": vtt_final_url, "info_json_url": info_json_final_url,
            "duration_seconds": video_duration_seconds, "duration": video_duration_seconds,
            "duration_formatted": video_duration_formatted,
            "encrypted": has_encryption, "key_url": encrypted_key_url,
            "username": username, "cdn_domain": server_config["cdn_domain"],
            "qualities": target_qualities,
            "elapsed_time_seconds": elapsed_sec, "processing_time": f"{elapsed_sec}s"
        })

    except BaseException as e:
        elapsed_sec    = round(time.time() - start_time, 2)
        detailed_error = f"{type(e).__name__}: {str(e)}"
        print(f"[{video_id}] Yükleme Hatası:\n{traceback.format_exc()}")
        tracker.send_event(step="failed", status="failed", extra={
            "error": detailed_error,
            "message": f"Yükleme hatası: {detailed_error}",
            "elapsed_time_seconds": elapsed_sec, "processing_time": f"{elapsed_sec}s"
        })
    finally:
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
            print(f"[{video_id}] Geçici dizin silindi: {work_dir}")
            volume.commit()
