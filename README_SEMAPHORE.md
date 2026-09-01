# 🎬 Semaphore CI Video HLS Converter & Processor

**Semaphore CI Video Converter**, [Semaphore CI](https://semaphoreci.com/) bulut / VM altyapısı üzerinde çalışan, dinamik CDN alan adlarını, çok kullanıcılı (multi-tenant) klasör yapısını, Hetzner Storage Box ve SSH depolama sunucularını, HLS AES-128 şifrelemeyi, Timeline Sprite/WebVTT seekbar önizleme haritasını, 16 kanallı `aria2c` indirmesini ve **3 seviyeli performans/metrik loglama sistemini** destekleyen yüksek performanslı, harici bir web servisine ihtiyaç duymayan video dönüştürme ve CDN dağıtım çözümüdür.

---

## 🌟 Öne Çıkan Özellikler

* **⚡ Ultra Hızlı Başlatma & Sıfır Ek Sunucu:** Semaphore CI'ın optimize VM makineleri (`e1-standard-2`, `e1-standard-4` vb.) üzerinde doğrudan Semaphore API ile tetiklenir.
* **🚀 16x Paralel aria2c İndirme & Direct-IP Baypas:** Cloudflare ve TLS yükünü baypas ederek doğrudan iç ağ IP'sinden indirme (`INTERNAL_DOMAIN_IP_MAP`).
* **🎬 Çoklu Çözünürlük HLS (Adaptive Bitrate Streaming):** `360p`, `720p`, `1080p`, `1440p`, `2160p`, `4320p` uyarlanabilir akış ve otomatik `master.m3u8` üretimi.
* **⚡ AAC Ses Passthrough (Direct Copy):** Kaynak videodaki ses zaten `AAC` formatındaysa ses yeniden kodlanmaz, doğrudan kopyalanır (`-c:a copy`).
* **🔐 HLS AES-128 Şifreleme (`"encrypt": true`):** İsteğe bağlı 128-bit AES ile video parçaları şifrelenir. Anahtar dosyaları (`enc.key`) yükleme öncesi diskten temizlenerek CDN'e sızması önlenir.
* **🖼️ Timeline Sprite ve WebVTT Haritası (`"sprite": true`):** Video oynatıcının seek bar önizlemesi için `sprite.jpg` ve `thumbnails.vtt` otomatik oluşturulur.
* **🌐 Hetzner Storage Box 4x Paralel SSH rsync:** Optimize SSH ControlMaster soketi üzerinden kök dosyalar ve kalite varyantları paralel kanallarla hızla aktarılır.
* **📊 Canlı `perf_stats` ve 5 Saniye Debounced Webhook:** Kodlama ve yükleme sırasında backend'inizi boğmadan 5 saniyede bir akıcı ilerleme (%15-%85) ve ayrıntılı darboğaz metrikleri iletilir (`runner: "semaphore-ci"`).
* **🛑 Güvenli İptal ve Temizlik (Watchdog):** Semaphore CI üzerinden workflow iptal edildiğinde (SIGTERM) senkron `status: "cancelled"` webhook'u gönderilir ve geçici disk anında temizlenir.

---

## 🔑 Semaphore CI Kurulumu & API Token Alma

1. [Semaphore CI](https://semaphoreci.com/) hesabınıza giriş yapın.
2. Sağ üstteki profil menüsünden **Account Settings -> API Tokens** bölümüne gidin.
3. Yeni bir API Token oluşturun (Örn: `sem_tok_xxxx`).
4. Projenizin adını veya Project ID'sini alın (Örn: `video-convert` veya UUID).

---

## 🚀 Entegrasyon & Tetikleme Örnekleri

Semaphore CI Workflow API adresi:
`POST https://<ORGANIZATION>.semaphoreci.com/api/v1alpha/plumber-workflows`

---

### 1. cURL ile Tetikleme (JSON Payload - Tavsiye Edilen)

```bash
curl -X POST \
  -H "Authorization: Token SEMAPHORE_API_TOKEN_BURAYA" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "video-convert",
    "reference": "main",
    "commit_sha": "HEAD",
    "pipeline_file": ".semaphore/semaphore.yml",
    "env_vars": [
      {
        "name": "PAYLOAD_JSON",
        "value": "{\"video_url\":\"https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_30MB.mp4\",\"webhook_url\":\"https://siteniz.com/api/video_webhook\",\"cdn_domain\":\"https://video-cdn.xfoy.dev\",\"username\":\"huseyin\",\"custom_id\":\"POST_1001\",\"qualities\":[\"360p\",\"720p\"],\"sprite\":true,\"encrypt\":false,\"storage_host\":\"u625088.your-storagebox.de\",\"storage_user\":\"u625088-sub1\",\"storage_pass\":\"videoCdn500!\",\"storage_port\":23,\"target_dir\":\"hls\"}"
      }
    ]
  }' \
  "https://ORGANIZATION.semaphoreci.com/api/v1alpha/plumber-workflows"
```

---

### 2. Python ile Entegrasyon

```python
import json
import requests

SEMAPHORE_ORG = "your-org"
SEMAPHORE_TOKEN = "sem_tok_xxxx"
PROJECT_ID = "video-convert"  # Proje adı veya UUID

payload = {
    "video_url": "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_30MB.mp4",
    "webhook_url": "https://siteniz.com/api/video_webhook",
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
    f"https://{SEMAPHORE_ORG}.semaphoreci.com/api/v1alpha/plumber-workflows",
    headers={
        "Authorization": f"Token {SEMAPHORE_TOKEN}",
        "Content-Type": "application/json"
    },
    json={
        "project_id": PROJECT_ID,
        "reference": "main",
        "commit_sha": "HEAD",
        "pipeline_file": ".semaphore/semaphore.yml",
        "env_vars": [
            {
                "name": "PAYLOAD_JSON",
                "value": json.dumps(payload)
            }
        ]
    },
    timeout=10
)

data = resp.json()
print("Workflow ID:", data.get("wf_id"))
```

---

### 3. PHP ile Entegrasyon

```php
<?php
$semaphoreOrg = "your-org";
$apiToken = "sem_tok_xxxx";
$projectId = "video-convert";

$payload = [
    "video_url"     => "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_30MB.mp4",
    "webhook_url"   => "https://siteniz.com/api/video_webhook",
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
    "project_id"    => $projectId,
    "reference"     => "main",
    "commit_sha"    => "HEAD",
    "pipeline_file" => ".semaphore/semaphore.yml",
    "env_vars"      => [
        [
            "name"  => "PAYLOAD_JSON",
            "value" => json_encode($payload)
        ]
    ]
];

$ch = curl_init("https://{$semaphoreOrg}.semaphoreci.com/api/v1alpha/plumber-workflows");
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_HTTPHEADER, [
    "Authorization: Token {$apiToken}",
    "Content-Type: application/json"
]);
curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($requestData));
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_TIMEOUT, 10);

$response = curl_exec($ch);
curl_close($ch);

$result = json_decode($response, true);
echo "Workflow ID: " . $result["wf_id"] . "\n";
?>
```

---

### 4. Node.js / JavaScript ile Entegrasyon

```javascript
const axios = require('axios');

const SEMAPHORE_ORG = "your-org";
const SEMAPHORE_TOKEN = "sem_tok_xxxx";
const PROJECT_ID = "video-convert";

const payload = {
  video_url: "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_30MB.mp4",
  webhook_url: "https://siteniz.com/api/video_webhook",
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

axios.post(`https://${SEMAPHORE_ORG}.semaphoreci.com/api/v1alpha/plumber-workflows`, {
  project_id: PROJECT_ID,
  reference: "main",
  commit_sha: "HEAD",
  pipeline_file: ".semaphore/semaphore.yml",
  env_vars: [
    {
      name: "PAYLOAD_JSON",
      value: JSON.stringify(payload)
    }
  ]
}, {
  headers: {
    "Authorization": `Token ${SEMAPHORE_TOKEN}`,
    "Content-Type": "application/json"
  }
})
.then(res => console.log("Workflow ID:", res.data.wf_id))
.catch(err => console.error("Hata:", err.response?.data || err.message));
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
  "video_id": "sem_a1b2c3d4",
  "custom_id": "POST_1001",
  "username": "huseyin",
  "cdn_domain": "https://video-cdn.xfoy.dev",
  "encrypted": false,
  "key_url": null,
  "duration_seconds": 10.0,
  "duration": 10.0,
  "duration_formatted": "00:00:10",
  "master_url": "https://video-cdn.xfoy.dev/huseyin/sem_a1b2c3d4/master.m3u8",
  "poster_url": "https://video-cdn.xfoy.dev/huseyin/sem_a1b2c3d4/poster.jpg",
  "sprite_url": "https://video-cdn.xfoy.dev/huseyin/sem_a1b2c3d4/sprite.jpg",
  "vtt_url": "https://video-cdn.xfoy.dev/huseyin/sem_a1b2c3d4/thumbnails.vtt",
  "info_json_url": "https://video-cdn.xfoy.dev/huseyin/sem_a1b2c3d4/info.json",
  "qualities": ["360p", "720p"],
  "elapsed_time_seconds": 18.5,
  "processing_time": "18.5s",
  "runner": "semaphore-ci",
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
    "engine_used": "CPU (4x vCPU libx264 superfast) | 4.1x realtime",
    "download_stage": {
      "download_time_sec": 1.8,
      "download_size_mb": 30.0,
      "download_speed_mbps": 133.33,
      "connections": 16
    },
    "conversion_stage": {
      "conversion_time_sec": 2.4,
      "realtime_speed_ratio": "4.1x",
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
  "video_id": "sem_a1b2c3d4",
  "custom_id": "POST_1001",
  "runner": "semaphore-ci",
  "message": "İşlem Semaphore CI üzerinden iptal edildi.",
  "elapsed_time_seconds": 10.2
}
```

---

## 🗂️ Klasör Yapısı

```
.
├── .semaphore/
│   └── semaphore.yml              # Semaphore CI Pipeline tanımı
├── .gitlab-ci.yml                 # GitLab CI Pipeline tanımı
├── modalvideocdn/                 # Modal.com serverless converter modülü
├── gitlabvideocdn/                # GitLab CI video converter modülü
└── semaphorevideocdn/             # Semaphore CI video converter modülü
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
