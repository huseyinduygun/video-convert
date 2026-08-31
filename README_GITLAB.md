# 🎬 GitLab CI/CD Video HLS Converter & Processor

**GitLab CI/CD Video Converter**, GitLab Serverless Runner altyapısı üzerinde çalışan, dinamik CDN alan adlarını, çok kullanıcılı (multi-tenant) klasör yapısını, Hetzner Storage Box ve SSH depolama sunucularını, HLS AES-128 şifrelemeyi, Timeline Sprite/WebVTT seekbar önizleme haritasını, 16 kanallı `aria2c` indirmesini ve **3 seviyeli performans/metrik loglama sistemini** destekleyen yüksek performanslı, harici bir web servisine ihtiyaç duymayan video dönüştürme ve CDN dağıtım çözümüdür.

---

## 🌟 Öne Çıkan Özellikler

* **⚡ Sıfır Ek Sunucu Maliyeti:** Harici bir API sunucusu / FastAPI çalıştırmanıza gerek yoktur. Doğrudan GitLab Pipeline Trigger API ile tetiklenir.
* **🚀 16x Paralel aria2c İndirme & Direct-IP Baypas:** Cloudflare ve TLS yükünü baypas ederek doğrudan iç ağ IP'sinden indirme (`INTERNAL_DOMAIN_IP_MAP`).
* **🎬 Çoklu Çözünürlük HLS (Adaptive Bitrate Streaming):** `360p`, `720p`, `1080p`, `1440p`, `2160p`, `4320p` uyarlanabilir akış ve otomatik `master.m3u8` üretimi.
* **⚡ AAC Ses Passthrough (Direct Copy):** Kaynak videodaki ses zaten `AAC` formatındaysa ses yeniden kodlanmaz, doğrudan kopyalanır (`-c:a copy`).
* **🔐 HLS AES-128 Şifreleme (`"encrypt": true`):** İsteğe bağlı 128-bit AES ile video parçaları şifrelenir. Anahtar dosyaları (`enc.key`) yükleme öncesi diskten temizlenerek CDN'e sızması önlenir.
* **🖼️ Timeline Sprite ve WebVTT Haritası (`"sprite": true`):** Video oynatıcının seek bar önizlemesi için `sprite.jpg` ve `thumbnails.vtt` otomatik oluşturulur.
* **🌐 Hetzner Storage Box 4x Paralel SSH rsync:** Optimize SSH ControlMaster soketi üzerinden kök dosyalar ve kalite varyantları paralel kanallarla hızla aktarılır.
* **📊 Canlı `perf_stats` ve 5 Saniye Debounced Webhook:** Kodlama ve yükleme sırasında backend'inizi boğmadan 5 saniyede bir akıcı ilerleme (%15-%85) ve ayrıntılı darboğaz metrikleri iletilir.
* **🛑 Güvenli İptal ve Temizlik (Watchdog):** GitLab üzerinden pipeline iptal edildiğinde (SIGTERM) senkron `status: "cancelled"` webhook'u gönderilir ve geçici disk anında temizlenir.

---

## 🔑 GitLab Kurulumu & Trigger Token Oluşturma

1. GitLab'da projenize gidin: `https://gitlab.com/huseyinduygun/video-convert`
2. Sol menüden **Settings -> CI/CD** bölümünü açın.
3. **Pipeline trigger tokens** başlığını genişletin.
4. **Add trigger** butonuna tıklayarak bir token oluşturun (Örn: `glptt-MAMqoWMX1UC_z_jvEyZP`).

---

## 🚀 Entegrasyon & Tetikleme Örnekleri

GitLab Pipeline Trigger API adresi:
`POST https://gitlab.com/api/v4/projects/{PROJECT_ID_VEYA_URL_ENCODED_PATH}/trigger/pipeline`

> [!TIP]
> Proje yolunuz `huseyinduygun/video-convert` ise URL formatı:  
> `https://gitlab.com/api/v4/projects/huseyinduygun%2Fvideo-convert/trigger/pipeline`

---

### 1. cURL ile Tetikleme (JSON Payload - Tavsiye Edilen)

```bash
curl -X POST \
  --form token="glptt-MAMqoWMX1UC_z_jvEyZP" \
  --form ref="main" \
  --form "variables[PAYLOAD_JSON]={
    \"video_url\": \"https://video.xfoy.dev/uploads/sample.mp4\",
    \"webhook_url\": \"https://siteniz.com/api/video_webhook\",
    \"cdn_domain\": \"https://video-cdn.xfoy.dev\",
    \"username\": \"huseyin\",
    \"custom_id\": \"POST_1001\",
    \"qualities\": [\"360p\", \"720p\", \"1080p\"],
    \"sprite\": true,
    \"encrypt\": false,
    \"storage_host\": \"u625088.your-storagebox.de\",
    \"storage_user\": \"u625088-sub1\",
    \"storage_pass\": \"videoCdn500!\",
    \"storage_port\": 23,
    \"target_dir\": \"hls\"
  }" \
  "https://gitlab.com/api/v4/projects/huseyinduygun%2Fvideo-convert/trigger/pipeline"
```

---

### 2. PHP ile Entegrasyon

```php
<?php
$triggerToken = "glptt-MAMqoWMX1UC_z_jvEyZP";
$projectId = "huseyinduygun%2Fvideo-convert";

$payload = [
    "video_url"     => "https://domain.com/sample.mp4",
    "webhook_url"   => "https://siteniz.com/api/video_webhook",
    "cdn_domain"    => "https://video-cdn.xfoy.dev",
    "username"      => "huseyin",
    "custom_id"     => "POST_1001",
    "qualities"     => ["360p", "720p", "1080p"],
    "sprite"        => true,
    "encrypt"       => false,
    "storage_host"  => "u625088.your-storagebox.de",
    "storage_user"  => "u625088-sub1",
    "storage_pass"  => "videoCdn500!",
    "storage_port"  => 23,
    "target_dir"    => "hls"
];

$ch = curl_init("https://gitlab.com/api/v4/projects/{$projectId}/trigger/pipeline");
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_POSTFIELDS, [
    "token" => $triggerToken,
    "ref"   => "main",
    "variables[PAYLOAD_JSON]" => json_encode($payload)
]);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_TIMEOUT, 10);

$response = curl_exec($ch);
curl_close($ch);

$result = json_decode($response, true);
echo "Pipeline ID: " . $result["id"] . "\n";
echo "İzleme Linki: " . $result["web_url"] . "\n";
?>
```

---

### 3. Python ile Entegrasyon

```python
import json
import requests

GITLAB_TRIGGER_TOKEN = "glptt-MAMqoWMX1UC_z_jvEyZP"
PROJECT_SLUG = "huseyinduygun%2Fvideo-convert"

payload = {
    "video_url": "https://domain.com/sample.mp4",
    "webhook_url": "https://siteniz.com/api/video_webhook",
    "cdn_domain": "https://video-cdn.xfoy.dev",
    "username": "huseyin",
    "custom_id": "POST_1001",
    "qualities": ["360p", "720p", "1080p"],
    "sprite": True,
    "encrypt": False,
    "storage_host": "u625088.your-storagebox.de",
    "storage_user": "u625088-sub1",
    "storage_pass": "videoCdn500!",
    "storage_port": 23,
    "target_dir": "hls"
}

resp = requests.post(
    f"https://gitlab.com/api/v4/projects/{PROJECT_SLUG}/trigger/pipeline",
    data={
        "token": GITLAB_TRIGGER_TOKEN,
        "ref": "main",
        "variables[PAYLOAD_JSON]": json.dumps(payload)
    },
    timeout=10
)

data = resp.json()
print(f"Pipeline Başlatıldı! ID: {data.get('id')}")
print(f"Canlı Takip: {data.get('web_url')}")
```

---

### 4. Node.js / JavaScript ile Entegrasyon

```javascript
const axios = require('axios');

const GITLAB_TRIGGER_TOKEN = "glptt-MAMqoWMX1UC_z_jvEyZP";
const PROJECT_SLUG = "huseyinduygun%2Fvideo-convert";

const payload = {
  video_url: "https://domain.com/sample.mp4",
  webhook_url: "https://siteniz.com/api/video_webhook",
  cdn_domain: "https://video-cdn.xfoy.dev",
  username: "huseyin",
  custom_id: "POST_1001",
  qualities: ["360p", "720p", "1080p"],
  sprite: true,
  encrypt: false,
  storage_host: "u625088.your-storagebox.de",
  storage_user: "u625088-sub1",
  storage_pass: "videoCdn500!",
  storage_port: 23,
  target_dir: "hls"
};

const formData = new URLSearchParams();
formData.append("token", GITLAB_TRIGGER_TOKEN);
formData.append("ref", "main");
formData.append("variables[PAYLOAD_JSON]", JSON.stringify(payload));

axios.post(`https://gitlab.com/api/v4/projects/${PROJECT_SLUG}/trigger/pipeline`, formData)
  .then(res => {
    console.log("Pipeline ID:", res.data.id);
    console.log("Web URL:", res.data.web_url);
  })
  .catch(err => console.error("Tetikleme Hatası:", err.response?.data || err.message));
```

---

## 📋 Tüm İstek Parametreleri Referansı

| Parametre | Tipi | Zorunlu? | Varsayılan | Açıklama |
| :--- | :--- | :--- | :--- | :--- |
| `video_url` | String | **Evet** | - | İndirilecek video dosyasının doğrudan URL'si |
| `webhook_url` | String | **Evet** | - | İlerleme ve tamamlandı bildirimlerinin atılacağı URL |
| `cdn_domain` | String | **Evet** | - | CDN ana alan adı (Örn: `https://video-cdn.xfoy.dev`) |
| `username` | String | **Evet** | - | Kullanıcı dizin adı (Örn: `huseyin`) |
| `custom_id` | String | Hayır | `video_id` | Veritabanınızdaki gönderi/video ID'si |
| `qualities` | Array | Hayır | `["360p", "720p", "1080p"]` | İstenen kaliteler (`360p`, `720p`, `1080p`, `1440p`, `2160p`) |
| `poster_url` | String | Hayır | `null` | Özel afiş resmi (yoksa videodan otomatik 1. sn karesi alınır) |
| `watermark_url`| String | Hayır | `null` | Filigran / Logo PNG resim URL'si |
| `watermark_position`| String | Hayır | `rt` | Konum (`lt`, `lb`, `rt`, `rb`, `c`, `tc`, `bc`, `lc`, `rc`) |
| `sprite` | Boolean| Hayır | `false` | `sprite.jpg` ve `thumbnails.vtt` haritası üretir |
| `encrypt` | Boolean| Hayır | `false` | HLS AES-128 şifrelemeyi aktif eder |
| `key_url` | String | *Encrypt ise* | `null` | Oynatıcının şifre anahtarını alacağı URI |
| `storage_host`| String | **Evet** | - | Hetzner Storage Box / SSH IP adresi |
| `storage_user`| String | **Evet** | - | SSH Kullanıcı adı |
| `storage_pass`| String | **Evet** | - | SSH Şifresi |
| `storage_port`| Integer| Hayır | `22` | SSH Portu (Hetzner için `23`) |
| `target_dir` | String | Hayır | `hls` | Hedef sunucudaki ana dizin |
| `web_dir` | String | Hayır | `""` | CDN alt web dizini (Boşsa doğrudan domain/{user}/{id}) |

---

## 📤 Webhook Bildirim Yapıları (Webhook Events)

Sistem işlem boyunca aşağıdaki adımlarda `webhook_url` adresinize HTTP POST istekleri iletir:

### 1. Başarılı Tamamlandı Bildirimi (`status: "completed"`)

```json
{
  "status": "completed",
  "step": "completed",
  "progress": 100,
  "video_id": "gl_2805470404",
  "custom_id": "POST_1001",
  "username": "huseyin",
  "cdn_domain": "https://video-cdn.xfoy.dev",
  "encrypted": false,
  "key_url": null,
  "duration_seconds": 10.0,
  "duration": 10.0,
  "duration_formatted": "00:00:10",
  "master_url": "https://video-cdn.xfoy.dev/huseyin/gl_2805470404/master.m3u8",
  "poster_url": "https://video-cdn.xfoy.dev/huseyin/gl_2805470404/poster.jpg",
  "sprite_url": "https://video-cdn.xfoy.dev/huseyin/gl_2805470404/sprite.jpg",
  "vtt_url": "https://video-cdn.xfoy.dev/huseyin/gl_2805470404/thumbnails.vtt",
  "info_json_url": "https://video-cdn.xfoy.dev/huseyin/gl_2805470404/info.json",
  "qualities": ["360p", "720p"],
  "elapsed_time_seconds": 24.5,
  "processing_time": "24.5s",
  "runner": "gitlab-ci",
  "perf_stats": {
    "total_elapsed_seconds": 24.5,
    "video_details": {
      "original_resolution": "1280x720",
      "duration_seconds": 10.0,
      "duration_formatted": "00:00:10",
      "input_codec": "h264",
      "has_audio": false,
      "aac_passthrough": false
    },
    "engine_used": "CPU (8x vCPU libx264 superfast) | 3.5x realtime",
    "download_stage": {
      "download_time_sec": 2.1,
      "download_size_mb": 30.0,
      "download_speed_mbps": 114.28,
      "connections": 16
    },
    "conversion_stage": {
      "conversion_time_sec": 2.8,
      "realtime_speed_ratio": "3.5x",
      "resource_usage": {
        "max_cpu_percent": 82.4,
        "avg_cpu_percent": 65.1
      }
    },
    "upload_stage": {
      "upload_duration_seconds": 3.4,
      "upload_size_mb": 8.5,
      "upload_speed_mbps": 20.0
    }
  }
}
```

### 2. Hata / İptal Bildirimi (`status: "failed"` / `"cancelled"`)

```json
{
  "status": "cancelled",
  "step": "cancelled",
  "progress": 0,
  "video_id": "gl_2805470404",
  "custom_id": "POST_1001",
  "runner": "gitlab-ci",
  "message": "İşlem GitLab CI/CD üzerinden iptal edildi.",
  "elapsed_time_seconds": 12.3
}
```

---

## 🗂️ Klasör Yapısı

```
.
├── .gitlab-ci.yml                 # GitLab Runner Docker boru hattı tanımı
├── modalvideocdn/                 # Modal.com serverless converter modülü
└── gitlabvideocdn/                # GitLab CI/CD video converter modülü
    ├── __init__.py                # Paket dışa aktarımları
    ├── config.py                  # Sabitler, çözünürlük profilleri, direct-IP haritası
    ├── runner.py                  # CI/CD ortamında çalışan ana dönüştürücü betik
    ├── requirements.txt           # Gerekli minimal kütüphaneler (requests, psutil)
    ├── README.md                  # Modül içi dokümantasyon
    └── core/
        ├── __init__.py
        ├── tracker.py             # Senkron/Asenkron Webhook yöneticisi & 5s Debouncing
        └── utils.py               # Sprite, VTT, info.json, poster, SSH ve perf_stats
```
