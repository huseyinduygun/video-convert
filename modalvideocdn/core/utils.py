import os
import subprocess
import concurrent.futures
import time
import json
import hmac
import hashlib
import socket
import math

import requests

from ..config.settings import ADMIN_TOKEN, SECRET_KEY


def build_web_base_url(cdn_domain: str, web_dir: str, username: str, video_id: str) -> str:
    """Dinamik CDN domaini ve web dizinine göre tam Web URL yapısını oluşturur."""
    domain_clean = cdn_domain.strip().rstrip("/")
    if not domain_clean.startswith("http://") and not domain_clean.startswith("https://"):
        domain_clean = f"https://{domain_clean}"

    web_dir_clean = web_dir.strip().strip("/") if web_dir else ""

    if web_dir_clean:
        return f"{domain_clean}/{web_dir_clean}/{username}/{video_id}"
    else:
        return f"{domain_clean}/{username}/{video_id}"


def check_storage_server_connection(host: str, port: int, user: str, password: str, target_dir: str, timeout: float = 3.0) -> bool:
    """Hedef rsync/SSH depolama sunucusunun açık ve erişilebilir olduğunu test eder."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
    except Exception as err:
        print(f"Depolama Sunucusu Port Kontrolü Başarısız ({host}:{port}): {err}")
        return False

    try:
        env = os.environ.copy()
        env["SSHPASS"] = password
        check_cmd = [
            "sshpass", "-e",
            "rsync", "--dry-run", "--quiet",
            "-e", f"ssh -p {port} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
                  f"-o PreferredAuthentications=password -o PubkeyAuthentication=no -o ConnectTimeout=3",
            "/tmp/",
            f"{user}@{host}:{target_dir}/"
        ]
        res = subprocess.run(check_cmd, capture_output=True, text=True, timeout=6, env=env)
        if res.returncode == 0:
            return True
        else:
            print(f"Depolama Sunucusu SSH/rsync Doğrulama Hatası ({host}, Return {res.returncode}): {res.stderr}")
            return False
    except Exception as err:
        print(f"Depolama Sunucusu Test Hatası ({host}): {err}")
        return False


def verify_request_auth(data: dict) -> bool:
    """
    Kimlik doğrulama:
    1. Admin Token doğrulaması (admin_token / token / secret_token)
    2. HMAC SHA-256 Hash doğrulaması (hash / signature)
    """
    provided_token = data.get("admin_token") or data.get("token") or data.get("secret_token")
    if provided_token and hmac.compare_digest(str(provided_token), ADMIN_TOKEN):
        return True

    provided_hash = data.get("hash") or data.get("signature")
    video_url = data.get("video_url", "")
    custom_id = data.get("custom_id") or data.get("id") or data.get("external_id") or ""

    if provided_hash and video_url:
        string_to_sign = f"{video_url}:{custom_id}" if custom_id else video_url
        expected_hash = hmac.new(
            SECRET_KEY.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        if hmac.compare_digest(str(provided_hash).lower(), expected_hash.lower()):
            return True

    return False


def probe_connection_tier(url: str, num_conn: int) -> bool:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    def single_head(idx):
        try:
            req_headers = dict(headers)
            req_headers["Range"] = f"bytes={idx * 100}-{(idx + 1) * 100}"
            res = requests.head(url, headers=req_headers, allow_redirects=True, timeout=2)
            return res.status_code in [200, 206]
        except Exception:
            return False

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_conn) as ex:
            results = list(ex.map(single_head, range(num_conn)))
        return len(results) == num_conn and all(results)
    except Exception:
        return False


def detect_optimal_connections(url: str) -> int:
    """Sunucunun desteklediği maksimum bağlantı limitini (16→8→4→2→1) otomatik bulur."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Range": "bytes=0-100"}
        r = requests.head(url, headers=headers, allow_redirects=True, timeout=2)
        if r.status_code not in [200, 206]:
            return 1
        for tier in [16, 8, 4, 2]:
            if probe_connection_tier(url, tier):
                return tier
    except Exception as e:
        print(f"Bağlantı tespiti uyarısı: {e}")
    return 1


def generate_timeline_sprite_and_vtt(work_dir: str, input_file: str, total_duration: float):
    """
    Video süresine göre dinamik aralıklarla (5s/10s/20s/30s) kare alır,
    sprite.jpg ve thumbnails.vtt haritası oluşturur.
    """
    if total_duration <= 0 or not os.path.exists(f"{work_dir}/enable_sprite.flag"):
        return False

    try:
        if total_duration <= 600:
            interval = 5
        elif total_duration <= 1800:
            interval = 10
        elif total_duration <= 3600:
            interval = 20
        else:
            interval = 30

        num_frames = int(total_duration // interval) + 1
        if num_frames <= 0:
            return False

        cols = 10
        rows = math.ceil(num_frames / cols)
        thumb_width = 160
        thumb_height = 90

        sprite_path = f"{work_dir}/sprite.jpg"
        vtt_path = f"{work_dir}/thumbnails.vtt"

        print(f"Timeline Sprite oluşturuluyor ({total_duration:.1f}s, {interval}s aralık, {num_frames} kare, {cols}x{rows} ızgara)...")
        sprite_cmd = [
            "ffmpeg", "-y", "-threads", "4",
            "-i", input_file,
            "-vf", f"fps=1/{interval},scale={thumb_width}:{thumb_height},tile={cols}x{rows}",
            "-q:v", "3",
            sprite_path
        ]
        res = subprocess.run(sprite_cmd, capture_output=True, text=True)
        if res.returncode != 0 or not os.path.exists(sprite_path):
            print(f"Sprite üretme uyarısı: {res.stderr}")
            return False

        def format_vtt_time(seconds):
            m, s = divmod(seconds, 60)
            h, m = divmod(m, 60)
            ms = int((seconds - int(seconds)) * 1000)
            return f"{int(h):02d}:{int(m):02d}:{int(s):02d}.{ms:03d}"

        vtt_lines = ["WEBVTT", ""]
        for i in range(num_frames):
            start_sec = i * interval
            end_sec = min(total_duration, (i + 1) * interval)
            col = i % cols
            row = i // cols
            x = col * thumb_width
            y = row * thumb_height
            vtt_lines.append(f"{format_vtt_time(start_sec)} --> {format_vtt_time(end_sec)}")
            vtt_lines.append(f"sprite.jpg#xywh={x},{y},{thumb_width},{thumb_height}")
            vtt_lines.append("")

        with open(vtt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(vtt_lines))

        print("Timeline Sprite ve thumbnails.vtt başarıyla üretildi!")
        return True
    except Exception as err:
        print(f"Timeline Sprite oluşturma hatası: {err}")
        return False


def generate_metadata_and_poster(
    work_dir: str, input_file: str, video_id: str, custom_id: str,
    username: str, server_config: dict, in_width: int, in_height: int,
    total_duration: float, active_profiles: list
):
    """Videonun info.json metadata dosyasını üretir."""
    poster_path = f"{work_dir}/poster.jpg"
    has_poster = os.path.exists(poster_path)
    has_sprite = os.path.exists(f"{work_dir}/sprite.jpg") and os.path.exists(f"{work_dir}/thumbnails.vtt")
    has_encryption = os.path.exists(f"{work_dir}/is_encrypted.flag")

    encrypted_key_url = None
    if has_encryption:
        with open(f"{work_dir}/is_encrypted.flag", "r", encoding="utf-8") as ef:
            encrypted_key_url = ef.read().strip()

    dur_int = int(total_duration)
    mins, secs = divmod(dur_int, 60)
    hours, mins = divmod(mins, 60)
    formatted_duration = f"{hours:02d}:{mins:02d}:{secs:02d}"

    base_web_url = build_web_base_url(
        server_config["cdn_domain"],
        server_config.get("web_dir", ""),
        username,
        video_id
    )

    info_data = {
        "video_id": video_id,
        "custom_id": custom_id,
        "username": username,
        "cdn_domain": server_config["cdn_domain"],
        "encrypted": has_encryption,
        "key_url": encrypted_key_url if has_encryption else None,
        "duration_seconds": round(total_duration, 2),
        "duration_formatted": formatted_duration,
        "original_resolution": {
            "width": in_width,
            "height": in_height,
            "aspect_ratio": f"{in_width}:{in_height}"
        },
        "qualities": [
            {
                "name": p["name"],
                "resolution": p["calc_res_str"],
                "bandwidth": p["bandwidth"],
                "playlist_url": f"{base_web_url}/{p['name']}/index.m3u8"
            } for p in active_profiles
        ],
        "master_url": f"{base_web_url}/master.m3u8",
        "poster_url": f"{base_web_url}/poster.jpg" if has_poster else None,
        "sprite_url": f"{base_web_url}/sprite.jpg" if has_sprite else None,
        "vtt_url": f"{base_web_url}/thumbnails.vtt" if has_sprite else None,
        "info_json_url": f"{base_web_url}/info.json",
        "created_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    }

    with open(f"{work_dir}/info.json", "w", encoding="utf-8") as f:
        json.dump(info_data, f, indent=4, ensure_ascii=False)

    return info_data


def calc_target_dim(orig_w: int, orig_h: int, target_h: int):
    """Orijinal en-boy oranını koruyarak hedef yüksekliğe göre genişliği hesaplar."""
    if orig_h <= 0 or orig_w <= 0:
        return 1920, 1080
    scale = target_h / float(orig_h)
    new_w = int(round(orig_w * scale))
    if new_w % 2 != 0:
        new_w += 1
    return new_w, target_h


def cleanup_stale_volume_files(max_age_seconds: int = 7200):
    """
    /vol dizinindeki 2 saatten (7200 saniye) eski çöp kalıntı klasörleri otomatik olarak siler.
    Hiçbir çöken veya zaman aşımına uğrayan işleme ait dosyanın diskte yer kaplamamasını sağlar.
    """
    try:
        vol_root = "/vol"
        if not os.path.exists(vol_root):
            return
        now = time.time()
        cleaned_count = 0
        for item in os.listdir(vol_root):
            item_path = os.path.join(vol_root, item)
            if os.path.isdir(item_path):
                mtime = os.path.getmtime(item_path)
                if (now - mtime) > max_age_seconds:
                    import shutil
                    print(f"[Volume Safety] 2 saatten eski çöp klasör siliniyor: {item_path}")
                    shutil.rmtree(item_path, ignore_errors=True)
                    cleaned_count += 1
        if cleaned_count > 0:
            from ..config import volume
            volume.commit()
            print(f"[Volume Safety] {cleaned_count} adet çöp klasör temizlendi ve Volume commit edildi.")
    except Exception as err:
        print(f"[Volume Safety] Temizlik uyarısı: {err}")
