# 🎬 CircleCI Video HLS Converter & Processor

**CircleCI Video Converter**, [CircleCI Official API v2](https://circleci.com/docs/api/v2/) altyapısı üzerinde çalışan, dinamik CDN alan adlarını, çok kullanıcılı (multi-tenant) klasör yapısını, Hetzner Storage Box ve SSH depolama sunucularını, HLS AES-128 şifrelemeyi, Timeline Sprite/WebVTT seekbar önizleme haritasını, 16 kanallı `aria2c` indirmesini ve **3 seviyeli performans/metrik loglama sistemini** destekleyen yüksek performanslı, harici bir web servisine ihtiyaç duymayan video dönüştürme ve CDN dağıtım çözümüdür.

---

## 🌟 Öne Çıkan Özellikler

* **⚡ Sıfır Ek Sunucu & Resmi CircleCI API v2:** Harici bir API sunucusuna gerek kalmadan doğrudan CircleCI Pipeline API v2 üzerinden tetiklenir.
* **🚀 16x Paralel aria2c İndirme & Direct-IP Baypas:** Cloudflare ve TLS yükünü baypas ederek doğrudan iç ağ IP'sinden indirme (`INTERNAL_DOMAIN_IP_MAP`).
* **🎬 Çoklu Çözünürlük HLS (Adaptive Bitrate Streaming):** `360p`, `720p`, `1080p`, `1440p`, `2160p`, `4320p` uyarlanabilir akış ve otomatik `master.m3u8` üretimi.
* **⚡ AAC Ses Passthrough (Direct Copy):** Kaynak videodaki ses zaten `AAC` formatındaysa ses yeniden kodlanmaz, doğrudan kopyalanır (`-c:a copy`).
* **🔐 HLS AES-128 Şifreleme (`"encrypt": true`):** İsteğe bağlı 128-bit AES ile video parçaları şifrelenir. Anahtar dosyaları (`enc.key`) yükleme öncesi diskten temizlenerek CDN'e sızması önlenir.
* **🖼️ Timeline Sprite ve WebVTT Haritası (`"sprite": true`):** Video oynatıcının seek bar önizlemesi için `sprite.jpg` ve `thumbnails.vtt` otomatik oluşturulur.
* **🌐 Hetzner Storage Box 4x Paralel SSH rsync:** Optimize SSH ControlMaster soketi üzerinden kök dosyalar ve kalite varyantları paralel kanallarla hızla aktarılır.
* **📊 Canlı `perf_stats` ve 5 Saniye Debounced Webhook:** Kodlama ve yükleme sırasında backend'inizi boğmadan 5 saniyede bir akıcı ilerleme (%15-%85) ve ayrıntılı darboğaz metrikleri iletilir (`runner: "circleci"`).
* **🛑 Güvenli İptal ve Temizlik (Watchdog):** CircleCI üzerinden workflow/job iptal edildiğinde (SIGTERM) senkron `status: "cancelled"` webhook'u gönderilir ve geçici disk anında temizlenir.

---

## 🔑 CircleCI API Token & Doğru `project-slug` Bilgisi

CircleCI API v2 uç noktalarında projenizi belirtmek için `{project-slug}` kullanılır:
`POST https://circleci.com/api/v2/project/{project-slug}/pipeline`

> [!IMPORTANT]
> **404 "Project not found" Hatasını Önlemek İçin:**  
> CircleCI API v2'de `project-slug` projenizin VCS türüne göre 2 farklı formatta olabilir:
> 1. **GitLab veya GitHub App Projeleri İçin (En Yaygın):**  
>    Format: `circleci/{organization_id}/{project_id}`  
>    *(Örnek: `circleci/a1b2c3d4-e5f6-7890-abcd-ef1234567890/f1e2d3c4-b5a6-0987-dcba-fe0987654321`)*  
>    *Organization ID: CircleCI sol menü -> **Organization Settings -> Overview** bölümünde yazar.*  
>    *Project ID: CircleCI sol menü -> **Project Settings -> Overview** bölümünde **Project ID** veya **Project Slug** olarak yazar.*
> 2. **Klasik GitHub (OAuth) Projeleri İçin:**  
>    Format: `gh/{github_username}/{repo_name}`  
>    *(Örnek: `gh/huseyinduygun/video-convert`)*
> 
> 👉 **En Kolay Yol:** CircleCI panelinde projenizi açıp **Project Settings -> Overview** sayfasına gidin. Sayfanın en üstünde yazan **Project Slug** değerini kopyalayın.

---

## 🚀 CircleCI Resmi API v2 ile Tetikleme

API Uç Noktası:  
`POST https://circleci.com/api/v2/project/{project-slug}/pipeline`

Zorunlu HTTP Başlıkları:
- `Circle-Token: {api_token}`
- `Content-Type: application/json`

---

### 1. cURL ile Pipeline Başlatma (JSON Payload - Tavsiye Edilen)

```bash
# GitLab / GitHub App Projeleri İçin:
curl -X POST \
  -H "Circle-Token: CCIPAT_TOKEN_BURAYA" \
  -H "Content-Type: application/json" \
  -d '{
    "branch": "main",
    "parameters": {
      "PAYLOAD_JSON": "{\"video_url\":\"https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_30MB.mp4\",\"webhook_url\":\"https://silly-island-20.webhook.cool\",\"cdn_domain\":\"https://video-cdn.xfoy.dev\",\"username\":\"huseyin\",\"custom_id\":\"POST_1001\",\"qualities\":[\"360p\",\"720p\"],\"sprite\":true,\"encrypt\":false,\"storage_host\":\"u625088.your-storagebox.de\",\"storage_user\":\"u625088-sub1\",\"storage_pass\":\"videoCdn500!\",\"storage_port\":23,\"target_dir\":\"hls\"}"
    }
  }' \
  "https://circleci.com/api/v2/project/circleci/ORG_ID/PROJECT_ID/pipeline"
```

```bash
# Standart GitHub (OAuth) Projeleri İçin:
curl -X POST \
  -H "Circle-Token: CCIPAT_TOKEN_BURAYA" \
  -H "Content-Type: application/json" \
  -d '{
    "branch": "main",
    "parameters": {
      "PAYLOAD_JSON": "{\"video_url\":\"https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_30MB.mp4\",\"webhook_url\":\"https://silly-island-20.webhook.cool\",\"cdn_domain\":\"https://video-cdn.xfoy.dev\",\"username\":\"huseyin\",\"custom_id\":\"POST_1001\",\"qualities\":[\"360p\",\"720p\"],\"sprite\":true,\"encrypt\":false,\"storage_host\":\"u625088.your-storagebox.de\",\"storage_user\":\"u625088-sub1\",\"storage_pass\":\"videoCdn500!\",\"storage_port\":23,\"target_dir\":\"hls\"}"
    }
  }' \
  "https://circleci.com/api/v2/project/gh/huseyinduygun/video-convert/pipeline"
```

**Başarılı Yanıt (HTTP 201 Created):**
```json
{
  "id": "7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d",
  "state": "pending",
  "number": 1,
  "created_at": "2026-09-01T12:00:00.000Z"
}
```

---

### 2. cURL ile Ayrı Parametreler Gönderimi

```bash
curl -X POST \
  -H "Circle-Token: CIRCLECI_API_TOKEN_BURAYA" \
  -H "Content-Type: application/json" \
  -d '{
    "branch": "main",
    "parameters": {
      "VIDEO_URL": "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_30MB.mp4",
      "WEBHOOK_URL": "https://silly-island-20.webhook.cool",
      "CDN_DOMAIN": "https://video-cdn.xfoy.dev",
      "USERNAME": "huseyin",
      "CUSTOM_ID": "POST_1001",
      "QUALITIES": "360p,720p",
      "STORAGE_HOST": "u625088.your-storagebox.de",
      "STORAGE_USER": "u625088-sub1",
      "STORAGE_PASS": "videoCdn500!",
      "STORAGE_PORT": "23",
      "ENABLE_SPRITE": "1",
      "TARGET_DIR": "hls"
    }
  }' \
  "https://circleci.com/api/v2/project/gl/huseyinduygun/video-convert/pipeline"
```

---

### 3. PHP ile Entegrasyon

```php
<?php
$circleToken = "CCIPAT_xxxx";
$projectSlug = "gl/huseyinduygun/video-convert"; // veya UUID

$payload = [
    "video_url"     => "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_30MB.mp4",
    "webhook_url"   => "https://silly-island-20.webhook.cool",
    "cdn_domain"    => "https://video-cdn.xfoy.dev",
    "username"      => "huseyin",
    "custom_id"     => "POST_1001",
    "qualities"     => ["360p", "720p"],
    "sprite"        => true,
    "encrypt"       => false,
    "storage_host"  => "u625088.your-storagebox.de",
    "storage_user"  => "u625088-sub1",
    "storage_pass"  => "videoCdn500!",
    "storage_port"  => 23,
    "target_dir"    => "hls"
];

$requestData = [
    "branch"     => "main",
    "parameters" => [
        "PAYLOAD_JSON" => json_encode($payload)
    ]
];

$ch = curl_init("https://circleci.com/api/v2/project/{$projectSlug}/pipeline");
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_HTTPHEADER, [
    "Circle-Token: {$circleToken}",
    "Content-Type: application/json"
]);
curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($requestData));
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_TIMEOUT, 10);

$response = curl_exec($ch);
curl_close($ch);

$result = json_decode($response, true);
echo "Pipeline ID: " . ($result["id"] ?? "Bilinmiyor") . "\n";
echo "Pipeline Number: " . ($result["number"] ?? "Bilinmiyor") . "\n";
?>
```

---

### 4. Python ile Entegrasyon

```python
import json
import requests

CIRCLE_TOKEN = "CCIPAT_xxxx"
PROJECT_SLUG = "gl/huseyinduygun/video-convert"  # veya project UUID

payload = {
    "video_url": "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_30MB.mp4",
    "webhook_url": "https://silly-island-20.webhook.cool",
    "cdn_domain": "https://video-cdn.xfoy.dev",
    "username": "huseyin",
    "custom_id": "POST_1001",
    "qualities": ["360p", "720p"],
    "sprite": True,
    "encrypt": False,
    "storage_host": "u625088.your-storagebox.de",
    "storage_user": "u625088-sub1",
    "storage_pass": "videoCdn500!",
    "storage_port": 23,
    "target_dir": "hls"
}

resp = requests.post(
    f"https://circleci.com/api/v2/project/{PROJECT_SLUG}/pipeline",
    headers={
        "Circle-Token": CIRCLE_TOKEN,
        "Content-Type": "application/json"
    },
    json={
        "branch": "main",
        "parameters": {
            "PAYLOAD_JSON": json.dumps(payload)
        }
    },
    timeout=10
)

data = resp.json()
print("Pipeline ID:", data.get("id"))
print("Pipeline Number:", data.get("number"))
```

---

### 5. Node.js / JavaScript ile Entegrasyon

```javascript
const axios = require('axios');

const CIRCLE_TOKEN = "CCIPAT_xxxx";
const PROJECT_SLUG = "gl/huseyinduygun/video-convert";

const payload = {
  video_url: "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_30MB.mp4",
  webhook_url: "https://silly-island-20.webhook.cool",
  cdn_domain: "https://video-cdn.xfoy.dev",
  username: "huseyin",
  custom_id: "POST_1001",
  qualities: ["360p", "720p"],
  sprite: true,
  encrypt: false,
  storage_host: "u625088.your-storagebox.de",
  storage_user: "u625088-sub1",
  storage_pass: "videoCdn500!",
  storage_port: 23,
  target_dir: "hls"
};

axios.post(`https://circleci.com/api/v2/project/${PROJECT_SLUG}/pipeline`, {
  branch: "main",
  parameters: {
    PAYLOAD_JSON: JSON.stringify(payload)
  }
}, {
  headers: {
    "Circle-Token": CIRCLE_TOKEN,
    "Content-Type": "application/json"
  }
})
.then(res => {
  console.log("Pipeline ID:", res.data.id);
  console.log("Pipeline Number:", res.data.number);
})
.catch(err => console.error("Hata:", err.response?.data || err.message));
```

---

## 🛑 Pipeline İptal Etme & Durum Sorgulama API'leri

### 1. Devam Eden Workflow'u İptal Etme (Cancel Workflow)
```bash
curl -X POST \
  -H "Circle-Token: {api_token}" \
  "https://circleci.com/api/v2/workflow/{workflow_id}/cancel"
```

### 2. Pipeline Durumunu Sorgulama (Get Pipeline)
```bash
curl -H "Circle-Token: {api_token}" \
  "https://circleci.com/api/v2/pipeline/{pipeline_id}"
```

### 3. Pipeline'a Ait Workflow'ları Listeleme
```bash
curl -H "Circle-Token: {api_token}" \
  "https://circleci.com/api/v2/pipeline/{pipeline_id}/workflow"
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
  "video_id": "cir_7a8b9c0d",
  "custom_id": "POST_1001",
  "username": "huseyin",
  "cdn_domain": "https://video-cdn.xfoy.dev",
  "encrypted": false,
  "key_url": null,
  "duration_seconds": 10.0,
  "duration": 10.0,
  "duration_formatted": "00:00:10",
  "master_url": "https://video-cdn.xfoy.dev/huseyin/cir_7a8b9c0d/master.m3u8",
  "poster_url": "https://video-cdn.xfoy.dev/huseyin/cir_7a8b9c0d/poster.jpg",
  "sprite_url": "https://video-cdn.xfoy.dev/huseyin/cir_7a8b9c0d/sprite.jpg",
  "vtt_url": "https://video-cdn.xfoy.dev/huseyin/cir_7a8b9c0d/thumbnails.vtt",
  "info_json_url": "https://video-cdn.xfoy.dev/huseyin/cir_7a8b9c0d/info.json",
  "qualities": ["360p", "720p"],
  "elapsed_time_seconds": 18.5,
  "processing_time": "18.5s",
  "runner": "circleci",
  "perf_stats": {
    "total_elapsed_seconds": 18.5,
    "video_details": {
      "original_resolution": "1280x720",
      "duration_seconds": 10.0,
      "duration_formatted": "00:00:10",
      "input_codec": "h264",
      "has_audio": false,
      "aac_passthrough": false
    },
    "engine_used": "CPU (2x vCPU libx264 superfast) | 4.7x realtime",
    "download_stage": {
      "download_time_sec": 1.8,
      "download_size_mb": 30.0,
      "download_speed_mbps": 133.33,
      "connections": 16
    },
    "conversion_stage": {
      "conversion_time_sec": 2.4,
      "realtime_speed_ratio": "4.7x",
      "resource_usage": {
        "max_cpu_percent": 88.0,
        "avg_cpu_percent": 70.5
      }
    },
    "upload_stage": {
      "upload_duration_seconds": 3.1,
      "upload_size_mb": 8.5,
      "upload_speed_mbps": 21.9
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
  "video_id": "cir_7a8b9c0d",
  "custom_id": "POST_1001",
  "runner": "circleci",
  "message": "İşlem CircleCI üzerinden iptal edildi.",
  "elapsed_time_seconds": 10.2
}
```

---

## 🗂️ Klasör Yapısı

```
.
├── .circleci/
│   └── config.yml                 # CircleCI 2.1 Pipeline tanımı
├── .semaphore/
│   └── semaphore.yml              # Semaphore CI Pipeline tanımı
├── .gitlab-ci.yml                 # GitLab CI Pipeline tanımı
├── modalvideocdn/                 # Modal.com serverless converter modülü
├── gitlabvideocdn/                # GitLab CI video converter modülü
├── semaphorevideocdn/             # Semaphore CI video converter modülü
└── circlecivideocdn/              # CircleCI video converter modülü
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
