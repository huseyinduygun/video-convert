import argparse
import base64
import concurrent.futures
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from urllib.parse import urlparse, urlunparse

from .config import (
    DEFAULT_PROFILES,
    DEFAULT_TARGET_DIR,
    DEFAULT_WEB_DIR,
    INTERNAL_DOMAIN_IP_MAP,
    MAX_UPLOAD_WORKERS,
    WATERMARK_POSITIONS,
)
from .core.tracker import (
    ProgressTracker,
    TaskCancelledOrTimeout,
    check_and_raise_cancellation,
    setup_cancellation_and_timeout_handlers,
)
from .core.utils import (
    ResourceMonitor,
    build_accumulated_perf_stats,
    build_web_base_url,
    calc_target_dim,
    generate_metadata_and_poster,
    generate_timeline_sprite_and_vtt,
)


def parse_payload() -> dict:
    """Komut satırından veya CircleCI ortam değişkenlerinden dönüştürme parametrelerini ayrıştırır."""
    parser = argparse.ArgumentParser(description="CircleCI Video HLS Converter Runner")
    parser.add_argument("--payload", type=str, help="JSON formatında istek verisi")
    parser.add_argument("--payload-b64", type=str, help="Base64 kodlanmış JSON istek verisi")
    parser.add_argument("--payload-file", type=str, help="İstek JSON dosyası yolu")
    args, _ = parser.parse_known_args()

    data = {}
    if args.payload:
        try:
            data = json.loads(args.payload)
        except Exception as e:
            print(f"[UYARI] --payload JSON ayrıştırma hatası: {e}")
    elif args.payload_b64:
        try:
            decoded = base64.b64decode(args.payload_b64).decode("utf-8")
            data = json.loads(decoded)
        except Exception as e:
            print(f"[UYARI] --payload-b64 ayrıştırma hatası: {e}")
    elif args.payload_file and os.path.exists(args.payload_file):
        try:
            with open(args.payload_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    try:
                        data = json.loads(content)
                    except Exception:
                        data = json.loads(content.replace(r'\"', '"'))
        except Exception as e:
            print(f"[UYARI] --payload-file okuma hatası: {e}")

    # Ortam değişkenlerinden PAYLOAD_JSON veya PAYLOAD_B64 yükle
    if not data:
        env_payload = os.environ.get("PAYLOAD_JSON")
        env_payload_b64 = os.environ.get("PAYLOAD_B64")
        if env_payload:
            try:
                data = json.loads(env_payload)
            except Exception:
                try:
                    data = json.loads(env_payload.replace(r'\"', '"'))
                except Exception:
                    pass
        elif env_payload_b64:
            try:
                decoded = base64.b64decode(env_payload_b64).decode("utf-8")
                data = json.loads(decoded)
            except Exception:
                pass

    if not isinstance(data, dict):
        data = {}

    # Bireysel CircleCI ortam değişkenlerini oku ve eksik alanları doldur / üzerine yaz
    env_mappings = [
        ("video_url", ["VIDEO_URL"]),
        ("webhook_url", ["WEBHOOK_URL"]),
        ("cdn_domain", ["CDN_DOMAIN", "DOMAIN", "CDN_URL"]),
        ("username", ["USERNAME", "USER"]),
        ("custom_id", ["CUSTOM_ID", "ID", "EXTERNAL_ID"]),
        ("video_id", ["VIDEO_ID"]),
        ("storage_host", ["STORAGE_HOST", "SERVER_HOST", "HOST"]),
        ("storage_user", ["STORAGE_USER", "SERVER_USER"]),
        ("storage_pass", ["STORAGE_PASS", "STORAGE_PASSWORD", "SERVER_PASS", "PASSWORD", "PASS"]),
        ("storage_port", ["STORAGE_PORT", "SERVER_PORT", "PORT"]),
        ("target_dir", ["TARGET_DIR", "STORAGE_DIR"]),
        ("web_dir", ["WEB_DIR"]),
        ("poster_url", ["POSTER_URL", "COVER_URL", "THUMBNAIL_URL"]),
        ("watermark_url", ["WATERMARK_URL", "LOGO_URL"]),
        ("watermark_position", ["WATERMARK_POSITION", "LOGO_POSITION"]),
        ("key_url", ["KEY_URL", "KEY_API_URL", "ENCRYPTION_KEY_URL"]),
    ]

    for key, env_names in env_mappings:
        if not data.get(key):
            for env_name in env_names:
                val = os.environ.get(env_name)
                if val is not None and str(val).strip():
                    data[key] = str(val).strip()
                    break

    # Boolean alanlar
    if "sprite" not in data and "enable_sprite" not in data and "vtt" not in data:
        for env_k in ["ENABLE_SPRITE", "SPRITE", "VTT"]:
            if env_k in os.environ:
                data["sprite"] = os.environ[env_k] in ["1", "true", "True", "TRUE", "yes"]
                break

    if "encrypt" not in data and "encryption" not in data and "enable_encryption" not in data:
        for env_k in ["ENCRYPT", "ENCRYPTION", "ENABLE_ENCRYPTION"]:
            if env_k in os.environ:
                data["encrypt"] = os.environ[env_k] in ["1", "true", "True", "TRUE", "yes"]
                break

    if "qualities" not in data:
        qualities_env = os.environ.get("QUALITIES")
        if qualities_env:
            try:
                data["qualities"] = json.loads(qualities_env) if qualities_env.startswith("[") else [q.strip() for q in qualities_env.split(",") if q.strip()]
            except Exception:
                data["qualities"] = [q.strip() for q in qualities_env.split(",") if q.strip()]

    return data


def run_conversion(data: dict = None) -> int:
    """CircleCI ortamında video dönüştürme işlemini baştan sona icra eder."""
    start_time = time.time()
    if data is None:
        data = parse_payload()

    video_url = data.get("video_url")
    webhook_url = data.get("webhook_url")
    raw_domain = data.get("cdn_domain") or data.get("domain") or data.get("cdn_url")
    raw_username = data.get("username") or data.get("user")
    custom_id = data.get("custom_id") or data.get("id") or data.get("external_id")

    # CircleCI workflow veya build numarasını video_id fallback olarak kullan
    circ_wf_id = os.environ.get("CIRCLE_WORKFLOW_ID") or os.environ.get("CIRCLE_WORKFLOW_JOB_ID") or os.environ.get("CIRCLE_BUILD_NUM")
    video_id = data.get("video_id") or (circ_wf_id and f"cir_{str(circ_wf_id)[:8]}") or str(int(start_time))[-8:]
    custom_id = custom_id or video_id

    qualities = data.get("qualities")
    poster_url = data.get("poster_url") or data.get("cover_url") or data.get("thumbnail_url")
    watermark_url = data.get("watermark_url") or data.get("logo_url")
    watermark_position = str(data.get("watermark_position") or data.get("logo_position") or "rt").lower().strip()
    enable_sprite = bool(data.get("sprite", False) or data.get("enable_sprite", False) or data.get("vtt", False))
    encrypt = bool(data.get("encrypt", False) or data.get("encryption", False) or data.get("enable_encryption", False))
    key_url = data.get("key_url") or data.get("key_api_url") or data.get("encryption_key_url")

    storage_host = str(data.get("storage_host") or data.get("server_host") or data.get("host") or "").strip()
    storage_user = str(data.get("storage_user") or data.get("server_user") or data.get("user") or "").strip()
    storage_pass = str(data.get("storage_pass") or data.get("server_pass") or data.get("pass") or data.get("password") or "").strip()
    storage_port = int(data.get("storage_port") or data.get("server_port") or data.get("port") or 22)
    target_dir = str(data.get("target_dir") or data.get("storage_dir") or DEFAULT_TARGET_DIR).strip().rstrip("/")
    web_dir = str(data.get("web_dir") if "web_dir" in data else DEFAULT_WEB_DIR).strip().strip("/")

    if not video_url:
        print("[HATA] video_url parametresi zorunludur!")
        return 1
    if not webhook_url:
        print("[UYARI] webhook_url belirtilmedi, bildirimler yalnızca konsola basılacak.")

    cdn_domain = str(raw_domain or "https://cdn.domain.com").strip().rstrip("/")
    if not cdn_domain.startswith("http://") and not cdn_domain.startswith("https://"):
        cdn_domain = f"https://{cdn_domain}"

    username = re.sub(r'[^a-zA-Z0-9_-]', '', str(raw_username or "default").strip())

    server_config = {
        "host": storage_host,
        "port": storage_port,
        "user": storage_user,
        "pass": storage_pass,
        "target_dir": target_dir,
        "web_dir": web_dir,
        "cdn_domain": cdn_domain
    }

    # Çalışma klasörü
    work_dir = f"/tmp/circleci_convert_{video_id}"
    os.makedirs(work_dir, exist_ok=True)
    input_file = f"{work_dir}/input.mp4"

    tracker = ProgressTracker(webhook_url, video_id, custom_id)
    setup_cancellation_and_timeout_handlers(tracker, start_time, work_dir)

    try:
        # =========================================================================
        # AŞAMA 1: İNDİRME VE ANALİZ (Download & Probe)
        # =========================================================================
        t_dl_start = time.time()
        print(f"[{video_id}] 1. Aşama Başlatılıyor: İndirme (Kullanıcı: {username}, ID: {custom_id}, Platform: CircleCI)")
        tracker.send_event(step="download_started", progress=0, extra={
            "download_progress": 0, "username": username, "encrypted": encrypt
        })

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

        # Direct-IP Routing & aria2c İndirme
        parsed_url = urlparse(video_url)
        domain_host = parsed_url.netloc.split(":")[0].lower()
        target_direct_ip = INTERNAL_DOMAIN_IP_MAP.get(domain_host)

        download_target_url = video_url
        aria2_headers = [f"--header=Host: {domain_host}"]

        if target_direct_ip:
            new_netloc = target_direct_ip if not parsed_url.port else f"{target_direct_ip}:{parsed_url.port}"
            download_target_url = urlunparse(("http", new_netloc, parsed_url.path, parsed_url.params, parsed_url.query, parsed_url.fragment))
            print(f"[{video_id}] İç Ağ Direct-IP Aktif: {domain_host} → http://{new_netloc} (Cloudflare/TLS baypas)")

        aria_cmd = [
            "aria2c",
            "--allow-overwrite=true",
            "-c",
            "-x", "16",
            "-s", "16",
            "-k", "1M",
            "--file-allocation=none",
            "--summary-interval=0",
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "--timeout=30",
            "--max-tries=5",
            "--retry-wait=2",
            "-d", work_dir,
            "-o", "input.mp4",
        ] + aria2_headers + [download_target_url]

        print(f"[{video_id}] aria2c indirme başlatılıyor (16x bağlantı)...")
        download_success = False
        try:
            res_dl = subprocess.run(aria_cmd, capture_output=True, text=True)
            if res_dl.returncode == 0 and os.path.exists(input_file) and os.path.getsize(input_file) > 1024:
                download_success = True
            else:
                print(f"[{video_id}] aria2c uyarısı/hatası, curl fallback deneniyor: {res_dl.stderr}")
        except Exception as dl_err:
            print(f"[{video_id}] aria2c çağrısı başarısız ({dl_err}), curl fallback deneniyor...")

        if not download_success:
            curl_cmd = ["curl", "-f", "-L", "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "-o", input_file, video_url]
            res_curl = subprocess.run(curl_cmd, capture_output=True, text=True)
            if res_curl.returncode != 0 or not os.path.exists(input_file) or os.path.getsize(input_file) <= 1024:
                size_now = os.path.getsize(input_file) if os.path.exists(input_file) else 0
                raise RuntimeError(f"Video indirilemedi veya geçersiz/boş dosya ({size_now} bayt)! URL bağlantısı süresi dolmuş veya erişilemiyor olabilir. Hata: {res_curl.stderr}")

        t_dl_end = time.time()
        dl_duration = round(t_dl_end - t_dl_start, 2)
        file_size_bytes = os.path.getsize(input_file)
        file_size_mb = file_size_bytes / (1024 * 1024)
        dl_speed_mbps = round((file_size_mb * 8) / max(0.1, dl_duration), 2)
        print(f"[{video_id}] Video başarıyla indirildi: {file_size_mb:.2f} MB ({dl_duration}s, {dl_speed_mbps} Mbps)")

        # ffprobe analizi
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-analyzeduration", "5000000", "-probesize", "10000000",
            "-show_entries", "format=duration:stream=width,height,codec_name,codec_type,pix_fmt",
            "-of", "json", input_file
        ]
        probe_res = subprocess.run(probe_cmd, capture_output=True, text=True)
        probe_dur = 0.0
        probe_width = 1920
        probe_height = 1080
        probe_codec = "h264"
        probe_pix_fmt = "yuv420p"
        probe_has_audio = False
        probe_is_aac = False

        if probe_res.returncode == 0 and probe_res.stdout.strip():
            try:
                pdata = json.loads(probe_res.stdout)
                for stream in pdata.get("streams", []):
                    if stream.get("codec_type") == "video" and probe_width == 1920 and probe_height == 1080:
                        probe_width = int(stream.get("width", 1920))
                        probe_height = int(stream.get("height", 1080))
                        probe_codec = stream.get("codec_name", "h264")
                        probe_pix_fmt = stream.get("pix_fmt", "yuv420p")
                    elif stream.get("codec_type") == "audio":
                        probe_has_audio = True
                        if stream.get("codec_name") == "aac":
                            probe_is_aac = True
                if "format" in pdata and "duration" in pdata["format"]:
                    probe_dur = float(pdata["format"]["duration"])
            except Exception as e:
                print(f"[{video_id}] ffprobe json parse hatası: {e}")

        dl_perf_data = {
            "download_time_sec": dl_duration,
            "stage_execution_time_sec": dl_duration,
            "download_size_mb": round(file_size_mb, 2),
            "download_speed_mbps": dl_speed_mbps,
            "direct_download": True,
            "connections": 16,
        }
        with open(f"{work_dir}/perf_download.json", "w", encoding="utf-8") as f:
            json.dump(dl_perf_data, f)

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

        # =========================================================================
        # AŞAMA 2: HLS DÖNÜŞTÜRME & KODLAMA (Transcode & Encode)
        # =========================================================================
        t_conv_start = time.time()
        print(f"[{video_id}] 2. Aşama Başlatılıyor: HLS Kodlama ({probe_width}x{probe_height}, {dur_formatted})...")
        tracker.send_event(step="conversion_started", progress=15)

        # Aktif profilleri belirle
        requested_list = [q.lower().strip() for q in (qualities or []) if str(q).strip()]
        active_profiles = []
        for p in DEFAULT_PROFILES:
            p_name = p["name"]
            if requested_list:
                if p_name in requested_list:
                    active_profiles.append(dict(p))
            else:
                if p["height"] <= probe_height or (not active_profiles and p["height"] == 360):
                    active_profiles.append(dict(p))

        if not active_profiles:
            active_profiles = [DEFAULT_PROFILES[0]]

        for p in active_profiles:
            t_w, t_h = calc_target_dim(probe_width, probe_height, p["height"])
            p["calc_w"] = t_w
            p["calc_h"] = t_h
            p["calc_res_str"] = f"{t_w}x{t_h}"

        print(f"[{video_id}] Kodlanacak Kaliteler: {[p['name'] + ' (' + p['calc_res_str'] + ')' for p in active_profiles]}")

        # Filigran ölçeklendirme
        has_wm = os.path.exists(f"{work_dir}/watermark.png")
        if has_wm:
            wm_pos_key = "rt"
            if os.path.exists(f"{work_dir}/watermark_pos.txt"):
                with open(f"{work_dir}/watermark_pos.txt", "r") as wf:
                    wm_pos_key = wf.read().strip()
            wm_pos_expr = WATERMARK_POSITIONS.get(wm_pos_key, WATERMARK_POSITIONS["rt"])
        else:
            wm_pos_expr = None

        # GPU / NVENC desteğini kontrol et
        use_nvenc = False
        try:
            chk_nv = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=2)
            if chk_nv.returncode == 0:
                chk_enc = subprocess.run(["ffmpeg", "-encoders"], capture_output=True, text=True, timeout=2)
                if "h264_nvenc" in chk_enc.stdout:
                    use_nvenc = True
        except Exception:
            pass

        engine_name = "NVIDIA NVENC GPU" if use_nvenc else f"CPU ({os.cpu_count() or 4}x vCPU libx264 superfast)"
        print(f"[{video_id}] Kodlama Motoru: {engine_name}")

        monitor = ResourceMonitor(interval_sec=0.5, is_gpu=use_nvenc)
        monitor.start()

        for p in active_profiles:
            os.makedirs(f"{work_dir}/{p['name']}", exist_ok=True)

        cpu_cores = os.cpu_count() or 4
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-threads", str(cpu_cores),
            "-filter_complex_threads", str(cpu_cores),
            "-loglevel", "info",
            "-progress", "pipe:1"
        ]
        if use_nvenc:
            ffmpeg_cmd += ["-hwaccel", "cuda"]
        ffmpeg_cmd += ["-i", input_file]

        if has_wm:
            ffmpeg_cmd += ["-i", f"{work_dir}/watermark.png"]

        filter_parts = []
        for idx, p in enumerate(active_profiles):
            tw, th = p["calc_w"], p["calc_h"]
            if has_wm:
                wm_w = max(48, int(round(tw * 0.15)))
                filter_parts.append(f"[0:v]scale={tw}:{th}:flags=fast_bilinear[scaled_v{idx}]")
                filter_parts.append(f"[1:v]scale={wm_w}:-1:flags=fast_bilinear[scaled_wm{idx}]")
                filter_parts.append(f"[scaled_v{idx}][scaled_wm{idx}]overlay={wm_pos_expr}[v_out_{idx}]")
            else:
                filter_parts.append(f"[0:v]scale={tw}:{th}:flags=fast_bilinear[v_out_{idx}]")

        ffmpeg_cmd += ["-filter_complex", ";".join(filter_parts)]

        # Ses ayarı
        audio_args = ["-c:a", "copy"] if (probe_has_audio and probe_is_aac) else (["-c:a", "aac", "-b:a", "128k", "-ac", "2"] if probe_has_audio else ["-an"])

        # AES-128 keyinfo
        enc_args = []
        if encrypt and os.path.exists(f"{work_dir}/enc.keyinfo"):
            enc_args = ["-hls_key_info_file", f"{work_dir}/enc.keyinfo"]

        for idx, p in enumerate(active_profiles):
            v_codec_args = ["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ll"] if use_nvenc else ["-c:v", "libx264", "-preset", "superfast", "-threads", "0", "-crf", p["crf"]]
            ffmpeg_cmd += [
                "-map", f"[v_out_{idx}]",
            ]
            if probe_has_audio:
                ffmpeg_cmd += ["-map", "0:a:0?"]

            ffmpeg_cmd += v_codec_args + audio_args + [
                "-b:v", p["bitrate"],
                "-maxrate", p["maxrate"],
                "-bufsize", p["bufsize"],
                "-g", "48",
                "-keyint_min", "48",
                "-sc_threshold", "0",
                "-hls_time", "4",
                "-hls_playlist_type", "vod",
                "-hls_flags", "independent_segments",
                "-hls_segment_type", "mpegts",
                "-hls_segment_filename", f"{work_dir}/{p['name']}/segment_%03d.ts",
            ] + enc_args + [
                f"{work_dir}/{p['name']}/index.m3u8"
            ]

        proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        last_out_time = time.time()

        for line in proc.stdout:
            last_out_time = time.time()
            if "out_time_ms=" in line:
                try:
                    out_ms = int(line.strip().split("out_time_ms=")[1])
                    cur_sec = out_ms / 1000000.0
                    if probe_dur > 0:
                        prog_pct = min(85, max(15, int(15 + (cur_sec / probe_dur) * 70)))
                        tracker.send_event(step="converting", progress=prog_pct)
                except Exception:
                    pass

            if (time.time() - last_out_time) > 45.0:
                proc.kill()
                raise RuntimeError("FFmpeg 45 saniye boyunca yanıt vermedi (Stagnation Watchdog tetiklendi)!")

        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg HLS kodlama hatası (Return Code {proc.returncode})")

        res_usage = monitor.stop()
        t_conv_end = time.time()
        conv_duration = round(t_conv_end - t_conv_start, 2)
        speed_ratio = round(probe_dur / max(0.1, conv_duration), 2) if probe_dur > 0 else 1.0

        print(f"[{video_id}] FFmpeg kodlama tamamlandı: {conv_duration}s (Hız: {speed_ratio}x realtime)")

        # master.m3u8 oluştur
        master_lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
        for p in active_profiles:
            tw, th = p["calc_w"], p["calc_h"]
            master_lines.append(f"#EXT-X-STREAM-INF:BANDWIDTH={p['bandwidth']},RESOLUTION={tw}x{th},NAME=\"{p['name']}\"")
            master_lines.append(f"{p['name']}/index.m3u8")

        with open(f"{work_dir}/master.m3u8", "w", encoding="utf-8") as mf:
            mf.write("\n".join(master_lines) + "\n")

        # Sprite / VTT üret
        if enable_sprite:
            generate_timeline_sprite_and_vtt(work_dir, input_file, probe_dur)

        # Poster üret
        if not os.path.exists(f"{work_dir}/poster.jpg"):
            poster_sec = min(1.0, probe_dur / 2.0)
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(poster_sec),
                "-i", input_file,
                "-vframes", "1",
                "-q:v", "2",
                f"{work_dir}/poster.jpg"
            ], capture_output=True, text=True)

        # info.json üret
        generate_metadata_and_poster(
            work_dir, input_file, video_id, custom_id,
            username, server_config, probe_width, probe_height,
            probe_dur, active_profiles
        )

        conv_perf_data = {
            "engine": f"{engine_name} | {speed_ratio}x realtime",
            "conversion_time_sec": conv_duration,
            "stage_execution_time_sec": conv_duration,
            "realtime_speed_ratio": f"{speed_ratio}x",
            "video_duration_sec": probe_dur,
            "resource_usage": res_usage,
            "video_details": video_details
        }
        with open(f"{work_dir}/perf_conversion.json", "w", encoding="utf-8") as f:
            json.dump(conv_perf_data, f)

        tracker.send_event(step="conversion_completed", progress=85, extra={
            "conversion_duration_seconds": conv_duration,
            "realtime_speed_ratio": f"{speed_ratio}x",
            "perf_stats": build_accumulated_perf_stats(work_dir, start_time)
        })

        # =========================================================================
        # AŞAMA 3: DEPOLAMA SUNUCUSUNA YÜKLEME (Upload stage)
        # =========================================================================
        t_up_start = time.time()
        print(f"[{video_id}] 3. Aşama Başlatılıyor: Hetzner / SSH Depolama Yüklemesi...")
        tracker.send_event(step="upload_started", progress=90)

        # Güvenlik: secret key dosyalarını diskten temizle
        for sec_file in ["enc.key", "enc.keyinfo"]:
            if os.path.exists(f"{work_dir}/{sec_file}"):
                os.remove(f"{work_dir}/{sec_file}")

        if not storage_host or not storage_user or not storage_pass:
            print(f"[{video_id}] [BİLGİ] storage_host / storage_user / storage_pass tanımlı değil, yükleme atlandı.")
            upload_duration = 0.0
            upload_size_mb = 0.0
            upload_speed_mbps = 0.0
        else:
            remote_target_path = f"{target_dir}/{username}/{video_id}"
            env = os.environ.copy()
            env["SSHPASS"] = storage_pass

            ctl_path = f"/tmp/ssh_ctl_{video_id}_%r@%h_%p"
            ssh_opts = (
                f"ssh -p {storage_port} "
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

            EXCLUDED_FILES = {
                "input.mp4", "probe_data.json", "watermark.png", "watermark_pos.txt",
                "wm_scaled.png", "enc.key", "enc.keyinfo", "enable_sprite.flag", "cancel.flag"
            }

            total_up_bytes = 0
            for root, _, files in os.walk(work_dir):
                for f_name in files:
                    if f_name not in EXCLUDED_FILES and not f_name.startswith("perf_") and not f_name.endswith(".flag"):
                        total_up_bytes += os.path.getsize(os.path.join(root, f_name))
            upload_size_mb = total_up_bytes / (1024 * 1024)

            items = [i for i in os.listdir(work_dir) if not i.startswith("perf_") and i not in EXCLUDED_FILES and not i.endswith(".flag")]
            subdirs = [i for i in items if os.path.isdir(os.path.join(work_dir, i))]
            root_files = [i for i in items if os.path.isfile(os.path.join(work_dir, i))]

            sub_dirs_str = " ".join([f"'{remote_target_path}/{sd}'" for sd in subdirs])
            init_cmd = [
                "sshpass", "-e",
                "ssh", "-p", str(storage_port),
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "PreferredAuthentications=password",
                "-o", "PubkeyAuthentication=no",
                "-o", "ControlMaster=auto",
                "-o", f"ControlPath={ctl_path}",
                "-o", "ControlPersist=120",
                f"{storage_user}@{storage_host}",
                f"mkdir -p '{remote_target_path}' {sub_dirs_str}"
            ]
            subprocess.run(init_cmd, capture_output=True, text=True, env=env)

            def sync_job(src_path, dst_path, is_dir=False):
                r_cmd = [
                    "sshpass", "-e",
                    "rsync", "-r", "--inplace", "-W", "--no-compress",
                    "-e", ssh_opts,
                    src_path + ("/" if is_dir else ""),
                    f"{storage_user}@{storage_host}:{dst_path}" + ("/" if is_dir else "")
                ]
                res = subprocess.run(r_cmd, capture_output=True, text=True, env=env)
                if res.returncode != 0:
                    print(f"[{video_id}] rsync uyarısı ({src_path}): {res.stderr}")
                return res.returncode == 0

            upload_tasks = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(MAX_UPLOAD_WORKERS, len(subdirs) + 1)) as executor:
                for rf in root_files:
                    upload_tasks.append(executor.submit(sync_job, f"{work_dir}/{rf}", f"{remote_target_path}/{rf}", False))
                for sd in subdirs:
                    upload_tasks.append(executor.submit(sync_job, f"{work_dir}/{sd}", f"{remote_target_path}/{sd}", True))

                concurrent.futures.wait(upload_tasks)

            try:
                subprocess.run(["ssh", "-O", "exit", "-o", f"ControlPath={ctl_path}", f"{storage_user}@{storage_host}"], capture_output=True, text=True)
            except Exception:
                pass

            t_up_end = time.time()
            upload_duration = round(t_up_end - t_up_start, 2)
            upload_speed_mbps = round((upload_size_mb * 8) / max(0.1, upload_duration), 2)
            print(f"[{video_id}] Yükleme tamamlandı: {upload_size_mb:.2f} MB ({upload_duration}s, {upload_speed_mbps} Mbps)")

        up_perf_data = {
            "upload_duration_seconds": upload_duration,
            "stage_execution_time_sec": upload_duration,
            "upload_size_mb": round(upload_size_mb, 2),
            "upload_speed_mbps": upload_speed_mbps,
            "hetzner_optimized": True
        }
        with open(f"{work_dir}/perf_upload.json", "w", encoding="utf-8") as f:
            json.dump(up_perf_data, f)

        # =========================================================================
        # AŞAMA 4: TAMAMLANDI BİLDİRİMİ (Completed Event)
        # =========================================================================
        total_elapsed = round(time.time() - start_time, 2)
        base_web_url = build_web_base_url(cdn_domain, web_dir, username, video_id)
        has_poster = os.path.exists(f"{work_dir}/poster.jpg")
        has_sprite = os.path.exists(f"{work_dir}/sprite.jpg")

        tracker.send_event(step="completed", progress=100, status="completed", extra={
            "duration_seconds": round(probe_dur, 2),
            "duration": round(probe_dur, 2),
            "duration_formatted": dur_formatted,
            "cdn_domain": cdn_domain,
            "username": username,
            "encrypted": encrypt,
            "key_url": key_url if encrypt else None,
            "master_url": f"{base_web_url}/master.m3u8",
            "poster_url": f"{base_web_url}/poster.jpg" if has_poster else None,
            "sprite_url": f"{base_web_url}/sprite.jpg" if has_sprite else None,
            "vtt_url": f"{base_web_url}/thumbnails.vtt" if has_sprite else None,
            "info_json_url": f"{base_web_url}/info.json",
            "qualities": [p["name"] for p in active_profiles],
            "elapsed_time_seconds": total_elapsed,
            "processing_time": f"{total_elapsed}s",
            "perf_stats": build_accumulated_perf_stats(work_dir, start_time)
        })

        print(f"[{video_id}] Video dönüştürme ve yükleme başarıyla tamamlandı! Toplam Süre: {total_elapsed}s")
        return 0

    except TaskCancelledOrTimeout as c_err:
        elapsed = round(time.time() - start_time, 2)
        print(f"[{video_id}] İptal algılandı: {c_err}")
        tracker.send_event(step="cancelled", status="cancelled", extra={
            "message": "İşlem CircleCI üzerinden iptal edildi.",
            "elapsed_time_seconds": elapsed,
            "perf_stats": build_accumulated_perf_stats(work_dir, start_time)
        })
        return 130
    except BaseException as err:
        elapsed = round(time.time() - start_time, 2)
        detailed_error = f"{type(err).__name__}: {str(err)}"
        print(f"[{video_id}] Hata Oluştu:\n{traceback.format_exc()}")
        tracker.send_event(step="failed", status="failed", extra={
            "error": detailed_error,
            "message": f"Dönüştürme aşamasında hata: {detailed_error}",
            "elapsed_time_seconds": elapsed,
            "processing_time": f"{elapsed}s",
            "perf_stats": build_accumulated_perf_stats(work_dir, start_time)
        })
        return 1
    finally:
        if os.path.exists(work_dir):
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(run_conversion())
