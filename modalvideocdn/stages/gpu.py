import os
import subprocess
import traceback
import shutil
import time
import json

from ..config import app, volume, WATERMARK_POSITIONS
from ..core import (
    image_gpu,
    ProgressTracker,
    setup_cancellation_and_timeout_handlers,
    generate_timeline_sprite_and_vtt,
    generate_metadata_and_poster,
    calc_target_dim,
)
from .upload import upload_stage


@app.function(image=image_gpu, gpu="T4", cpu=1.0, memory=2048, timeout=1800, scaledown_window=0, volumes={"/vol": volume})
def gpu_process_stage(
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

        print(f"[{video_id}] 2. Video bilgileri tespit ediliyor (NVIDIA T4 GPU Fast NVENC Modu)...")
        probe_res = subprocess.run([
            "ffprobe", "-v", "error",
            "-probesize", "20M", "-analyzeduration", "5000000",
            "-show_entries", "format=duration:stream=width,height,codec_name,codec_type,pix_fmt",
            "-of", "json", input_file
        ], capture_output=True, text=True)

        in_width, in_height = 1920, 1080
        total_duration = 0.0
        has_audio = False
        is_aac_audio = False
        input_codec = "h264"
        input_pix_fmt = "yuv420p"

        if probe_res.returncode == 0 and probe_res.stdout.strip():
            try:
                data = json.loads(probe_res.stdout)
                if "streams" in data:
                    for stream in data["streams"]:
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

        print(f"[{video_id}] 3. NVIDIA T4 GPU Fast NVENC HLS dönüştürme başlatılıyor (Kaliteler: {target_qualities}, Bağımsız Tek Ses: {has_audio})...")
        tracker.send_event(step="conversion_started", progress=15, extra={
            "target_qualities": target_qualities, "engine": "GPU (NVIDIA T4 CUDA NVENC)", "encrypted": has_encryption
        })

        ffmpeg_cmd = ["ffmpeg", "-y"]

        if use_hw_decode:
            ffmpeg_cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-c:v", cuvid_decoder, "-i", input_file])
        else:
            ffmpeg_cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-i", input_file])

        if has_watermark:
            ffmpeg_cmd.extend(["-i", f"{work_dir}/watermark.png"])

        filter_complex_parts = []
        out_stream_args = []
        n = len(active_profiles)

        top_p = active_profiles[-1]
        top_w, top_h = top_p['calc_w'], top_p['calc_h']

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

        # Video varyantları (Sadece Video, Ses yok)
        for idx, p in enumerate(active_profiles):
            variant_dir = f"{work_dir}/{p['name']}"
            os.makedirs(variant_dir, exist_ok=True)
            variant_m3u8 = f"{variant_dir}/index.m3u8"

            stream_args = [
                "-map", f"[v{idx}]",
                "-c:v", "h264_nvenc",
                "-b:v", p["bitrate"], "-maxrate", p["maxrate"], "-bufsize", p["bufsize"],
                "-preset", "p2",
                "-tune", "hq",
                "-rc", "vbr",
                "-cq", "28",
                "-spatial_aq", "1",
                "-temporal_aq", "1",
                "-rc-lookahead", "32",
                "-b_adapt", "1",
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

        print(f"[{video_id}] Executing FFmpeg GPU Command:\n" + " ".join(ffmpeg_cmd))

        process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in process.stdout:
            line = line.strip()
            if line.startswith("out_time_us="):
                try:
                    us = int(line.split("=")[1])
                    sec = us / 1_000_000.0
                    if total_duration > 0:
                        pct = min(100.0, (sec / total_duration) * 100.0)
                        tracker.send_event(step="converting", progress=15 + int(pct * 0.70))
                except Exception:
                    pass

        process.wait()
        stderr_nvenc = process.stderr.read()

        if process.returncode != 0:
            print(f"[{video_id}] FFmpeg Full Stderr:\n{stderr_nvenc}")
            error_tail = stderr_nvenc.strip()[-400:] if stderr_nvenc else "Bilinmeyen Hata"
            raise Exception(f"NVENC GPU Hatası: {error_tail}")

        # Post-Processing: .ts uzantılı kalan dosyaları fiziki olarak .jpg uzantısına çevir & m3u8 güncelle
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

        # Master Playlist — Bağımsız Ses Haritası ile
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
        print(f"[{video_id}] GPU Dönüştürme Hatası:\n{traceback.format_exc()}")
        tracker.send_event(step="failed", status="failed", extra={
            "error": detailed_error,
            "message": f"GPU dönüştürme hatası: {detailed_error}",
            "elapsed_time_seconds": elapsed_sec, "processing_time": f"{elapsed_sec}s"
        })
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
            volume.commit()
