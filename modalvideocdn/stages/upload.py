import time
container_proc_start_time = time.time()

import os
import subprocess
import traceback
import shutil
import json
import concurrent.futures

from ..config import (
    app, volume, STAGE_CFG_UPLOAD, STAGE_CFG_DOWNLOAD, STAGE_CFG_ENCODE_CPU, STAGE_CFG_ENCODE_GPU,
    MAX_UPLOAD_WORKERS, PRICING_VCPU_SEC, PRICING_RAM_GB_SEC, PRICING_ACTIVE_GPU_SEC, PRICING_GPU_MAP
)
from ..core import (
    image_cpu,
    ProgressTracker,
    setup_cancellation_and_timeout_handlers,
    build_web_base_url,
    check_and_raise_cancellation,
    TaskCancelledOrTimeout,
    build_accumulated_perf_stats,
    decrypt_storage_pass,
)


@app.function(image=image_cpu, volumes={"/vol": volume}, **STAGE_CFG_UPLOAD)
def upload_stage(
    video_url: str, webhook_url: str, video_id: str, custom_id: str,
    username: str, server_config: dict, start_time: float, target_qualities: list,
    stage_spawn_time: float = None
):
    stage_func_start_time = container_proc_start_time
    base_start_time = stage_spawn_time or stage_func_start_time
    work_dir = f"/vol/{video_id}"
    tracker = ProgressTracker(webhook_url, video_id, custom_id)
    setup_cancellation_and_timeout_handlers(tracker, start_time, work_dir)

    t0 = time.time()
    try:
        volume.reload()
        t1 = time.time()

        for secret_file in ["enc.key", "enc.keyinfo"]:
            path = f"{work_dir}/{secret_file}"
            if os.path.exists(path):
                os.remove(path)

        base_target_dir    = server_config["target_dir"].rstrip("/")
        remote_target_path = f"{base_target_dir}/{username}/{video_id}"

        print(f"[{video_id}] 4. Hetzner rsync 4x Paralel SSH ile CDN yüklemesi → {server_config['host']}:{remote_target_path}")
        tracker.send_event(step="upload_started", progress=90)

        EXCLUDED_FILES = {
            "input.mp4", "probe_data.json", "watermark.png", "watermark_pos.txt",
            "wm_scaled.png", "enc.key", "enc.keyinfo", "enable_sprite.flag", "cancel.flag"
        }

        # Toplam yüklenecek HLS/CDN dizin boyutunu hesapla (input.mp4 ve geçici veriler hariç)
        total_upload_bytes = 0
        if os.path.exists(work_dir):
            for root, _, files in os.walk(work_dir):
                for f_name in files:
                    if f_name not in EXCLUDED_FILES and not f_name.startswith("perf_") and not f_name.endswith(".flag"):
                        total_upload_bytes += os.path.getsize(os.path.join(root, f_name))
        total_upload_mb = total_upload_bytes / (1024 * 1024)

        env = os.environ.copy()
        raw_pass = server_config.get("pass") or server_config.get("storage_pass") or server_config.get("storage_pass_enc") or ""
        env["SSHPASS"] = decrypt_storage_pass(raw_pass)

        ctl_path = f"/tmp/ssh_ctl_{video_id}_%r@%h_%p"
        ssh_opts = (
            f"ssh -p {server_config['port']} "
            f"-c aes128-gcm@openssh.com,chacha20-poly1305@openssh.com,aes128-ctr "
            f"-o StrictHostKeyChecking=no "
            f"-o UserKnownHostsFile=/dev/null "
            f"-o PreferredAuthentications=password "
            f"-o PubkeyAuthentication=no "
            f"-o Compression=no "
            f"-o IPQoS=throughput "
            f"-o TCPKeepAlive=no "
            f"-o ControlMaster=auto "
            f"-o ControlPath={ctl_path} "
            f"-o ControlPersist=120"
        )

        items = [
            i for i in os.listdir(work_dir)
            if not i.startswith("perf_") and i not in EXCLUDED_FILES and not i.endswith(".flag")
        ]
        subdirs = [i for i in items if os.path.isdir(os.path.join(work_dir, i))]
        root_files = [i for i in items if os.path.isfile(os.path.join(work_dir, i))]

        t_init0 = time.time()
        # 1. Uzak hedef dizinleri tek bir ilk SSH çağrısıyla oluştur (mkdir -p) ve SSH ControlMaster bağlantısını kur
        sub_dirs_str = " ".join([f"'{remote_target_path}/{sd}'" for sd in subdirs])
        init_ssh_cmd = [
            "sshpass", "-e",
            "ssh", "-p", str(server_config["port"]),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "PreferredAuthentications=password",
            "-o", "PubkeyAuthentication=no",
            "-o", "Compression=no",
            "-o", "IPQoS=throughput",
            "-o", "ControlMaster=yes",
            "-o", f"ControlPath={ctl_path}",
            "-o", "ControlPersist=120",
            f"{server_config['user']}@{server_config['host']}",
            f"mkdir -p '{remote_target_path}' {sub_dirs_str}"
        ]
        subprocess.run(init_ssh_cmd, capture_output=True, text=True, env=env)
        t_init1 = time.time()
        ssh_init_duration = round(t_init1 - t_init0, 3)

        upload_tasks = []
        CHUNK_SIZE = 10

        for sd in subdirs:
            sd_full_path = os.path.join(work_dir, sd)
            sd_files = [os.path.join(sd_full_path, f) for f in os.listdir(sd_full_path) if os.path.isfile(os.path.join(sd_full_path, f))]
            if not sd_files:
                continue

            file_chunks = [sd_files[i:i + CHUNK_SIZE] for i in range(0, len(sd_files), CHUNK_SIZE)]
            for chunk_idx, chunk in enumerate(file_chunks):
                upload_tasks.append({
                    "name": f"folder:{sd}_part{chunk_idx+1}",
                    "is_list": True,
                    "src": chunk,
                    "dest": f"{server_config['user']}@{server_config['host']}:{remote_target_path}/{sd}/"
                })

        if root_files:
            upload_tasks.append({
                "name": "root_files",
                "is_list": True,
                "src": [os.path.join(work_dir, rf) for rf in root_files],
                "dest": f"{server_config['user']}@{server_config['host']}:{remote_target_path}/"
            })

        up_start_time = time.time()
        import threading

        total_tasks = len(upload_tasks)
        completed_tasks = 0
        last_sent_progress = 90
        last_sent_time = time.time()
        MIN_INTERVAL_SEC = 5.0
        progress_lock = threading.Lock()

        def execute_upload_task(task):
            nonlocal completed_tasks, last_sent_progress, last_sent_time
            if task["is_list"]:
                cmd = [
                    "sshpass", "-e",
                    "rsync", "-rt", "-W", "--inplace", "--quiet",
                    "-e", ssh_opts
                ] + task["src"] + [task["dest"]]
            else:
                cmd = [
                    "sshpass", "-e",
                    "rsync", "-rt", "-W", "--inplace", "--quiet",
                    "-e", ssh_opts,
                    task["src"], task["dest"]
                ]
            res = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if res.returncode != 0:
                raise Exception(f"rsync Yükleme Hatası ({task['name']}): {res.stderr}")

            with progress_lock:
                completed_tasks += 1
                now = time.time()
                if total_tasks > 0:
                    new_prog = 90 + int((completed_tasks / total_tasks) * 9)
                    time_elapsed = now - last_sent_time
                    if new_prog > last_sent_progress and new_prog < 100 and time_elapsed >= MIN_INTERVAL_SEC:
                        last_sent_progress = new_prog
                        last_sent_time = now
                        tracker.send_event(
                            step="uploading",
                            progress=new_prog,
                            extra={
                                "upload_progress": int((completed_tasks / total_tasks) * 100),
                                "uploaded_chunks": completed_tasks,
                                "total_chunks": total_tasks
                            }
                        )

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_UPLOAD_WORKERS) as executor:
                futures = [executor.submit(execute_upload_task, task) for task in upload_tasks]
                for future in concurrent.futures.as_completed(futures):
                    future.result()
        finally:
            # ControlMaster SSH soket dosyalarını temizle
            try:
                import glob
                for sock_f in glob.glob(f"/tmp/ssh_ctl_{video_id}_*"):
                    if os.path.exists(sock_f):
                        os.remove(sock_f)
            except Exception:
                pass

        t2 = time.time()
        up_duration = round(t2 - up_start_time, 2)
        up_speed_mbps = round((total_upload_mb * 8) / max(0.1, up_duration), 2)

        print(f"[PERF_PROFILE] [{video_id}] upload_stage tamamlandı | Yükleme: {up_duration}s | Boyut: {total_upload_mb:.2f}MB | Hız: {up_speed_mbps} Mbps | Hetzner Optimizasyonu: Aktif")

        base_web_url = build_web_base_url(
            server_config["cdn_domain"],
            server_config.get("web_dir", ""),
            username, video_id
        )

        posters_list = []
        for i in [1, 2, 3]:
            if os.path.exists(f"{work_dir}/poster_{i}.jpg"):
                posters_list.append(f"{base_web_url}/poster_{i}.jpg")

        hls_final_url       = f"{base_web_url}/master.m3u8"
        poster_final_url    = (f"{base_web_url}/poster.jpg" if os.path.exists(f"{work_dir}/poster.jpg") else (posters_list[0] if posters_list else None))
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

        t3 = time.time()
        # Konteyner fonksiyonunun GERÇEK ham çalışma süresini tam kayıt öncesi kaydet
        stage_exec_sec = round(t3 - stage_func_start_time, 2)

        timing_breakdown = {
            "volume_reload_sec": round(t1 - t0, 3),
            "ssh_init_sec": ssh_init_duration,
            "rsync_upload_sec": up_duration,
            "url_and_meta_prep_sec": round(t3 - t2, 3),
            "stage_total_execution_sec": stage_exec_sec
        }

        up_perf_data = {
            "upload_duration_seconds": up_duration,
            "stage_execution_time_sec": stage_exec_sec,
            "upload_size_mb": round(total_upload_mb, 2),
            "upload_speed_mbps": up_speed_mbps,
            "hetzner_optimized": True,
            "timing_breakdown": timing_breakdown
        }
        with open(f"{work_dir}/perf_upload.json", "w", encoding="utf-8") as f:
            json.dump(up_perf_data, f)

        print(f"[TIMING_LOG] [{video_id}] upload_stage Ayrıntılı Süre Bölünmesi:")
        print(f"  ├─ 1. Volume Reload: {timing_breakdown['volume_reload_sec']}s")
        print(f"  ├─ 2. SSH İlk Bağlantı & Dizin Oluşturma: {timing_breakdown['ssh_init_sec']}s")
        print(f"  ├─ 3. Hetzner rsync 4x Paralel Yükleme: {timing_breakdown['rsync_upload_sec']}s")
        print(f"  ├─ 4. Meta & URL Hazırlığı: {timing_breakdown['url_and_meta_prep_sec']}s")
        print(f"  └─ TOTAL Konteyner Execution: {stage_exec_sec}s")

        elapsed_sec = round(time.time() - start_time, 2)
        perf_stats = build_accumulated_perf_stats(work_dir, start_time)

        print(f"[{video_id}] 5. İşlem bitti ({elapsed_sec}s, Video Süresi: {video_duration_seconds}s)")
        print(f"[PERF_PROFILE] [{video_id}] ÖZET METRİKLER:\n" + json.dumps(perf_stats, indent=2, ensure_ascii=False))

        tracker.send_event(step="completed", progress=100, status="completed", extra={
            "hls_url": hls_final_url, "master_url": hls_final_url,
            "poster": poster_final_url,
            "posters": posters_list if posters_list else ([poster_final_url] if poster_final_url else []),
            "sprite_url": sprite_final_url,
            "vtt_url": vtt_final_url, "info_json_url": info_json_final_url,
            "duration_seconds": video_duration_seconds, "duration": video_duration_seconds,
            "duration_formatted": video_duration_formatted,
            "encrypted": has_encryption, "key_url": encrypted_key_url,
            "username": username, "cdn_domain": server_config["cdn_domain"],
            "qualities": target_qualities,
            "elapsed_time_seconds": elapsed_sec, "processing_time": f"{elapsed_sec}s",
            "perf_stats": perf_stats
        })

    except TaskCancelledOrTimeout as c_err:
        elapsed_sec = round(time.time() - start_time, 2)
        print(f"[{video_id}] İptal algılandı: {c_err}")
        tracker.send_event(step="cancelled", status="cancelled", extra={
            "message": "Yükleme aşamasında işlem kullanıcı tarafından durduruldu.",
            "elapsed_time_seconds": elapsed_sec,
            "perf_stats": build_accumulated_perf_stats(work_dir, start_time)
        })
    except BaseException as e:
        elapsed_sec    = round(time.time() - start_time, 2)
        detailed_error = f"{type(e).__name__}: {str(e)}"
        print(f"[{video_id}] Yükleme Hatası:\n{traceback.format_exc()}")
        tracker.send_event(step="failed", status="failed", extra={
            "error": detailed_error,
            "message": f"Yükleme hatası: {detailed_error}",
            "elapsed_time_seconds": elapsed_sec, "processing_time": f"{elapsed_sec}s",
            "perf_stats": build_accumulated_perf_stats(work_dir, start_time)
        })
    finally:
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
            print(f"[{video_id}] Geçici dizin silindi: {work_dir}")
            volume.commit()
