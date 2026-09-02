import base64
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

from ..config.settings import (
    ADMIN_TOKEN, SECRET_KEY, STAGE_CFG_DOWNLOAD, STAGE_CFG_ENCODE_CPU,
    STAGE_CFG_ENCODE_GPU, STAGE_CFG_UPLOAD, PRICING_VCPU_SEC,
    PRICING_RAM_GB_SEC, PRICING_ACTIVE_GPU_SEC, PRICING_GPU_MAP
)


def decrypt_storage_pass(pass_str: str, secret_key: str = None) -> str:
    """
    SFTP / Storage şifresini çözümler:
    1. 'enc:' ile başlıyorsa: AES-256-CBC (OpenSSL / PHP uyumlu) şifresini çözer.
    2. 'b64:' ile başlıyorsa: Base64 kodunu çözer.
    3. Normal düz metin (Plaintext) ise: Olduğu gibi döner.
    """
    if not pass_str or not isinstance(pass_str, str):
        return ""

    pass_str = pass_str.strip()
    sec_key = secret_key or SECRET_KEY

    # 1. Base64 Çözümü
    if pass_str.startswith("b64:"):
        try:
            return base64.b64decode(pass_str[4:]).decode("utf-8")
        except Exception as err:
            print(f"[UYARI] storage_pass b64 çözme hatası: {err}")
            return pass_str

    # 2. AES-256-CBC Şifre Çözümü (PHP openssl_encrypt uyumlu)
    if pass_str.startswith("enc:"):
        try:
            raw_bytes = base64.b64decode(pass_str[4:])
            if len(raw_bytes) > 16:
                iv_hex = raw_bytes[:16].hex()
                cipher_bytes = raw_bytes[16:]
                k_hex = hashlib.sha256(sec_key.encode("utf-8")).hexdigest()
                dec_cmd = [
                    "openssl", "enc", "-d", "-aes-256-cbc",
                    "-K", k_hex,
                    "-iv", iv_hex
                ]
                res = subprocess.run(dec_cmd, input=cipher_bytes, capture_output=True, timeout=5)
                if res.returncode == 0 and res.stdout:
                    return res.stdout.decode("utf-8")
                else:
                    print(f"[UYARI] storage_pass OpenSSL şifre çözme hatası: {res.stderr.decode('utf-8', errors='ignore')}")
        except Exception as err:
            print(f"[UYARI] storage_pass enc çözme hatası: {err}")

    # 3. Düz metin (Plaintext)
    return pass_str


def get_container_allocated_cpu(default_cpu: float = 8.0) -> str:
    """Modal'ın atadığı vCPU miktarını MODAL_CPUS ortam değişkeninden okur.
    Bu sayede cgroup v1/v2 üzerinde host'un toplam CPU sayısını yanlış rapor etme
    sorununun önüne geçilir. Değişken yoksa default_cpu kullanılır."""
    try:
        modal_cpus = os.environ.get("MODAL_CPUS")
        if modal_cpus:
            val = round(float(modal_cpus), 2)
            return f"{int(val) if val == int(val) else val}"
    except Exception:
        pass
    val = round(default_cpu, 2)
    return f"{int(val) if val == int(val) else val}"


def calc_optimal_cpu(
    height: int,
    duration_sec: float,
    quality_count: int,
    max_cpu: float = 8.0,
) -> float:
    """Video özelliklerine göre libx264 encode için optimal vCPU sayısını hesaplar.

    Mantık:
      - Her kalite seviyesi için çözünürlüğe bağlı bir thread ihtiyacı belirlenir.
      - 4K → 4 thread/kalite, 1080p → 3, 720p → 2, 480p ve altı → 1
      - Toplam ihtiyaç quality_count ile çarpılır, minimum 1, max_cpu ile sınırlanır.
      - Uzun videolar (>10 dk) için küçük bir çarpan eklenir.
    """
    if height >= 2160:
        threads_per_quality = 4
    elif height >= 1080:
        threads_per_quality = 3
    elif height >= 720:
        threads_per_quality = 2
    else:
        threads_per_quality = 1

    base = threads_per_quality * max(1, quality_count)

    # 10 dakikayı aşan videolar için +1 ekstra
    if duration_sec > 600:
        base += 1

    # En yakın çift sayıya yuvarla (Modal CPU tahsisleri genellikle çiftli olur)
    optimal = min(max_cpu, max(1.0, float(base)))
    # 1, 2, 4, 8 kademelerine yuvarla
    for step in [1.0, 2.0, 4.0, 8.0]:
        if optimal <= step:
            return step
    return max_cpu


import threading

class ResourceMonitor:
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
            parent_proc = psutil.Process()
            parent_proc.cpu_percent(interval=None)
            alloc_vcpus = float(os.environ.get("MODAL_CPUS", "4.0"))
        except Exception:
            psutil = None
            parent_proc = None
            alloc_vcpus = 4.0

        while self._running:
            try:
                if psutil and parent_proc:
                    tot_cpu = parent_proc.cpu_percent(interval=None)
                    for child in parent_proc.children(recursive=True):
                        try:
                            tot_cpu += child.cpu_percent(interval=None)
                        except Exception:
                            pass
                    norm_pct = min(100.0, round(tot_cpu / max(1.0, alloc_vcpus), 1))
                    self.cpu_samples.append(norm_pct)
            except Exception:
                pass

            if self.is_gpu:
                try:
                    gpu_p = subprocess.run(
                        ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=1
                    )
                    if gpu_p.returncode == 0 and gpu_p.stdout.strip():
                        parts = gpu_p.stdout.strip().split("\n")[0].split(",")
                        if len(parts) >= 2:
                            g_util = float(parts[0].strip())
                            g_mem = float(parts[1].strip())
                            self.gpu_samples.append(g_util)
                            self.gpu_mem_samples.append(g_mem)
                except Exception:
                    pass

            time.sleep(self.interval)


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
        env["SSHPASS"] = decrypt_storage_pass(password, SECRET_KEY)
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


def generate_smart_posters(work_dir: str, input_file: str, duration: float):
    """
    FFmpeg 'thumbnail' filtresini kullanarak videonun %20, %50 ve %80 dilimlerinden
    en net ve temsil edici 3 adet poster (poster_1.jpg, poster_2.jpg, poster_3.jpg) üretir.
    Eğer API'den özel bir poster.jpg geldiyse bu işlem tamamen atlanır.
    """
    default_poster = f"{work_dir}/poster.jpg"
    if os.path.exists(default_poster) and os.path.getsize(default_poster) > 0:
        # API'den özel poster zaten indirildi/geldi, otomatik üretimi atla
        return

    import shutil
    dur = max(1.0, float(duration or 1.0))
    time_points = [
        ("poster_1.jpg", max(0.5, round(dur * 0.20, 2))),
        ("poster_2.jpg", max(1.0, round(dur * 0.50, 2))),
        ("poster_3.jpg", max(1.5, round(dur * 0.80, 2))),
    ]

    for filename, ss_time in time_points:
        target_path = f"{work_dir}/{filename}"
        if not os.path.exists(target_path):
            try:
                subprocess.run([
                    "ffmpeg", "-y",
                    "-ss", str(ss_time),
                    "-i", input_file,
                    "-vf", "thumbnail=30",
                    "-vframes", "1",
                    "-q:v", "2",
                    target_path
                ], capture_output=True, text=True, timeout=20)
            except Exception as e:
                print(f"[UYARI] {filename} poster üretim hatası: {e}")

    if not os.path.exists(default_poster):
        for candidate in ["poster_1.jpg", "poster_2.jpg", "poster_3.jpg"]:
            cand_path = f"{work_dir}/{candidate}"
            if os.path.exists(cand_path) and os.path.getsize(cand_path) > 0:
                shutil.copy2(cand_path, default_poster)
                break


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

    posters_list = []
    for i in [1, 2, 3]:
        if os.path.exists(f"{work_dir}/poster_{i}.jpg"):
            posters_list.append(f"{base_web_url}/poster_{i}.jpg")

    primary_poster_url = f"{base_web_url}/poster.jpg" if has_poster else (posters_list[0] if posters_list else None)

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
        "poster_url": primary_poster_url,
        "posters": posters_list if posters_list else ([primary_poster_url] if primary_poster_url else []),
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


def cleanup_stale_volume_files(max_age_seconds: int = 1200):
    """
    /vol dizinindeki 20 dakikadan (1200 saniye) eski çöp kalıntı klasörleri otomatik olarak siler.
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
                    print(f"[Volume Safety] 20 dakikadan eski çöp klasör siliniyor: {item_path}")
                    shutil.rmtree(item_path, ignore_errors=True)
                    cleaned_count += 1
        if cleaned_count > 0:
            from ..config import volume
            volume.commit()
            print(f"[Volume Safety] {cleaned_count} adet çöp klasör temizlendi ve Volume commit edildi.")
    except Exception as err:
        print(f"[Volume Safety] Temizlik uyarısı: {err}")


import modal
from ..config import app, volume
from .images import image_cpu

@app.function(
    schedule=modal.Cron("0 * * * *"),
    volumes={"/vol": volume},
    image=image_cpu,
    cpu=0.125,
    memory=256,
    region="eu",
    scaledown_window=2,
    timeout=180
)
def auto_cleanup_cron():
    """Modal tarafında saat başı otomatik çalışan arka plan temizlik botu."""
    print("[Cron Safety] Saat başı periyodik Volume temizlik botu çalıştırıldı.")
    cleanup_stale_volume_files(max_age_seconds=1200)


def build_accumulated_perf_stats(work_dir: str, start_time: float) -> dict:
    """Volume üzerindeki mevcut perf_*.json dosyalarını okur, o anki aşamaya kadar
    birikmiş metrikleri ve tahmini birikmiş Modal maliyetini hesaplar.
    """
    dl_perf_file = f"{work_dir}/perf_download.json"
    conv_perf_file = f"{work_dir}/perf_conversion.json"
    up_perf_file = f"{work_dir}/perf_upload.json"

    dl_perf = {}
    if os.path.exists(dl_perf_file):
        try:
            with open(dl_perf_file, "r", encoding="utf-8") as f:
                dl_perf = json.load(f)
        except Exception:
            pass

    conv_perf = {}
    if os.path.exists(conv_perf_file):
        try:
            with open(conv_perf_file, "r", encoding="utf-8") as f:
                conv_perf = json.load(f)
        except Exception:
            pass

    up_perf = {}
    if os.path.exists(up_perf_file):
        try:
            with open(up_perf_file, "r", encoding="utf-8") as f:
                up_perf = json.load(f)
        except Exception:
            pass

    elapsed_sec = round(time.time() - start_time, 2)
    raw_video_details = conv_perf.get("video_details", {})
    video_details = dict(raw_video_details) if raw_video_details else {}

    # Maliyet hesabı (Modal Konteyner Gerçek Execution Süreleri Üzerinden)
    dl_sec = float(dl_perf.get("stage_execution_time_sec", dl_perf.get("download_time_sec", 0.0)))
    dl_cost = dl_sec * (STAGE_CFG_DOWNLOAD["cpu"] * PRICING_VCPU_SEC + (STAGE_CFG_DOWNLOAD["memory"] / 1024.0) * PRICING_RAM_GB_SEC)

    enc_sec = float(conv_perf.get("stage_execution_time_sec", conv_perf.get("conversion_time_sec", 0.0)))
    is_gpu = "GPU" in conv_perf.get("engine", "")
    enc_cpu_val = float(conv_perf.get("allocated_cpu", STAGE_CFG_ENCODE_CPU["cpu"] if not is_gpu else STAGE_CFG_ENCODE_GPU["cpu"]))
    enc_ram_val = float(STAGE_CFG_ENCODE_CPU["memory"] if not is_gpu else STAGE_CFG_ENCODE_GPU["memory"])
    detected_gpu = conv_perf.get("gpu_type")
    if not detected_gpu and is_gpu:
        engine_str = conv_perf.get("engine", "").upper()
        for g_k in PRICING_GPU_MAP.keys():
            if g_k in engine_str:
                detected_gpu = g_k
                break
    gpu_type = detected_gpu or STAGE_CFG_ENCODE_GPU.get("gpu", "T4")
    gpu_rate = PRICING_GPU_MAP.get(gpu_type, PRICING_ACTIVE_GPU_SEC)
    gpu_addon_cost = (enc_sec * gpu_rate) if is_gpu else 0.0
    enc_cost = (enc_sec * (enc_cpu_val * PRICING_VCPU_SEC + (enc_ram_val / 1024.0) * PRICING_RAM_GB_SEC)) + gpu_addon_cost

    up_sec = float(up_perf.get("stage_execution_time_sec", up_perf.get("upload_duration_seconds", 0.0)))
    up_cost = up_sec * (STAGE_CFG_UPLOAD["cpu"] * PRICING_VCPU_SEC + (STAGE_CFG_UPLOAD["memory"] / 1024.0) * PRICING_RAM_GB_SEC)

    total_cost_usd = round(dl_cost + enc_cost + up_cost, 6)

    stats = {
        "total_elapsed_seconds": elapsed_sec,
    }
    if video_details:
        stats["video_details"] = video_details
    if conv_perf.get("engine"):
        stats["engine_used"] = conv_perf["engine"]
    if dl_perf:
        stats["download_stage"] = dl_perf
    if conv_perf:
        # Shallow copy without polluting video_details
        c_copy = dict(conv_perf)
        c_copy.pop("video_details", None)
        stats["conversion_stage"] = c_copy
    if up_perf:
        stats["upload_stage"] = up_perf

    stats["resource_specs"] = {
        "download_cpu": STAGE_CFG_DOWNLOAD["cpu"],
        "download_ram_mb": STAGE_CFG_DOWNLOAD["memory"],
        "encode_cpu": conv_perf.get("allocated_cpu", STAGE_CFG_ENCODE_CPU["cpu"] if not is_gpu else STAGE_CFG_ENCODE_GPU["cpu"]),
        "encode_ram_mb": STAGE_CFG_ENCODE_CPU["memory"] if not is_gpu else STAGE_CFG_ENCODE_GPU["memory"],
        "upload_cpu": STAGE_CFG_UPLOAD["cpu"],
        "upload_ram_mb": STAGE_CFG_UPLOAD["memory"]
    }
    if conv_perf.get("resource_usage"):
        stats["resource_usage"] = conv_perf["resource_usage"]

    stats["cost_estimate"] = {
        "total_cost_usd": total_cost_usd,
        "formatted": f"${total_cost_usd:.4f}",
        "breakdown_usd": {
            "download": round(dl_cost, 6),
            "conversion": round(enc_cost, 6),
            "upload": round(up_cost, 6)
        }
    }
    return stats

