import os

DEFAULT_TARGET_DIR = "hls"
DEFAULT_WEB_DIR = ""  # Boş → https://cdn.domain.com/{username}/{video_id}

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "hls_adm_7f9c2e4a1b8d3f5e6a0b9c8d7e6f5a4b3c2d1e0f9a8b7c6d")
SECRET_KEY  = os.environ.get("SECRET_KEY",  "hls_sec_3b5a7d9e1f2c4b6a8d0e2f4a6b8c0d2e4f6a8b0c2d4e6f8a")

WATERMARK_POSITIONS = {
    "lt": "x=10:y=10",             # Left Top  (Sol Üst)
    "lb": "x=10:y=H-h-10",         # Left Bottom (Sol Alt)
    "rt": "x=W-w-10:y=10",         # Right Top (Sağ Üst)
    "rb": "x=W-w-10:y=H-h-10",     # Right Bottom (Sağ Alt)
    "tb": "x=W-w-10:y=H-h-10",     # Right Bottom Alternatif
    "c":  "x=(W-w)/2:y=(H-h)/2",   # Center (Tam Orta)
    "tc": "x=(W-w)/2:y=10",         # Top Center (Üst Orta)
    "bc": "x=(W-w)/2:y=H-h-10",    # Bottom Center (Alt Orta)
    "lc": "x=10:y=(H-h)/2",         # Left Center (Sol Orta)
    "rc": "x=W-w-10:y=(H-h)/2",    # Right Center (Sağ Orta)
}

# ── Modal Stage Konfigürasyonları ────────────────────────────────────────────
# Her stage için @app.function() parametrelerinin tek kaynağı.
# Değişiklik yapmak istediğinizde yalnızca burayı güncelleyin.
# Kullanım: @app.function(image=..., volumes=..., **STAGE_CFG_ENCODE_CPU)

STAGE_CFG_ENCODE_CPU: dict = {
    "cpu":              4.0,   # FFmpeg hızı düşmesin diye 4.0 vCPU TAM GÜÇTE tutuldu!
    "memory":           2048,  # Boşta yatan 6GB RAM kaldırıldı (%75 RAM tasarrufu)
    "timeout":          1800,
    "scaledown_window": 2,     # Modal standart güvenli pencere
    "region":           "eu",
}

STAGE_CFG_ENCODE_GPU: dict = {
    "gpu":              "T4",
    "cpu":              2.0,
    "memory":           4096,  # RAM 8GB'dan 4GB'a çekildi (%50 RAM tasarrufu)
    "timeout":          1800,
    "scaledown_window": 2,
    "region":           "eu",
    "max_containers":   5,     # Free Starter plandaki 10 GPU sınırını korumak için max 5 GPU eşzamanlı çalışır
}

import modal

STAGE_CFG_DOWNLOAD: dict = {
    "cpu":              0.5,   # İndirme ağ bağımlıdır, 0.5 CPU 600 Mbps hıza tam yeter
    "memory":           256,   # aria2c için 256MB RAM fazlasıyla yeterli
    "timeout":          600,
    "scaledown_window": 2,
    "region":           "eu",
    "retries":          modal.Retries(max_retries=2, backoff_coefficient=2.0),
}

STAGE_CFG_UPLOAD: dict = {
    "cpu":               0.5,   # SSH AES şifreleme ve rsync için 0.5 CPU tam yeterli
    "memory":            512,   # rsync için 512MB RAM tam yeterli
    "timeout":           1200,
    "scaledown_window":  2,
    "max_containers":    1,     # Hetzner Storage Box 10 SSH bağlantı limitini korumak için yüklemeler sırayla çalışır
    "region":            "eu",
    "retries":          modal.Retries(max_retries=2, backoff_coefficient=2.0),
}

STAGE_CFG_API: dict = {
    "cpu":                     0.125,
    "memory":                  256,
    "scaledown_window":        2,
    "region":                  "eu",
}

STAGE_CFG_CANCEL: dict = {
    "cpu":                     0.125,
    "memory":                  256,
    "scaledown_window":        2,
    "region":                  "eu",
}

# ── Paralel Upload Konfigürasyonu ──────────────────────────────────────────
# Storage Box / Rsync paralel SSH yükleme iş parçacığı (worker) tavanı
MAX_UPLOAD_WORKERS = 8

# ── Modal Fiyatlandırma Oranları (USD / Saniye) ────────────────────────────
# Modal.com resmi güncel birim kaynak fiyatları (saniye bazlı hesaplama)
# Physical core (2 vCPU eşdeğeri) = $0.0000131 / çekirdek / sn => 1 vCPU = $0.00000655 / sn
PRICING_VCPU_SEC   = 0.00000655   # 1 vCPU per second
PRICING_RAM_GB_SEC = 0.00000222   # 1 GiB RAM per second

PRICING_GPU_MAP = {
    "T4":         0.000164,
    "L4":         0.000222,
    "A10":        0.000306,
    "L40S":       0.000542,
    "A100_40GB":  0.000583,
    "A100_80GB":  0.000694,
    "RTX_PRO_6000": 0.000842,
    "H100":       0.001097,
    "H200":       0.001261,
    "B200":       0.001736,
    "B300":       0.001972,
}

# Her GPU modelinin optimal vCPU ve RAM kaynak eşlemesi (CPU I/O besleme darboğazını önlemek için)
GPU_RESOURCE_MAP = {
    "T4":           {"cpu": 2.0, "memory": 8192},
    "L4":           {"cpu": 4.0, "memory": 8192},
    "A10":          {"cpu": 4.0, "memory": 8192},
    "L40S":         {"cpu": 4.0, "memory": 16384},
    "A100":         {"cpu": 8.0, "memory": 16384},
    "A100_40GB":    {"cpu": 8.0, "memory": 16384},
    "A100_80GB":    {"cpu": 8.0, "memory": 16384},
    "H100":         {"cpu": 8.0, "memory": 16384},
}

ACTIVE_GPU_TYPE = STAGE_CFG_ENCODE_GPU.get("gpu", "T4")
PRICING_ACTIVE_GPU_SEC = PRICING_GPU_MAP.get(ACTIVE_GPU_TYPE, 0.000164)

# İç Ağ / Doğrudan IP Bağlantı Haritası (HTTPS/TLS ve Cloudflare Şifreleme Darboğazını Baypas Etmek İçin)
INTERNAL_DOMAIN_IP_MAP: dict = {
    "video.xfoy.dev": "192.99.199.60",
}