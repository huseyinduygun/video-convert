import time
container_proc_start_time = time.time()

import os
import subprocess
import traceback
import shutil
import json

from ..config import app, volume, STAGE_CFG_DOWNLOAD, STAGE_CFG_ENCODE_CPU
from ..core import (
    image_cpu,
    ProgressTracker,
    setup_cancellation_and_timeout_handlers,
    detect_optimal_connections,
    cleanup_stale_volume_files,
    check_and_raise_cancellation,
    TaskCancelledOrTimeout,
    calc_optimal_cpu,
    build_accumulated_perf_stats,
)
from .cpu import cpu_process_stage
from .gpu import gpu_process_stage


@app.function(image=image_cpu, volumes={"/vol": volume}, **STAGE_CFG_DOWNLOAD)
def download_stage(
    video_url: str, webhook_url: str, video_id: str, custom_id: str,
    username: str, server_config: dict, start_time: float,
    requested_qualities: list = None, gpu_mode: str = "cpu",
    poster_url: str = None, watermark_url: str = None,
    watermark_position: str = "rt", enable_sprite: bool = False,
    encrypt: bool = False, key_url: str = None,
    requested_gpu_type: str = None
):
    stage_func_start_time = container_proc_start_time
    work_dir = f"/vol/{video_id}"
    os.makedirs(work_dir, exist_ok=True)
    input_file = f"{work_dir}/input.mp4"
    tracker = ProgressTracker(webhook_url, video_id, custom_id)
    setup_cancellation_and_timeout_handlers(tracker, start_time, work_dir)

    t0 = time.time()
    try:
        t1 = time.time()

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

        t2 = time.time()
        conn_count = 16
        print(f"[{video_id}] 1. İndirme başlatılıyor (Kullanıcı: {username}, {conn_count}x bağlantı, Doğrudan /vol, Motor: {gpu_mode}, Şifreleme: {encrypt})...")
        tracker.send_event(step="download_started", progress=0, extra={
            "download_progress": 0, "connections": conn_count,
            "gpu_mode": gpu_mode, "username": username, "encrypted": encrypt
        })

        # Direct-IP Bypass & Raw HTTP Routing (HTTPS/TLS ve Cloudflare Şifreleme Yükünü Baypas Etmek İçin)
        from urllib.parse import urlparse, urlunparse
        from ..config import INTERNAL_DOMAIN_IP_MAP

        parsed_url = urlparse(video_url)
        domain_host = parsed_url.netloc.split(":")[0].lower()
        target_direct_ip = INTERNAL_DOMAIN_IP_MAP.get(domain_host)

        download_target_url = video_url
        aria2_headers = [f"--header=Host: {domain_host}"]

        if target_direct_ip:
            new_netloc = target_direct_ip if not parsed_url.port else f"{target_direct_ip}:{parsed_url.port}"
            download_target_url = urlunparse(("http", new_netloc, parsed_url.path, parsed_url.params, parsed_url.query, parsed_url.fragment))
            print(f"[{video_id}] Direct-IP Bypass Aktif: {video_url} -> {download_target_url} (Host Header: {domain_host})")

        dl_start_time = time.time()
        local_tmp_dir = f"/tmp/dl_{video_id}"
        os.makedirs(local_tmp_dir, exist_ok=True)
        local_tmp_file = f"{local_tmp_dir}/input.mp4"

        aria2_cmd = [
            "aria2c",
            "-x", str(conn_count), "-s", str(conn_count), "-k", "1M",
            "--allow-overwrite=true",
            f"--max-connection-per-server={conn_count}",
            "--file-allocation=none", "--check-certificate=false",
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "--summary-interval=1",
            aria2_headers[0],
            "-o", "input.mp4", "-d", local_tmp_dir, download_target_url
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

        if process.returncode != 0 or not os.path.exists(local_tmp_file):
            print(f"[{video_id}] aria2c uyarısı, curl ile yerel disk yedek indirme deneniyor...")
            subprocess.run(["curl", "-s", "-L", "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", video_url, "-o", local_tmp_file], check=True)

        # ffprobe: shutil.move'dan ÖNCE yerel NVMe'de çalıştır (FUSE üzerinde çalıştırmaktan 10x daha hızlı)
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-analyzeduration", "5000000", "-probesize", "10000000",
            "-show_entries", "format=duration:stream=width,height,codec_name,codec_type",
            "-of", "json", local_tmp_file
        ]
        probe_res = subprocess.run(probe_cmd, capture_output=True, text=True)
        probe_dur = 0.0
        probe_height = 1080
        probe_width = 1920
        probe_codec = "h264"
        probe_pix_fmt = "yuv420p"
        probe_has_audio = False
        probe_is_aac = False

        if probe_res.returncode == 0 and probe_res.stdout.strip():
            try:
                p_data = json.loads(probe_res.stdout)
                for stream in p_data.get("streams", []):
                    if stream.get("codec_type") == "video" and probe_height == 1080 and probe_width == 1920:
                        probe_height = int(stream.get("height", 1080))
                        probe_width = int(stream.get("width", 1920))
                        probe_codec = stream.get("codec_name", "h264")
                        probe_pix_fmt = stream.get("pix_fmt", "yuv420p")
                    elif stream.get("codec_type") == "audio":
                        probe_has_audio = True
                        if stream.get("codec_name") == "aac":
                            probe_is_aac = True
                if "format" in p_data and "duration" in p_data["format"]:
                    probe_dur = float(p_data["format"]["duration"])
            except Exception:
                pass

        import shutil
        shutil.move(local_tmp_file, input_file)
        if os.path.exists(local_tmp_dir):
            shutil.rmtree(local_tmp_dir, ignore_errors=True)

        t3 = time.time()
        dl_duration = round(t3 - dl_start_time, 2)
        file_size_bytes = os.path.getsize(input_file) if os.path.exists(input_file) else 0
        file_size_mb = file_size_bytes / (1024 * 1024)
        dl_speed_mbps = round((file_size_mb * 8) / max(0.1, dl_duration), 2)

        t4 = time.time()

        # İndirilen girdi dosyasını ve geçici verileri Modal Volume ağ diskine yaz (FUSE yazma işlemi)
        volume.commit()

        # Konteyner fonksiyonunun GERÇEK ham çalışma süresini tüm işlem ve commitler dahil kaydet
        t5 = time.time()
        stage_exec_sec = round(t5 - stage_func_start_time, 2)

        timing_breakdown = {
            "volume_reload_sec": round(t1 - t0, 3),
            "pre_checks_sec": round(t2 - t1, 3),
            "aria2c_download_sec": round(t3 - t2, 3),
            "ffprobe_analysis_sec": round(t4 - t3, 3),
            "volume_commit_sec": round(t5 - t4, 3),
            "stage_total_execution_sec": stage_exec_sec
        }

        dl_perf_data = {
            "download_time_sec": dl_duration,
            "stage_execution_time_sec": stage_exec_sec,
            "download_size_mb": round(file_size_mb, 2),
            "download_speed_mbps": dl_speed_mbps,
            "direct_vol_download": True,
            "connections": conn_count,
            "timing_breakdown": timing_breakdown
        }

        with open(f"{work_dir}/perf_download.json", "w", encoding="utf-8") as f:
            json.dump(dl_perf_data, f)

        # cpu/gpu stage'lerin ffprobe çalıştırmasına gerek kalmasın diye probe verilerini kaydet
        probe_data = {
            "duration": probe_dur,
            "width": probe_width,
            "height": probe_height,
            "codec": probe_codec,
            "pix_fmt": probe_pix_fmt,
            "has_audio": probe_has_audio,
            "is_aac": probe_is_aac,
        }
        with open(f"{work_dir}/probe_data.json", "w", encoding="utf-8") as f:
            json.dump(probe_data, f)

        volume.commit()

        print(f"[TIMING_LOG] [{video_id}] download_stage Ayrıntılı Süre Bölünmesi:")
        print(f"  ├─ 1. Volume Reload: {timing_breakdown['volume_reload_sec']}s")
        print(f"  ├─ 2. Ön Hazırlık/Kontroller: {timing_breakdown['pre_checks_sec']}s")
        print(f"  ├─ 3. aria2c İndirme: {timing_breakdown['aria2c_download_sec']}s")
        print(f"  ├─ 4. ffprobe Analizi: {timing_breakdown['ffprobe_analysis_sec']}s")
        print(f"  ├─ 5. Volume Commit (FUSE Diske Yazma): {timing_breakdown['volume_commit_sec']}s")
        print(f"  └─ TOTAL Konteyner Execution: {stage_exec_sec}s")

        dur_int = int(probe_dur)
        mins, secs = divmod(dur_int, 60)
        hours, mins = divmod(mins, 60)
        dur_formatted = f"{hours:02d}:{mins:02d}:{secs:02d}"

        video_details = {
            "original_resolution": f"{probe_width}x{probe_height}",
            "duration_seconds": round(probe_dur, 2),
            "duration_formatted": dur_formatted,
            "input_codec": probe_codec,
            "has_audio": probe_has_audio,
            "aac_passthrough": probe_is_aac if probe_has_audio else False,
        }

        tracker.send_event(step="download_completed", progress=10, extra={
            "download_progress": 100,
            "download_duration_seconds": dl_duration,
            "download_speed_mbps": dl_speed_mbps,
            "video_details": video_details,
            "perf_stats": build_accumulated_perf_stats(work_dir, start_time)
        })

        conv_spawn_time = time.time()

        if gpu_mode == "auto":
            if probe_dur >= 1800 or probe_height >= 1440:
                use_gpu = True
                print(f"[{video_id}] Auto-GPU: GPU seçildi (Süre: {probe_dur:.0f}s >= 1800s veya Çözünürlük: {probe_height}p >= 1440p)")
            else:
                use_gpu = False
                print(f"[{video_id}] Auto-GPU: CPU seçildi (Süre: {probe_dur:.0f}s < 1800s, Çözünürlük: {probe_height}p)")
        else:
            use_gpu = (gpu_mode == "gpu")

        if use_gpu:
            from ..config import STAGE_CFG_ENCODE_GPU, GPU_RESOURCE_MAP
            if requested_gpu_type and isinstance(requested_gpu_type, str) and requested_gpu_type.strip():
                selected_gpu = requested_gpu_type.strip().upper()
                print(f"[{video_id}] Özel GPU Tipi İstendi: {selected_gpu}")
            elif probe_height >= 2160 or probe_dur >= 180:
                selected_gpu = "L4"
                print(f"[{video_id}] Akıllı GPU Katmanı: 4K/8K veya 3+ Dk Uzun Video İçin L4 GPU Seçildi (Çözünürlük: {probe_height}p, Süre: {probe_dur:.0f}s)")
            else:
                selected_gpu = STAGE_CFG_ENCODE_GPU.get("gpu", "T4")
                print(f"[{video_id}] Akıllı GPU Katmanı: Standart Kısa Video İçin {selected_gpu} GPU Seçildi (Çözünürlük: {probe_height}p, Süre: {probe_dur:.0f}s)")

            gpu_res = GPU_RESOURCE_MAP.get(selected_gpu, {"cpu": STAGE_CFG_ENCODE_GPU.get("cpu", 2.0), "memory": STAGE_CFG_ENCODE_GPU.get("memory", 8192)})
            gpu_cpu = float(gpu_res["cpu"])
            gpu_mem = int(gpu_res["memory"])

            vol_sub = volume.with_mount_options(sub_path=f"/{video_id}")
            print(f"[{video_id}] Dynamic GPU Kaynak Ataması: {selected_gpu} GPU ({gpu_cpu} vCPU, {gpu_mem} MB RAM)")
            gpu_process_stage.with_options(volumes={"/vol": vol_sub}, gpu=selected_gpu, cpu=gpu_cpu, memory=gpu_mem).spawn(video_url, webhook_url, video_id, custom_id, username, server_config, start_time, requested_qualities, allocated_cpu=gpu_cpu, stage_spawn_time=conv_spawn_time)
        else:
            vol_sub = volume.with_mount_options(sub_path=f"/{video_id}")
            q_count = len(requested_qualities) if requested_qualities else 3
            optimal_cpu = calc_optimal_cpu(probe_height, probe_dur, q_count, max_cpu=STAGE_CFG_ENCODE_CPU["cpu"])
            print(f"[{video_id}] Dinamik CPU Hesaplandı: {optimal_cpu} vCPU (Çözünürlük: {probe_height}p, Süre: {probe_dur:.0f}s, Kaliteler: {q_count})")
            cpu_process_stage.with_options(volumes={"/vol": vol_sub}, cpu=optimal_cpu).spawn(video_url, webhook_url, video_id, custom_id, username, server_config, start_time, requested_qualities, stage_spawn_time=conv_spawn_time)

    except TaskCancelledOrTimeout as c_err:
        elapsed_sec = round(time.time() - start_time, 2)
        print(f"[{video_id}] İptal algılandı: {c_err}")
        tracker.send_event(step="cancelled", status="cancelled", extra={
            "message": "İndirme aşamasında işlem kullanıcı tarafından durduruldu.",
            "elapsed_time_seconds": elapsed_sec,
            "perf_stats": build_accumulated_perf_stats(work_dir, start_time)
        })
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
            volume.commit()
    except BaseException as e:
        elapsed_sec = round(time.time() - start_time, 2)
        detailed_error = f"{type(e).__name__}: {str(e)}"
        print(f"[{video_id}] İndirme Hatası:\n{traceback.format_exc()}")
        tracker.send_event(step="failed", status="failed", extra={
            "error": detailed_error,
            "message": f"İndirme aşamasında hata: {detailed_error}",
            "elapsed_time_seconds": elapsed_sec,
            "processing_time": f"{elapsed_sec}s",
            "perf_stats": build_accumulated_perf_stats(work_dir, start_time)
        })
    finally:
        if not os.path.exists(f"{work_dir}/input.mp4") and os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
            volume.commit()
