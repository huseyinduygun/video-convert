import concurrent.futures
import hashlib
import hmac
import json
import math
import os
import socket
import subprocess
import threading
import time
import urllib.request
from urllib.parse import urlparse, urlunparse

from ..config import (
    ADMIN_TOKEN,
    INTERNAL_DOMAIN_IP_MAP,
    SECRET_KEY,
)


class ResourceMonitor:
    """CPU ve varsa GPU kullanım oranlarını periyodik olarak örnekler."""
    def __init__(self, interval_sec: float = 0.5, is_gpu: bool = False):
        self.interval = interval_sec
        self.is_gpu = is_gpu
        self._running = False
        self._thread = None
        self.cpu_samples = []
        self.gpu_samples = []
        self.gpu_mem_samples = []

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

        res = {
            "max_cpu_percent": round(max(self.cpu_samples), 1) if self.cpu_samples else 0.0,
            "avg_cpu_percent": round(sum(self.cpu_samples) / len(self.cpu_samples), 1) if self.cpu_samples else 0.0,
        }
        if self.is_gpu:
            res["max_gpu_percent"] = round(max(self.gpu_samples), 1) if self.gpu_samples else 0.0
            res["avg_gpu_percent"] = round(sum(self.gpu_samples) / len(self.gpu_samples), 1) if self.gpu_samples else 0.0
            res["max_gpu_memory_mb"] = int(max(self.gpu_mem_samples)) if self.gpu_mem_samples else 0
        return res

    def _monitor_loop(self):
        try:
            import psutil
            # İlk çağrı referans noktasını başlatır
            psutil.cpu_percent(interval=None)
        except Exception:
            psutil = None

        while self._running:
            try:
                if psutil:
                    sys_cpu = psutil.cpu_percent(interval=None)
                    if sys_cpu is not None and sys_cpu > 0.0:
                        self.cpu_samples.append(round(float(sys_cpu), 1))
                else:
                    self.cpu_samples.append(0.0)

                if self.is_gpu:
                    try:
                        res = subprocess.run(
                            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                            capture_output=True, text=True, timeout=1
                        )
                        if res.returncode == 0 and res.stdout.strip():
                            parts = res.stdout.strip().split("\n")[0].split(",")
                            self.gpu_samples.append(float(parts[0].strip()))
                            self.gpu_mem_samples.append(float(parts[1].strip()))
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(self.interval)


def verify_request_auth(data: dict) -> bool:
    """İstek yetkilendirmesini admin_token veya HMAC imzası ile doğrular."""
    if not data:
        return False

    req_admin_token = data.get("admin_token")
    if req_admin_token and str(req_admin_token).strip() == ADMIN_TOKEN:
        return True

    signature = data.get("signature")
    timestamp = data.get("timestamp")
    video_url = data.get("video_url")

    if not signature or not timestamp or not video_url:
        return False

    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except Exception:
        return False

    raw = f"{video_url}:{timestamp}"
    expected_sig = hmac.new(SECRET_KEY.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(str(signature).strip(), expected_sig)


def calc_target_dim(src_w: int, src_h: int, target_h: int) -> tuple:
    """En boy oranını koruyarak hedef genişlik ve yüksekliği çift sayı olacak şekilde hesaplar."""
    if src_h <= 0 or src_w <= 0:
        return 1280, 720
    calc_w = int(round((src_w / src_h) * target_h))
    if calc_w % 2 != 0:
        calc_w += 1
    if target_h % 2 != 0:
        target_h += 1
    return calc_w, target_h


def generate_timeline_sprite_and_vtt(work_dir: str, input_file: str, duration: float):
    """Oynatıcı seek bar önizlemesi için sprite.jpg ve thumbnails.vtt dosyalarını oluşturur."""
    print(f"Sprite ve VTT Haritası Üretiliyor... (Video Süresi: {duration:.2f}s)")
    t_start = time.time()
    vtt_path = f"{work_dir}/thumbnails.vtt"
    sprite_path = f"{work_dir}/sprite.jpg"

    if duration <= 0:
        duration = 60.0

    interval = 5
    if duration > 1800:
        interval = 15
    elif duration > 600:
        interval = 10

    total_frames = math.ceil(duration / interval)
    cols = 10
    rows = math.ceil(total_frames / cols)
    tile_str = f"{cols}x{rows}"
    tw, th = 160, 90

    try:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", input_file,
            "-vf", f"fps=1/{interval},scale={tw}:{th}:flags=fast_bilinear,tile={tile_str}",
            "-q:v", "4",
            "-an",
            sprite_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            print(f"Sprite üretimi hatası: {res.stderr}")
            return

        def fmt_time(sec):
            hrs = int(sec // 3600)
            mins = int((sec % 3600) // 60)
            secs = int(sec % 60)
            ms = int((sec - int(sec)) * 1000)
            return f"{hrs:02d}:{mins:02d}:{secs:02d}.{ms:03d}"

        vtt_lines = ["WEBVTT", ""]
        curr_time = 0.0

        for r in range(rows):
            for c in range(cols):
                frame_idx = r * cols + c
                if frame_idx >= total_frames:
                    break
                next_time = min(duration, curr_time + interval)
                x = c * tw
                y = r * th
                vtt_lines.append(f"{fmt_time(curr_time)} --> {fmt_time(next_time)}")
                vtt_lines.append(f"sprite.jpg#xywh={x},{y},{tw},{th}")
                vtt_lines.append("")
                curr_time = next_time
                if curr_time >= duration:
                    break

        with open(vtt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(vtt_lines))

        print(f"Sprite ve VTT Başarıyla Üretildi: {total_frames} kare ({time.time() - t_start:.2f}s)")
    except Exception as e:
        print(f"Sprite üretim uyarısı: {e}")


def generate_metadata_and_poster(
    work_dir: str,
    input_file: str,
    video_id: str,
    custom_id: str,
    username: str,
    server_config: dict,
    width: int,
    height: int,
    duration: float,
    active_profiles: list
):
    """info.json ve poster.jpg dosyalarını standart formatta oluşturur."""
    cdn_domain = server_config.get("cdn_domain", "").rstrip("/")
    web_dir = server_config.get("web_dir", "").strip().strip("/")

    if web_dir:
        base_url = f"{cdn_domain}/{web_dir}/{username}/{video_id}"
    else:
        base_url = f"{cdn_domain}/{username}/{video_id}"

    dur_int = int(duration)
    mins, secs = divmod(dur_int, 60)
    hours, mins = divmod(mins, 60)
    dur_formatted = f"{hours:02d}:{mins:02d}:{secs:02d}"

    info_data = {
        "video_id": video_id,
        "custom_id": custom_id,
        "username": username,
        "cdn_domain": cdn_domain,
        "base_url": base_url,
        "master_m3u8": f"{base_url}/master.m3u8",
        "poster": f"{base_url}/poster.jpg",
        "sprite": f"{base_url}/sprite.jpg" if os.path.exists(f"{work_dir}/sprite.jpg") else None,
        "vtt": f"{base_url}/thumbnails.vtt" if os.path.exists(f"{work_dir}/thumbnails.vtt") else None,
        "duration_seconds": round(duration, 2),
        "duration_formatted": dur_formatted,
        "original_resolution": f"{width}x{height}",
        "qualities": [
            {
                "name": p["name"],
                "resolution": p.get("calc_res_str", f"{p['height']}p"),
                "bandwidth": p["bandwidth"],
                "url": f"{base_url}/{p['name']}/index.m3u8"
            }
            for p in active_profiles
        ],
        "created_at": int(time.time()),
        "runner": "circleci"
    }

    with open(f"{work_dir}/info.json", "w", encoding="utf-8") as f:
        json.dump(info_data, f, indent=2, ensure_ascii=False)


def build_accumulated_perf_stats(work_dir: str, start_time: float) -> dict:
    """Tüm aşamalara ait performans loglarını toparlar."""
    total_elapsed = round(time.time() - start_time, 2)
    stats = {
        "total_elapsed_seconds": total_elapsed,
        "runner": "circleci"
    }

    for stage_file in ["perf_download.json", "perf_conversion.json", "perf_upload.json"]:
        file_path = f"{work_dir}/{stage_file}"
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    stage_data = json.load(f)
                stage_key = stage_file.replace("perf_", "").replace(".json", "") + "_stage"
                stats[stage_key] = stage_data
                if "video_details" in stage_data and "video_details" not in stats:
                    stats["video_details"] = stage_data["video_details"]
                if "engine" in stage_data and "engine_used" not in stats:
                    stats["engine_used"] = stage_data["engine"]
                if "resource_usage" in stage_data and "resource_usage" not in stats:
                    stats["resource_usage"] = stage_data["resource_usage"]
            except Exception:
                pass

    return stats


def test_storage_connection(storage_host: str, storage_port: int, storage_user: str, storage_pass: str) -> dict:
    """Hetzner Storage Box SSH / SFTP bağlantısını sınar."""
    t0 = time.time()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(4.0)
        s.connect((storage_host, int(storage_port)))
        s.close()
        tcp_ok = True
    except Exception as e:
        return {"status": "error", "message": f"TCP portuna erişilemedi ({storage_host}:{storage_port}): {e}"}

    env = os.environ.copy()
    env["SSHPASS"] = storage_pass
    ssh_cmd = [
        "sshpass", "-e",
        "ssh", "-p", str(storage_port),
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "PreferredAuthentications=password",
        "-o", "PubkeyAuthentication=no",
        "-o", "ConnectTimeout=5",
        f"{storage_user}@{storage_host}",
        "echo OK_STORAGE_BOX"
    ]
    res = subprocess.run(ssh_cmd, capture_output=True, text=True, env=env)
    elapsed = round(time.time() - t0, 3)

    if res.returncode == 0 and "OK_STORAGE_BOX" in res.stdout:
        return {
            "status": "success",
            "message": "Storage Box bağlantısı başarılı.",
            "latency_ms": int(elapsed * 1000)
        }
    else:
        return {
            "status": "error",
            "message": f"SSH kimlik doğrulama başarısız: {res.stderr.strip()}",
            "latency_ms": int(elapsed * 1000)
        }


def build_web_base_url(cdn_domain: str, web_dir: str, username: str, video_id: str) -> str:
    """CDN için tam URL adresini üretir."""
    clean_domain = str(cdn_domain or "https://cdn.domain.com").strip().rstrip("/")
    if not clean_domain.startswith("http://") and not clean_domain.startswith("https://"):
        clean_domain = f"https://{clean_domain}"

    clean_web_dir = str(web_dir or "").strip().strip("/")
    if clean_web_dir:
        return f"{clean_domain}/{clean_web_dir}/{username}/{video_id}"
    return f"{clean_domain}/{username}/{video_id}"
