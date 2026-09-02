import time
container_proc_start_time = time.time()

import os
import subprocess
import concurrent.futures
import traceback
import shutil
import json

from ..config import app, volume, WATERMARK_POSITIONS, STAGE_CFG_ENCODE_CPU
from ..core import (
    image_cpu,
    ProgressTracker,
    setup_cancellation_and_timeout_handlers,
    generate_timeline_sprite_and_vtt,
    generate_smart_posters,
    generate_metadata_and_poster,
    calc_target_dim,
    get_container_allocated_cpu,
    check_and_raise_cancellation,
    TaskCancelledOrTimeout,
    build_accumulated_perf_stats,
)
from .upload import upload_stage


@app.function(image=image_cpu, volumes={"/vol": volume}, **STAGE_CFG_ENCODE_CPU)
def cpu_process_stage(
    video_url: str, webhook_url: str, video_id: str, custom_id: str,
    username: str, server_config: dict, start_time: float,
    requested_qualities: list = None, stage_spawn_time: float = None
):
    stage_func_start_time = container_proc_start_time
    base_start_time = stage_spawn_time or stage_func_start_time
    work_dir = f"/vol/{video_id}"
    input_file = f"{work_dir}/input.mp4"
    tracker = ProgressTracker(webhook_url, video_id, custom_id)
    setup_cancellation_and_timeout_handlers(tracker, start_time, work_dir)

    t0 = time.time()
    try:
        volume.reload()
        t1 = time.time()

        print(f"[{video_id}] 2. Video bilgileri okunuyor (download stage probe_data.json)...")

        in_width, in_height = 1920, 1080
        total_duration = 0.0
        has_audio = False
        is_aac_audio = False
        input_codec = "h264"

        probe_data_file = f"{work_dir}/probe_data.json"
        if os.path.exists(probe_data_file):
            try:
                with open(probe_data_file, "r") as f:
                    pd = json.load(f)
                in_width = int(pd.get("width", 1920))
                in_height = int(pd.get("height", 1080))
                total_duration = float(pd.get("duration", 0.0))
                input_codec = pd.get("codec", "h264")
                has_audio = bool(pd.get("has_audio", False))
                is_aac_audio = bool(pd.get("is_aac", False))
                print(f"[{video_id}] probe_data.json okundu: {in_width}x{in_height}, {total_duration:.2f}s, codec={input_codec}, ses={has_audio}")
            except Exception:
                pass

        if total_duration == 0.0:
            # Fallback: probe_data.json yoksa veya okunamazsa ffprobe çalıştır
            print(f"[{video_id}] probe_data.json bulunamadı, ffprobe fallback çalışıyor...")
            probe_res = subprocess.run([
                "ffprobe", "-v", "error",
                "-analyzeduration", "5000000", "-probesize", "10000000",
                "-show_entries", "format=duration:stream=width,height,codec_name,codec_type",
                "-of", "json", input_file
            ], capture_output=True, text=True)

            if probe_res.returncode == 0 and probe_res.stdout.strip():
                try:
                    data = json.loads(probe_res.stdout)
                    for stream in data.get("streams", []):
                        if stream.get("codec_type") == "video" and in_width == 1920 and in_height == 1080:
                            in_width = int(stream.get("width", 1920))
                            in_height = int(stream.get("height", 1080))
                            input_codec = stream.get("codec_name", "h264")
                        elif stream.get("codec_type") == "audio":
                            has_audio = True
                            if stream.get("codec_name") == "aac":
                                is_aac_audio = True
                    if "format" in data and "duration" in data["format"]:
                        total_duration = float(data["format"]["duration"])
                except Exception:
                    pass

        print(f"[{video_id}] Çözünürlük: {in_width}x{in_height}, Süre: {total_duration:.2f}s, Ses Var: {has_audio}, AAC Passthrough: {is_aac_audio}")
        t_probe_end = time.time()

        profiles = [
            {"name": "360p",  "height": 360,  "bitrate": "800k",  "maxrate": "1M",   "bufsize": "1.5M", "audio_bitrate": "96k",  "crf": "26", "bandwidth": 1000000},
            {"name": "720p",  "height": 720,  "bitrate": "2.5M",  "maxrate": "3M",   "bufsize": "4.5M", "audio_bitrate": "128k", "crf": "24", "bandwidth": 3000000},
            {"name": "1080p", "height": 1080, "bitrate": "4.5M",  "maxrate": "5.5M", "bufsize": "8M",   "audio_bitrate": "128k", "crf": "23", "bandwidth": 5500000},
        ]

        if requested_qualities and isinstance(requested_qualities, list) and len(requested_qualities) > 0:
            req_set = set(q.strip().lower() for q in requested_qualities)
            active_profiles = [p for p in profiles if p["name"].lower() in req_set and in_height >= p["height"]]
        else:
            active_profiles = [p for p in profiles if in_height >= p["height"]]

        if not active_profiles:
            custom_name = f"{in_height}p" if in_height > 0 else "240p"
            active_profiles = [{"name": custom_name, "height": in_height if in_height > 0 else 240,
                                 "bitrate": "500k", "maxrate": "700k", "bufsize": "1M",
                                 "audio_bitrate": "64k", "crf": "27", "bandwidth": 700000}]

        for p in active_profiles:
            w, h = calc_target_dim(in_width, in_height, p["height"])
            p["calc_w"] = w
            p["calc_h"] = h
            p["calc_res_str"] = f"{w}x{h}"

        target_qualities = [p["name"] for p in active_profiles]

        has_watermark = os.path.exists(f"{work_dir}/watermark.png")
        wm_pos_code = "rt"
        if has_watermark and os.path.exists(f"{work_dir}/watermark_pos.txt"):
            with open(f"{work_dir}/watermark_pos.txt", "r") as wf:
                wm_pos_code = wf.read().strip().lower()
        overlay_expr = WATERMARK_POSITIONS.get(wm_pos_code, WATERMARK_POSITIONS["rt"])
        has_encryption = os.path.exists(f"{work_dir}/enc.keyinfo")

        alloc_cpu = get_container_allocated_cpu(default_cpu=STAGE_CFG_ENCODE_CPU["cpu"])
        engine_name = f"CPU ({alloc_cpu}x vCPU libx264 superfast HQ)"

        print(f"[{video_id}] 3. libx264 CPU HLS dönüştürme başlatılıyor (Kaliteler: {target_qualities}, Bağımsız Tek Ses: {has_audio})...")
        tracker.send_event(step="conversion_started", progress=15, extra={
            "target_qualities": target_qualities, "engine": engine_name, "encrypted": has_encryption
        })

        ffmpeg_cmd = ["ffmpeg", "-y", "-i", input_file]
        if has_watermark:
            ffmpeg_cmd.extend(["-i", f"{work_dir}/watermark.png"])

        filter_complex_parts = []
        out_stream_args = []
        n = len(active_profiles)

        if not has_watermark:
            if n == 1:
                p = active_profiles[0]
                filter_complex_parts.append(f"[0:v]scale={p['calc_w']}:{p['calc_h']},format=yuv420p[v0]")
            else:
                filter_complex_parts.append(f"[0:v]split={n}" + "".join(f"[s{i}]" for i in range(n)))
                for idx, p in enumerate(active_profiles):
                    filter_complex_parts.append(f"[s{idx}]scale={p['calc_w']}:{p['calc_h']},format=yuv420p[v{idx}]")
        else:
            if n == 1:
                p = active_profiles[0]
                wm_scaled_width = max(40, int(p['calc_w'] * 0.15))
                scaled_wm = f"{work_dir}/wm_scaled.png"
                subprocess.run(["ffmpeg", "-y", "-i", f"{work_dir}/watermark.png",
                                 "-vf", f"scale={wm_scaled_width}:-1", scaled_wm],
                                capture_output=True, check=True)
                filter_complex_parts.append(f"[0:v]scale={p['calc_w']}:{p['calc_h']},format=yuv420p[main0];[main0][1:v]overlay={overlay_expr},format=yuv420p[v0]")
            else:
                filter_complex_parts.append(f"[0:v]split={n}" + "".join(f"[s{i}]" for i in range(n)))
                for idx, p in enumerate(active_profiles):
                    wm_scaled_width = max(40, int(p['calc_w'] * 0.15))
                    scaled_wm = f"{work_dir}/{p['name']}_wm.png"
                    subprocess.run(["ffmpeg", "-y", "-i", f"{work_dir}/watermark.png",
                                     "-vf", f"scale={wm_scaled_width}:-1", scaled_wm],
                                    capture_output=True, check=True)
                    filter_complex_parts.append(
                        f"[s{idx}]scale={p['calc_w']}:{p['calc_h']},format=yuv420p[main{idx}];[main{idx}][1:v]overlay={overlay_expr},format=yuv420p[v{idx}]"
                    )

        alloc_cpu_num = float(get_container_allocated_cpu(default_cpu=STAGE_CFG_ENCODE_CPU["cpu"]))
        threads_per_stream = max(2, int(alloc_cpu_num / max(1, n)))

        local_out_dir = f"/tmp/out_{video_id}"
        os.makedirs(local_out_dir, exist_ok=True)

        for idx, p in enumerate(active_profiles):
            variant_dir = f"{local_out_dir}/{p['name']}"
            os.makedirs(variant_dir, exist_ok=True)
            variant_m3u8 = f"{variant_dir}/index.m3u8"

            stream_args = [
                "-map", f"[v{idx}]",
                "-threads", str(threads_per_stream),
                "-pix_fmt", "yuv420p",
                "-c:v", "libx264", "-crf", p["crf"],
                "-b:v", p["bitrate"], "-maxrate", p["maxrate"], "-bufsize", p["bufsize"],
                "-preset", "superfast",
                "-x264-params", f"threads={threads_per_stream}:sliced-threads=0",
                "-g", "120", "-keyint_min", "60",
                "-an",
                "-hls_time", "6",
                "-hls_playlist_type", "vod",
                "-hls_segment_filename", f"{variant_dir}/segment_%03d.jpg",
                "-hls_flags", "independent_segments",
            ]

            if has_encryption:
                stream_args.extend(["-hls_key_info_file", f"{work_dir}/enc.keyinfo"])

            stream_args.append(variant_m3u8)
            out_stream_args.extend(stream_args)

        # Bağımsız Tek Ses İzini İşle (Tek geçişte aynı anda)
        if has_audio:
            audio_dir = f"{local_out_dir}/audio"
            os.makedirs(audio_dir, exist_ok=True)
            audio_m3u8 = f"{audio_dir}/index.m3u8"

            audio_codec_args = ["-c:a", "copy"] if is_aac_audio else ["-c:a", "aac", "-b:a", "128k", "-ac", "2"]

            audio_stream_args = [
                "-map", "0:a:0",
                "-vn",
            ] + audio_codec_args + [
                "-hls_time", "6",
                "-hls_playlist_type", "vod",
                "-hls_segment_filename", f"{audio_dir}/segment_%03d.jpg",
                "-hls_flags", "independent_segments",
            ]

            if has_encryption:
                audio_stream_args.extend(["-hls_key_info_file", f"{work_dir}/enc.keyinfo"])

            audio_stream_args.append(audio_m3u8)
            out_stream_args.extend(audio_stream_args)

        filter_complex_str = ";".join(filter_complex_parts)
        ffmpeg_cmd.extend(["-filter_complex", filter_complex_str])
        ffmpeg_cmd.extend(out_stream_args)
        ffmpeg_cmd.extend(["-progress", "pipe:1", "-nostats"])

        print(f"[{video_id}] Executing FFmpeg Single-Pass CPU Command:\n" + " ".join(ffmpeg_cmd))

        from ..core import ResourceMonitor
        monitor = ResourceMonitor(interval_sec=0.5, is_gpu=False)
        monitor.start()

        conv_start_time = time.time()
        last_conv_webhook_time = 0.0
        last_sent_conv_prog = -1
        MIN_CONV_INTERVAL_SEC = 5.0
        output_log_tail_cpu = []

        import threading
        last_activity_time_cpu = [time.time()]
        stagnation_detected_cpu = [False]
        INACTIVITY_TIMEOUT_SEC = 45.0  # 45 saniye boyunca hiç çıktı gelmezse kilitlenme kabul et ve otomatik öldür

        def _stagnation_checker_cpu():
            while not stagnation_detected_cpu[0]:
                time.sleep(2.0)
                if time.time() - last_activity_time_cpu[0] > INACTIVITY_TIMEOUT_SEC:
                    stagnation_detected_cpu[0] = True
                    print(f"[WATCHDOG] [{video_id}] CPU FFmpeg işlemi {INACTIVITY_TIMEOUT_SEC}s boyunca kilitlendi! Otomatik öldürülüyor...")
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    break

        checker_thread_cpu = threading.Thread(target=_stagnation_checker_cpu, daemon=True)
        checker_thread_cpu.start()

        proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        try:
            for line in proc.stdout:
                last_activity_time_cpu[0] = time.time()
                if stagnation_detected_cpu[0]:
                    raise Exception(f"FFmpeg kilitlenme zaman aşımı: İşlem {INACTIVITY_TIMEOUT_SEC}s boyunca tepki vermedi.")

                line_str = line.strip()
                if len(output_log_tail_cpu) > 50:
                    output_log_tail_cpu.pop(0)
                output_log_tail_cpu.append(line_str)

                if line_str.startswith("out_time_us="):
                    try:
                        us = int(line_str.split("=")[1])
                        sec = us / 1_000_000.0
                        if total_duration > 0:
                            pct = min(100.0, (sec / total_duration) * 100.0)
                            prog = 15 + int(pct * 0.70)
                            now = time.time()
                            if (now - last_conv_webhook_time >= MIN_CONV_INTERVAL_SEC and prog != last_sent_conv_prog) or (prog >= 85 and last_sent_conv_prog < 85):
                                tracker.send_event(step="converting", progress=prog)
                                last_conv_webhook_time = now
                                last_sent_conv_prog = prog
                    except TaskCancelledOrTimeout:
                        raise
                    except Exception:
                        pass
                try:
                    check_and_raise_cancellation(video_id, work_dir)
                except TaskCancelledOrTimeout:
                    proc.kill()
                    raise
        except TaskCancelledOrTimeout:
            proc.kill()
            raise
        finally:
            stagnation_detected_cpu[0] = True

        proc.wait()

        if stagnation_detected_cpu[0] and proc.returncode != 0:
            raise Exception(f"FFmpeg Kilitlenme Hatası: CPU dönüştürme işlemi {INACTIVITY_TIMEOUT_SEC} saniye boyunca hiç çıktı vermedi ve otomatik durduruldu.")

        if proc.returncode != 0:
            full_log_cpu = "\n".join(output_log_tail_cpu)
            print(f"[{video_id}] FFmpeg CPU Full Output Log:\n{full_log_cpu}")
            error_tail = full_log_cpu.strip()[-400:] if full_log_cpu else "Bilinmeyen Hata"
            raise Exception(f"FFmpeg CPU Single-Pass Hatası: {error_tail}")

        if os.path.exists(local_out_dir):
            for item in os.listdir(local_out_dir):
                shutil.move(os.path.join(local_out_dir, item), os.path.join(work_dir, item))
            shutil.rmtree(local_out_dir, ignore_errors=True)

        t3 = time.time()
        conv_duration = round(t3 - conv_start_time, 2)
        resource_usage = monitor.stop() if monitor else {}
        realtime_speed_ratio = round(total_duration / max(0.1, conv_duration), 2) if total_duration > 0 else 0.0
        bottleneck_detected = bool(realtime_speed_ratio > 0 and realtime_speed_ratio < 1.2)

        if bottleneck_detected:
            print(f"[PERF_WARNING] [{video_id}] CPU kodlama hızı düşük ({realtime_speed_ratio}x) - Olası CPU/Disk darboğazı!")

        # Dinamik CPU sayısı (MODAL_CPUS env var) + gerçek zamanlı verimlilik oranı
        alloc_cpu = get_container_allocated_cpu(default_cpu=STAGE_CFG_ENCODE_CPU["cpu"])
        efficiency_note = "HQ" if realtime_speed_ratio >= 3.0 else ("OK" if realtime_speed_ratio >= 1.5 else "LOW")
        engine_name = f"CPU ({alloc_cpu}x vCPU libx264 superfast | {realtime_speed_ratio}x realtime [{efficiency_note}])"

        dur_int = int(total_duration)
        mins, secs = divmod(dur_int, 60)
        hours, mins = divmod(mins, 60)
        dur_formatted = f"{hours:02d}:{mins:02d}:{secs:02d}"

        stage_exec_sec = round(time.time() - stage_func_start_time, 2)
        conv_perf_data = {
            "engine": engine_name,
            "allocated_cpu": float(alloc_cpu),
            "conversion_time_sec": conv_duration,
            "stage_execution_time_sec": stage_exec_sec,
            "realtime_speed_ratio": f"{realtime_speed_ratio}x",
            "video_duration_sec": round(total_duration, 2),
            "bottleneck_detected": bottleneck_detected,
            "resource_usage": resource_usage,
            "video_details": {
                "original_resolution": f"{in_width}x{in_height}",
                "duration_seconds": round(total_duration, 2),
                "duration_formatted": dur_formatted,
                "input_codec": input_codec,
                "has_audio": has_audio,
                "aac_passthrough": is_aac_audio if has_audio else False,
                "watermark_applied": has_watermark,
                "sprite_generated": os.path.exists(f"{work_dir}/enable_sprite.flag"),
                "encrypted": has_encryption,
                "qualities": target_qualities
            }
        }

        with open(f"{work_dir}/perf_conversion.json", "w", encoding="utf-8") as f:
            json.dump(conv_perf_data, f)

        print(f"[PERF_PROFILE] [{video_id}] cpu_process_stage tamamlandı | Süre: {conv_duration}s | Hız Çarpanı: {realtime_speed_ratio}x | Darboğaz: {bottleneck_detected}")

        check_dirs = [p["name"] for p in active_profiles]
        if has_audio:
            check_dirs.append("audio")

        for dir_name in check_dirs:
            if dir_name != "audio":
                tracker.record_variant_completed(dir_name, 85)

        generate_timeline_sprite_and_vtt(work_dir, input_file, total_duration)
        generate_smart_posters(work_dir, input_file, total_duration)
        master_playlist_lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
        if has_audio:
            master_playlist_lines.append('#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio",DEFAULT=YES,AUTOSELECT=YES,URI="audio/index.m3u8"')

        for p in active_profiles:
            audio_attr = ',AUDIO="audio"' if has_audio else ""
            master_playlist_lines.append(f"#EXT-X-STREAM-INF:BANDWIDTH={p['bandwidth']},RESOLUTION={p['calc_res_str']}{audio_attr}")
            master_playlist_lines.append(f"{p['name']}/index.m3u8")

        with open(f"{work_dir}/master.m3u8", "w") as f:
            f.write("\n".join(master_playlist_lines) + "\n")

        generate_metadata_and_poster(work_dir, input_file, video_id, custom_id, username, server_config, in_width, in_height, total_duration, active_profiles)

        t4 = time.time()
        if os.path.exists(input_file):
            os.remove(input_file)
        volume.commit()
        t5 = time.time()

        # Konteyner fonksiyonunun GERÇEK ham çalışma süresini kaydet
        stage_exec_sec = round(t5 - stage_func_start_time, 2)

        timing_breakdown = {
            "volume_reload_sec": round(t1 - t0, 3),
            "probe_read_sec": round(t_probe_end - t1, 3),
            "ffmpeg_conversion_sec": conv_duration,
            "post_processing_sec": round(t4 - t3, 3),
            "volume_commit_sec": round(t5 - t4, 3),
            "stage_total_execution_sec": stage_exec_sec
        }

        conv_perf_data["stage_execution_time_sec"] = stage_exec_sec
        conv_perf_data["timing_breakdown"] = timing_breakdown

        with open(f"{work_dir}/perf_conversion.json", "w", encoding="utf-8") as f:
            json.dump(conv_perf_data, f)
        volume.commit()

        print(f"[TIMING_LOG] [{video_id}] cpu_process_stage Ayrıntılı Süre Bölünmesi:")
        print(f"  ├─ 1. Volume Reload: {timing_breakdown['volume_reload_sec']}s")
        print(f"  ├─ 2. Probe Read (JSON): {timing_breakdown['probe_read_sec']}s")
        print(f"  ├─ 3. FFmpeg Dönüştürme: {timing_breakdown['ffmpeg_conversion_sec']}s")
        print(f"  ├─ 4. Post Processing (Sprite/Master.m3u8): {timing_breakdown['post_processing_sec']}s")
        print(f"  ├─ 5. Volume Commit (FUSE Diske Yazma): {timing_breakdown['volume_commit_sec']}s")
        print(f"  └─ TOTAL Konteyner Execution: {stage_exec_sec}s")

        tracker.send_event(step="conversion_completed", progress=85, extra={
            "conversion_duration_seconds": conv_duration,
            "realtime_speed_ratio": f"{realtime_speed_ratio}x",
            "perf_stats": build_accumulated_perf_stats(work_dir, start_time)
        })

        upload_spawn_time = time.time()
        vol_sub = volume.with_mount_options(sub_path=f"/{video_id}")
        upload_stage.with_options(volumes={"/vol": vol_sub}).spawn(video_url, webhook_url, video_id, custom_id, username, server_config, start_time, target_qualities, stage_spawn_time=upload_spawn_time)

    except TaskCancelledOrTimeout as c_err:
        elapsed_sec = round(time.time() - start_time, 2)
        print(f"[{video_id}] İptal algılandı: {c_err}")
        tracker.send_event(step="cancelled", status="cancelled", extra={
            "message": "CPU dönüştürme aşamasında işlem kullanıcı tarafından durduruldu.",
            "elapsed_time_seconds": elapsed_sec,
            "perf_stats": build_accumulated_perf_stats(work_dir, start_time)
        })
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
            volume.commit()
    except BaseException as e:
        elapsed_sec = round(time.time() - start_time, 2)
        detailed_error = f"{type(e).__name__}: {str(e)}"
        print(f"[{video_id}] CPU Dönüştürme Hatası:\n{traceback.format_exc()}")
        tracker.send_event(step="failed", status="failed", extra={
            "error": detailed_error,
            "message": f"CPU dönüştürme hatası: {detailed_error}",
            "elapsed_time_seconds": elapsed_sec, "processing_time": f"{elapsed_sec}s",
            "perf_stats": build_accumulated_perf_stats(work_dir, start_time)
        })
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
            volume.commit()
