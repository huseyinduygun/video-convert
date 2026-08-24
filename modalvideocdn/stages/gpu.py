import time
container_proc_start_time = time.time()

import os
import subprocess
import traceback
import shutil
import json

from ..config import app, volume, WATERMARK_POSITIONS, STAGE_CFG_ENCODE_GPU
from ..core import (
    image_gpu,
    ProgressTracker,
    setup_cancellation_and_timeout_handlers,
    generate_timeline_sprite_and_vtt,
    generate_metadata_and_poster,
    calc_target_dim,
    get_container_allocated_cpu,
    check_and_raise_cancellation,
    TaskCancelledOrTimeout,
    build_accumulated_perf_stats,
)
from .upload import upload_stage


@app.function(image=image_gpu, volumes={"/vol": volume}, **STAGE_CFG_ENCODE_GPU)
def gpu_process_stage(
    video_url: str, webhook_url: str, video_id: str, custom_id: str,
    username: str, server_config: dict, start_time: float,
    requested_qualities: list = None, allocated_cpu: float = None,
    stage_spawn_time: float = None
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
        input_pix_fmt = "yuv420p"

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
                input_pix_fmt = pd.get("pix_fmt", "yuv420p")
                print(f"[{video_id}] probe_data.json okundu: {in_width}x{in_height}, {total_duration:.2f}s, codec={input_codec}, ses={has_audio}")
            except Exception:
                pass

        if total_duration == 0.0:
            # Fallback: probe_data.json yoksa veya okunamazsa ffprobe çalıştır
            print(f"[{video_id}] probe_data.json bulunamadı, ffprobe fallback çalışıyor...")
            probe_res = subprocess.run([
                "ffprobe", "-v", "error",
                "-analyzeduration", "5000000", "-probesize", "10000000",
                "-show_entries", "format=duration:stream=width,height,codec_name,codec_type,pix_fmt",
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
                            input_pix_fmt = stream.get("pix_fmt", "yuv420p")
                        elif stream.get("codec_type") == "audio":
                            has_audio = True
                            if stream.get("codec_name") == "aac":
                                is_aac_audio = True
                    if "format" in data and "duration" in data["format"]:
                        total_duration = float(data["format"]["duration"])
                except Exception:
                    pass

        CUVID_MAP = {
            "hevc": "hevc_cuvid",
            "h264": "h264_cuvid",
            "vp9":  "vp9_cuvid",
            "av1":  "av1_cuvid",
        }
        cuvid_decoder = CUVID_MAP.get(input_codec.lower(), None)
        use_hw_decode = cuvid_decoder is not None
        print(f"[{video_id}] Codec: {input_codec}, PixFmt: {input_pix_fmt}, HW Decoder: {cuvid_decoder or 'software'}")
        print(f"[{video_id}] Çözünürlük: {in_width}x{in_height}, Süre: {total_duration:.2f}s, Ses Var: {has_audio}, AAC Passthrough: {is_aac_audio}")
        t_probe_end = time.time()

        profiles = [
            {"name": "360p",  "height": 360,  "bitrate": "600k", "maxrate": "800k",  "bufsize": "1.2M", "audio_bitrate": "96k",  "crf": "27", "bandwidth": 800000},
            {"name": "720p",  "height": 720,  "bitrate": "1.8M", "maxrate": "2.2M",  "bufsize": "3M",   "audio_bitrate": "128k", "crf": "26", "bandwidth": 2200000},
            {"name": "1080p", "height": 1080, "bitrate": "3.2M", "maxrate": "4M",    "bufsize": "5.5M", "audio_bitrate": "128k", "crf": "25", "bandwidth": 4000000},
        ]

        if requested_qualities and isinstance(requested_qualities, list) and len(requested_qualities) > 0:
            req_set = set(q.strip().lower() for q in requested_qualities)
            active_profiles = [p for p in profiles if p["name"].lower() in req_set and in_height >= p["height"]]
        else:
            active_profiles = [p for p in profiles if in_height >= p["height"]]

        if not active_profiles:
            custom_name = f"{in_height}p" if in_height > 0 else "240p"
            active_profiles = [{"name": custom_name, "height": in_height if in_height > 0 else 240,
                                 "bitrate": "400k", "maxrate": "550k", "bufsize": "800k",
                                 "audio_bitrate": "64k", "crf": "28", "bandwidth": 500000}]

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

        gpu_name = "NVIDIA GPU"
        gpu_type_short = "T4"
        try:
            gpu_probe = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True, timeout=2)
            if gpu_probe.returncode == 0 and gpu_probe.stdout.strip():
                gpu_name = gpu_probe.stdout.strip().split("\n")[0]
                for g_k in ["L40S", "A100", "A10", "H100", "L4", "T4"]:
                    if g_k in gpu_name.upper():
                        gpu_type_short = g_k
                        break
        except Exception:
            gpu_name = "NVIDIA T4"
            gpu_type_short = "T4"
        actual_cpu_str = str(allocated_cpu) if allocated_cpu else get_container_allocated_cpu(default_cpu=STAGE_CFG_ENCODE_GPU['cpu'])
        actual_cpu_val = float(actual_cpu_str)
        engine_name = f"GPU ({gpu_name} CUDA NVENC, {actual_cpu_str}x vCPU)"

        print(f"[{video_id}] 3. {engine_name} HLS dönüştürme başlatılıyor (Kaliteler: {target_qualities}, Bağımsız Tek Ses: {has_audio})...")
        tracker.send_event(step="conversion_started", progress=15, extra={
            "target_qualities": target_qualities, "engine": engine_name, "encrypted": has_encryption
        })

        ffmpeg_cmd = ["ffmpeg", "-y"]

        if use_hw_decode:
            ffmpeg_cmd.extend([
                "-hwaccel", "cuda",
                "-hwaccel_output_format", "cuda",
                "-c:v", cuvid_decoder,
                "-i", input_file
            ])
        else:
            ffmpeg_cmd.extend([
                "-hwaccel", "cuda",
                "-hwaccel_output_format", "cuda",
                "-i", input_file
            ])

        if has_watermark:
            ffmpeg_cmd.extend(["-i", f"{work_dir}/watermark.png"])

        filter_complex_parts = []
        out_stream_args = []
        n = len(active_profiles)

        top_idx = len(active_profiles) - 1
        top_p = active_profiles[top_idx]

        # PURE GPU VRAM PIPELINE: hevc_cuvid (VRAM) → scale_cuda:format=nv12 (VRAM) → h264_nvenc (VRAM)
        if not has_watermark:
            for idx, p in enumerate(active_profiles):
                filter_complex_parts.append(
                    f"[0:v]scale_cuda=w={p['calc_w']}:h={p['calc_h']}:format=nv12[v{idx}]"
                )
        else:
            for idx, p in enumerate(active_profiles):
                wm_scaled_width = max(40, int(p['calc_w'] * 0.15))
                scaled_wm = f"{work_dir}/{p['name']}_wm.png"
                subprocess.run(["ffmpeg", "-y", "-i", f"{work_dir}/watermark.png",
                                 "-vf", f"scale={wm_scaled_width}:-1", scaled_wm],
                                capture_output=True, check=True)
                filter_complex_parts.append(
                    f"[0:v]scale_cuda=w={p['calc_w']}:h={p['calc_h']}:format=nv12,hwdownload,format=nv12[v{idx}_sdr];"
                    f"[v{idx}_sdr][1:v]overlay={overlay_expr},hwupload[v{idx}]"
                )

        local_out_dir = f"/tmp/out_{video_id}"
        os.makedirs(local_out_dir, exist_ok=True)

        # Video varyantları (Sadece Video, Ses yok)
        for idx, p in enumerate(active_profiles):
            variant_dir = f"{local_out_dir}/{p['name']}"
            os.makedirs(variant_dir, exist_ok=True)
            variant_m3u8 = f"{variant_dir}/index.m3u8"

            stream_args = [
                "-map", f"[v{idx}]",
                "-c:v", "h264_nvenc",
                "-b:v", p["bitrate"], "-maxrate", p["maxrate"], "-bufsize", p["bufsize"],
                "-preset", "p1",
                "-tune", "ll",
                "-rc", "vbr_minqp",
                "-qmin", "18", "-qmax", "28",
                "-g", "120", "-keyint_min", "60",
                "-profile:v", "high", "-level", "4.2",
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

        # Bağımsız Tek Ses Varyantı (Ses sadece 1 KERE işlenir, disk/upload ve işlem tasarrufu)
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

        full_cmd = ffmpeg_cmd + ["-filter_complex", ";".join(filter_complex_parts)] + out_stream_args + ["-progress", "pipe:1", "-nostats"]

        from ..core import ResourceMonitor
        monitor = ResourceMonitor(interval_sec=0.5, is_gpu=True)
        monitor.start()

        print(f"[{video_id}] Executing FFmpeg GPU Command:\n" + " ".join(full_cmd))

        conv_start_time = time.time()
        last_conv_webhook_time = 0.0
        last_sent_conv_prog = -1
        MIN_CONV_INTERVAL_SEC = 5.0
        output_log_tail = []

        import threading
        last_activity_time = [time.time()]
        stagnation_detected = [False]
        INACTIVITY_TIMEOUT_SEC = 45.0  # 45 saniye boyunca hiç çıktı gelmezse kilitlenme kabul et ve otomatik öldür

        def _stagnation_checker():
            while not stagnation_detected[0]:
                time.sleep(2.0)
                if time.time() - last_activity_time[0] > INACTIVITY_TIMEOUT_SEC:
                    stagnation_detected[0] = True
                    print(f"[WATCHDOG] [{video_id}] GPU FFmpeg işlemi {INACTIVITY_TIMEOUT_SEC}s boyunca kilitlendi! Otomatik öldürülüyor...")
                    try:
                        process.kill()
                    except Exception:
                        pass
                    break

        checker_thread = threading.Thread(target=_stagnation_checker, daemon=True)
        checker_thread.start()

        # stderr=subprocess.STDOUT kullanılarak pipe kilitlenmesi (pipe deadlock) %100 engellenir
        process = subprocess.Popen(full_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        try:
            for line in process.stdout:
                last_activity_time[0] = time.time()
                if stagnation_detected[0]:
                    raise Exception(f"FFmpeg kilitlenme zaman aşımı: İşlem {INACTIVITY_TIMEOUT_SEC}s boyunca tepki vermedi.")

                line_str = line.strip()
                if len(output_log_tail) > 50:
                    output_log_tail.pop(0)
                output_log_tail.append(line_str)

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
                    process.kill()
                    raise
        except TaskCancelledOrTimeout:
            process.kill()
            raise
        finally:
            stagnation_detected[0] = True

        process.wait()

        if stagnation_detected[0] and process.returncode != 0:
            raise Exception(f"FFmpeg Kilitlenme Hatası: GPU dönüştürme işlemi {INACTIVITY_TIMEOUT_SEC} saniye boyunca hiç çıktı vermedi ve otomatik durduruldu.")

        if process.returncode != 0:
            full_log = "\n".join(output_log_tail)
            print(f"[{video_id}] FFmpeg Full Output Log:\n{full_log}")
            error_tail = full_log.strip()[-400:] if full_log else "Bilinmeyen Hata"
            raise Exception(f"NVENC GPU Hatası: {error_tail}")

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
            print(f"[PERF_WARNING] [{video_id}] NVENC GPU kodlama hızı düşük ({realtime_speed_ratio}x) - Olası CPU/Disk darboğazı!")

        # Gerçek zamanlı verimlilik oranını engine_name'e dahil et
        efficiency_note = "HQ" if realtime_speed_ratio >= 5.0 else ("OK" if realtime_speed_ratio >= 2.0 else "LOW")
        engine_name = engine_name.rstrip(")") + f" | {realtime_speed_ratio}x realtime [{efficiency_note}])"

        dur_int = int(total_duration)
        mins, secs = divmod(dur_int, 60)
        hours, mins = divmod(mins, 60)
        dur_formatted = f"{hours:02d}:{mins:02d}:{secs:02d}"

        stage_exec_sec = round(time.time() - stage_func_start_time, 2)
        conv_perf_data = {
            "engine": engine_name,
            "gpu_type": gpu_type_short,
            "allocated_cpu": actual_cpu_val,
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

        check_dirs = [p["name"] for p in active_profiles]
        if has_audio:
            check_dirs.append("audio")

        for dir_name in check_dirs:
            if dir_name != "audio":
                tracker.record_variant_completed(dir_name, 85)

        t_post_start = time.time()
        generate_timeline_sprite_and_vtt(work_dir, input_file, total_duration)
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
            "post_processing_sec": round(t4 - t_post_start, 3),
            "volume_commit_sec": round(t5 - t4, 3),
            "stage_total_execution_sec": stage_exec_sec
        }

        conv_perf_data["stage_execution_time_sec"] = stage_exec_sec
        conv_perf_data["timing_breakdown"] = timing_breakdown

        with open(f"{work_dir}/perf_conversion.json", "w", encoding="utf-8") as f:
            json.dump(conv_perf_data, f)
        volume.commit()

        print(f"[TIMING_LOG] [{video_id}] gpu_process_stage NVENC Kodlaması Bitti. GPU Anında Kapatılıyor!")
        print(f"  ├─ 1. Volume Reload: {timing_breakdown['volume_reload_sec']}s")
        print(f"  ├─ 2. Probe Read (JSON): {timing_breakdown['probe_read_sec']}s")
        print(f"  ├─ 3. FFmpeg GPU NVENC Dönüştürme: {timing_breakdown['ffmpeg_conversion_sec']}s")
        print(f"  ├─ 4. Volume Commit: {timing_breakdown['volume_commit_sec']}s")
        print(f"  └─ TOTAL GPU Konteyner Execution: {stage_exec_sec}s")

        tracker.send_event(step="conversion_completed", progress=85, extra={
            "conversion_duration_seconds": conv_duration,
            "realtime_speed_ratio": f"{realtime_speed_ratio}x",
            "perf_stats": build_accumulated_perf_stats(work_dir, start_time)
        })

        upload_spawn_time = time.time()
        vol_sub = volume.with_mount_options(sub_path=f"/{video_id}")
        upload_stage.with_options(volumes={"/vol": vol_sub}).spawn(video_url, webhook_url, video_id, custom_id, username, server_config, start_time, target_qualities, stage_spawn_time=upload_spawn_time)
        return

    except TaskCancelledOrTimeout as c_err:
        elapsed_sec = round(time.time() - start_time, 2)
        print(f"[{video_id}] İptal algılandı: {c_err}")
        tracker.send_event(step="cancelled", status="cancelled", extra={
            "message": "GPU dönüştürme aşamasında işlem kullanıcı tarafından durduruldu.",
            "elapsed_time_seconds": elapsed_sec,
            "perf_stats": build_accumulated_perf_stats(work_dir, start_time)
        })
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
            volume.commit()
    except BaseException as e:
        elapsed_sec = round(time.time() - start_time, 2)
        detailed_error = f"{type(e).__name__}: {str(e)}"
        print(f"[{video_id}] GPU Dönüştürme Hatası:\n{traceback.format_exc()}")
        tracker.send_event(step="failed", status="failed", extra={
            "error": detailed_error,
            "message": f"GPU dönüştürme hatası: {detailed_error}",
            "elapsed_time_seconds": elapsed_sec, "processing_time": f"{elapsed_sec}s",
            "perf_stats": build_accumulated_perf_stats(work_dir, start_time)
        })
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
            volume.commit()
