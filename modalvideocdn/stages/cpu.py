import os
import subprocess
import concurrent.futures
import traceback
import shutil
import time
import json

from ..config import app, volume, WATERMARK_POSITIONS
from ..core import (
    image_cpu,
    ProgressTracker,
    setup_cancellation_and_timeout_handlers,
    generate_timeline_sprite_and_vtt,
    generate_metadata_and_poster,
    calc_target_dim,
)
from .upload import upload_stage


@app.function(image=image_cpu, cpu=8.0, timeout=1800, volumes={"/vol": volume})
def cpu_process_stage(
    video_url: str, webhook_url: str, video_id: str, custom_id: str,
    username: str, server_config: dict, start_time: float,
    requested_qualities: list = None
):
    work_dir = f"/vol/{video_id}"
    input_file = f"{work_dir}/input.mp4"
    tracker = ProgressTracker(webhook_url, video_id, custom_id)
    setup_cancellation_and_timeout_handlers(tracker, start_time, work_dir)

    try:
        volume.reload()

        print(f"[{video_id}] 2. Video bilgileri tespit ediliyor (8x vCPU Modu)...")
        probe_res = subprocess.run([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration:stream=width,height,codec_name,codec_type",
            "-of", "json", input_file
        ], capture_output=True, text=True)

        in_width, in_height = 1920, 1080
        total_duration = 0.0
        has_audio = False
        is_aac_audio = False

        if probe_res.returncode == 0 and probe_res.stdout.strip():
            try:
                data = json.loads(probe_res.stdout)
                if "streams" in data:
                    for stream in data["streams"]:
                        if stream.get("codec_type") == "video" and in_width == 1920 and in_height == 1080:
                            in_width = int(stream.get("width", 1920))
                            in_height = int(stream.get("height", 1080))
                        elif stream.get("codec_type") == "audio":
                            has_audio = True
                            if stream.get("codec_name") == "aac":
                                is_aac_audio = True
                if "format" in data and "duration" in data["format"]:
                    total_duration = float(data["format"]["duration"])
            except Exception:
                pass

        print(f"[{video_id}] Çözünürlük: {in_width}x{in_height}, Süre: {total_duration:.2f}s, Ses Var: {has_audio}, AAC Passthrough: {is_aac_audio}")

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

        print(f"[{video_id}] 3. libx264 CPU HLS dönüştürme başlatılıyor (Kaliteler: {target_qualities}, Bağımsız Tek Ses: {has_audio})...")
        tracker.send_event(step="conversion_started", progress=15, extra={
            "target_qualities": target_qualities, "engine": "CPU (8x vCPU Superfast HQ)", "encrypted": has_encryption
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

        # Video varyantları için vCPU çekirdeklerini (8 çekirdek) çakışmayacak şekilde bölüyoruz
        # 3 profil için profil başına 2 thread (toplam 6 thread + 2 filter thread = 8 vCPU tam uyum)
        threads_per_stream = max(2, int(8 / max(1, n)))

        for idx, p in enumerate(active_profiles):
            variant_dir = f"{work_dir}/{p['name']}"
            os.makedirs(variant_dir, exist_ok=True)
            variant_m3u8 = f"{variant_dir}/index.m3u8"

            stream_args = [
                "-map", f"[v{idx}]",
                "-threads", str(threads_per_stream),
                "-pix_fmt", "yuv420p",
                "-c:v", "libx264", "-crf", p["crf"],
                "-b:v", p["bitrate"], "-maxrate", p["maxrate"], "-bufsize", p["bufsize"],
                "-preset", "superfast",
                "-x264-params", f"threads={threads_per_stream}:sliced-threads=1",
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
            audio_dir = f"{work_dir}/audio"
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

        proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout_cpu, stderr_cpu = proc.communicate()

        if proc.returncode != 0:
            print(f"[{video_id}] FFmpeg CPU Stderr:\n{stderr_cpu}")
            error_tail = stderr_cpu.strip()[-400:] if stderr_cpu else "Bilinmeyen Hata"
            raise Exception(f"FFmpeg CPU Single-Pass Hatası: {error_tail}")

        check_dirs = [p["name"] for p in active_profiles]
        if has_audio:
            check_dirs.append("audio")

        for dir_name in check_dirs:
            variant_dir = f"{work_dir}/{dir_name}"
            if os.path.exists(variant_dir):
                for filename in os.listdir(variant_dir):
                    if filename.endswith(".ts"):
                        old_path = os.path.join(variant_dir, filename)
                        new_path = os.path.join(variant_dir, filename[:-3] + ".jpg")
                        os.rename(old_path, new_path)

            variant_m3u8 = f"{variant_dir}/index.m3u8"
            if os.path.exists(variant_m3u8):
                with open(variant_m3u8, "r") as f:
                    m3u8_content = f.read()
                m3u8_content = m3u8_content.replace(".ts", ".jpg")
                with open(variant_m3u8, "w") as f:
                    f.write(m3u8_content)
            if dir_name != "audio":
                tracker.record_variant_completed(dir_name, 85)

        generate_timeline_sprite_and_vtt(work_dir, input_file, total_duration)
        tracker.send_event(step="conversion_completed", progress=85)

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

        if os.path.exists(input_file):
            os.remove(input_file)
        volume.commit()
        upload_stage.spawn(video_url, webhook_url, video_id, custom_id, username, server_config, start_time, target_qualities)

    except BaseException as e:
        elapsed_sec = round(time.time() - start_time, 2)
        detailed_error = f"{type(e).__name__}: {str(e)}"
        print(f"[{video_id}] CPU Dönüştürme Hatası:\n{traceback.format_exc()}")
        tracker.send_event(step="failed", status="failed", extra={
            "error": detailed_error,
            "message": f"CPU dönüştürme hatası: {detailed_error}",
            "elapsed_time_seconds": elapsed_sec, "processing_time": f"{elapsed_sec}s"
        })
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
            volume.commit()
