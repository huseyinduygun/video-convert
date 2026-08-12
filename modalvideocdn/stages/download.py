import os
import subprocess
import traceback
import shutil
import time
import json

from ..config import app, volume
from ..core import image_cpu, ProgressTracker, setup_cancellation_and_timeout_handlers, detect_optimal_connections
from .cpu import cpu_process_stage
from .gpu import gpu_process_stage


@app.function(image=image_cpu, cpu=1.0, timeout=600, volumes={"/vol": volume})
def download_stage(
    video_url: str, webhook_url: str, video_id: str, custom_id: str,
    username: str, server_config: dict, start_time: float,
    requested_qualities: list = None, gpu_mode: str = "cpu",
    poster_url: str = None, watermark_url: str = None,
    watermark_position: str = "rt", enable_sprite: bool = False,
    encrypt: bool = False, key_url: str = None
):
    local_tmp_dir = f"/tmp/{video_id}"
    os.makedirs(local_tmp_dir, exist_ok=True)
    local_file = f"{local_tmp_dir}/input.mp4"

    work_dir = f"/vol/{video_id}"
    os.makedirs(work_dir, exist_ok=True)
    input_file = f"{work_dir}/input.mp4"
    tracker = ProgressTracker(webhook_url, video_id, custom_id)
    setup_cancellation_and_timeout_handlers(tracker, start_time, work_dir)

    try:
        if poster_url:
            print(f"[{video_id}] Kapak fotoğrafı indiriliyor → {poster_url}")
            try:
                subprocess.run(["curl", "-s", "-L", "-A", "Mozilla/5.0", poster_url, "-o", f"{work_dir}/poster.jpg"], timeout=15)
            except Exception as p_err:
                print(f"[{video_id}] Kapak fotoğrafı uyarısı: {p_err}")

        if watermark_url:
            print(f"[{video_id}] Filigran indiriliyor → {watermark_url} (Pozisyon: {watermark_position})")
            try:
                subprocess.run(["curl", "-s", "-L", "-A", "Mozilla/5.0", watermark_url, "-o", f"{work_dir}/watermark.png"], timeout=15)
                with open(f"{work_dir}/watermark_pos.txt", "w") as wf:
                    wf.write(str(watermark_position).strip().lower())
            except Exception as w_err:
                print(f"[{video_id}] Filigran uyarısı: {w_err}")

        if enable_sprite:
            with open(f"{work_dir}/enable_sprite.flag", "w") as sf:
                sf.write("1")

        if encrypt and key_url:
            print(f"[{video_id}] HLS AES-128 Şifreleme aktif. Key URI → {key_url}")
            key_bytes = os.urandom(16)
            key_file = f"{work_dir}/enc.key"
            key_info_file = f"{work_dir}/enc.keyinfo"
            with open(key_file, "wb") as kf:
                kf.write(key_bytes)
            with open(key_info_file, "w", encoding="utf-8") as kif:
                kif.write(f"{key_url.strip()}\n{key_file}\n")
            with open(f"{work_dir}/is_encrypted.flag", "w", encoding="utf-8") as ef:
                ef.write(key_url.strip())

        conn_count = detect_optimal_connections(video_url)
        print(f"[{video_id}] 1. İndirme başlatılıyor (Kullanıcı: {username}, {conn_count}x bağlantı, Motor: {gpu_mode}, Şifreleme: {encrypt})...")
        tracker.send_event(step="download_started", progress=0, extra={
            "download_progress": 0, "connections": conn_count,
            "gpu_mode": gpu_mode, "username": username, "encrypted": encrypt
        })

        aria2_cmd = [
            "aria2c",
            "-x", str(conn_count), "-s", str(conn_count), "-k", "1M",
            "--allow-overwrite=true",
            f"--max-connection-per-server={conn_count}",
            "--file-allocation=none", "--check-certificate=false",
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "--summary-interval=1",
            "-o", "input.mp4", "-d", local_tmp_dir, video_url
        ]

        last_dl_pct = -25
        process = subprocess.Popen(aria2_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in process.stdout:
            line = line.strip()
            if "(" in line and "%)" in line:
                try:
                    pct_str = line.split("(")[1].split("%)")[0]
                    dl_pct = int(pct_str)
                    target_dl = (dl_pct // 25) * 25
                    if target_dl > 0 and target_dl < 100 and target_dl >= last_dl_pct + 25:
                        last_dl_pct = target_dl
                        tracker.send_event(step="downloading", progress=int((target_dl / 100.0) * 10), extra={"download_progress": target_dl})
                except Exception:
                    pass
        process.wait()

        if process.returncode != 0 or not os.path.exists(local_file):
            print(f"[{video_id}] aria2c uyarısı, curl ile yedek indirme deneniyor...")
            subprocess.run(["curl", "-s", "-L", "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", video_url, "-o", local_file], check=True)

        shutil.copyfile(local_file, input_file)
        if os.path.exists(local_file):
            os.remove(local_file)

        tracker.send_event(step="download_completed", progress=10, extra={"download_progress": 100})
        volume.commit()

        if gpu_mode == "auto":
            probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height", "-of", "json", input_file]
            probe_res = subprocess.run(probe_cmd, capture_output=True, text=True)
            probe_dur = 0.0
            probe_height = 1080
            if probe_res.returncode == 0 and probe_res.stdout.strip():
                try:
                    p_data = json.loads(probe_res.stdout)
                    if "streams" in p_data and len(p_data["streams"]) > 0:
                        probe_height = int(p_data["streams"][0].get("height", 1080))
                    if "format" in p_data and "duration" in p_data["format"]:
                        probe_dur = float(p_data["format"]["duration"])
                except Exception:
                    pass

            if probe_dur >= 600 or probe_height >= 1440:
                use_gpu = True
                print(f"[{video_id}] Auto-GPU: GPU (L4) seçildi (Süre: {probe_dur:.0f}s, Çözünürlük: {probe_height}p)")
            else:
                use_gpu = False
                print(f"[{video_id}] Auto-GPU: CPU seçildi (Süre: {probe_dur:.0f}s, Çözünürlük: {probe_height}p)")
        else:
            use_gpu = (gpu_mode == "gpu")

        if use_gpu:
            gpu_process_stage.spawn(video_url, webhook_url, video_id, custom_id, username, server_config, start_time, requested_qualities)
        else:
            cpu_process_stage.spawn(video_url, webhook_url, video_id, custom_id, username, server_config, start_time, requested_qualities)

    except BaseException as e:
        elapsed_sec = round(time.time() - start_time, 2)
        detailed_error = f"{type(e).__name__}: {str(e)}"
        print(f"[{video_id}] İndirme Hatası:\n{traceback.format_exc()}")
        tracker.send_event(step="failed", status="failed", extra={
            "error": detailed_error,
            "message": f"İndirme aşamasında hata: {detailed_error}",
            "elapsed_time_seconds": elapsed_sec,
            "processing_time": f"{elapsed_sec}s"
        })
    finally:
        if os.path.exists(local_tmp_dir):
            shutil.rmtree(local_tmp_dir, ignore_errors=True)
        if not os.path.exists(f"{work_dir}/input.mp4") and os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
            volume.commit()
