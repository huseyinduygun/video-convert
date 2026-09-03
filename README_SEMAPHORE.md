# 🎬 Semaphore CI Video HLS Converter & Processor

**Semaphore CI Video Converter**, [Semaphore CI Official API (v1alpha)](https://docs.semaphore.io/reference/api) altyapısı üzerinde çalışan, dinamik CDN alan adlarını, çok kullanıcılı (multi-tenant) klasör yapısını, Hetzner Storage Box ve SSH depolama sunucularını, HLS AES-128 şifrelemeyi, Timeline Sprite/WebVTT seekbar önizleme haritasını, 16 kanallı `aria2c` indirmesini ve **3 seviyeli performans/metrik loglama sistemini** destekleyen yüksek performanslı, harici bir web servisine ihtiyaç duymayan video dönüştürme ve CDN dağıtım çözümüdür.

---

## 🌟 Öne Çıkan Özellikler

* **⚡ Sıfır Ek Sunucu & Resmi Semaphore API:** Harici bir API sunucusuna gerek kalmadan doğrudan Semaphore CI Workflow API (`v1alpha`) üzerinden tetiklenir.
* **🚀 16x Paralel aria2c İndirme & Direct-IP Baypas:** Cloudflare ve TLS yükünü baypas ederek doğrudan iç ağ IP'sinden indirme (`INTERNAL_DOMAIN_IP_MAP`).
* **🎬 Çoklu Çözünürlük HLS (Adaptive Bitrate Streaming):** `360p`, `720p`, `1080p`, `1440p`, `2160p`, `4320p` uyarlanabilir akış ve otomatik `master.m3u8` üretimi.
* **⚡ AAC Ses Passthrough (Direct Copy):** Kaynak videodaki ses zaten `AAC` formatındaysa ses yeniden kodlanmaz, doğrudan kopyalanır (`-c:a copy`).
* **🔐 HLS AES-128 Şifreleme (`"encrypt": true`):** İsteğe bağlı 128-bit AES ile video parçaları şifrelenir. Anahtar dosyaları (`enc.key`) yükleme öncesi diskten temizlenerek CDN'e sızması önlenir.
* **🖼️ Timeline Sprite ve WebVTT Haritası (`"sprite": true`):** Video oynatıcının seek bar önizlemesi için `sprite.jpg` ve `thumbnails.vtt` otomatik oluşturulur.
* **🌐 Hetzner Storage Box 4x Paralel SSH rsync:** Optimize SSH ControlMaster soketi üzerinden kök dosyalar ve kalite varyantları paralel kanallarla hızla aktarılır.
* **📊 Canlı `perf_stats` ve 5 Saniye Debounced Webhook:** Kodlama ve yükleme sırasında backend'inizi boğmadan 5 saniyede bir akıcı ilerleme (%15-%85) ve ayrıntılı darboğaz metrikleri iletilir (`runner: "semaphore-ci"`).
* **🛑 Güvenli İptal ve Temizlik (Watchdog):** Semaphore CI üzerinden workflow iptal edildiğinde (SIGTERM) senkron `status: "cancelled"` webhook'u gönderilir ve geçici disk anında temizlenir.

---

## 🔑 Semaphore CI Kurulumu & Project UUID Alma

Resmi API belgeleri: [https://docs.semaphore.io/reference/api](https://docs.semaphore.io/reference/api)

> [!IMPORTANT]
> **Kritik Kural: `project_id` Alanı Project UUID Olmalıdır!**  
> Semaphore CI `POST /api/v1alpha/plumber-workflows` uç noktası proje ismi (`video-convert`) yerine projenin **Project UUID** değerini (Örn: `895e9d6d-7fd2-48e4-8623-558295f7cdca`) bekler.
> 
> **Project UUID Değerini Nasıl Bulabilirsiniz?**
> 1. Semaphore web arayüzünde projenizin **Project Settings** sayfasına giderek URL'deki veya sayfadaki UUID'yi alabilirsiniz.
> 2. Veya API ile tüm projelerinizi listeleyip proje adınızın (`video-convert`) UUID'sini sorgulayabilirsiniz:
>    ```bash
>    curl -H "Authorization: Token {api_token}" \
>      "https://<organization-url>.semaphoreci.com/api/v1alpha/projects"
>    ```

1. [Semaphore CI](https://semaphoreci.com/) hesabınıza giriş yapın.
2. [Account Settings -> API Tokens](https://me.semaphoreci.com/account) bölümünden bir API Token oluşturun (Örn: `sem_tok_xxxx`).
3. Organizasyon URL adınızı (`<organization-url>`) ve **Project UUID** bilginizi (Örn: `895e9d6d-7fd2-48e4-8623-558295f7cdca`) not edin.

---

## 🚀 Semaphore CI Resmi API v1alpha ile Tetikleme

Semaphore API Kök Adresi:  
`https://<organization-url>.semaphoreci.com/api/v1alpha`

Zorunlu HTTP Başlıkları:
- `Authorization: Token {api_token}`
- `Content-Type: application/json`

---

### 1. cURL ile Workflow Başlatma (JSON Payload - Tavsiye Edilen)

Endpoint: `POST https://<organization-url>.semaphoreci.com/api/v1alpha/plumber-workflows`

```bash
curl -X POST \
  -H "Authorization: Token SEMAPHORE_API_TOKEN_BURAYA" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "895e9d6d-7fd2-48e4-8623-558295f7cdca",
    "reference": "refs/heads/main",
    "commit_sha": "HEAD",
    "pipeline_file": ".semaphore/semaphore.yml",
    "parameters": {
      "PAYLOAD_JSON": "{\"video_url\":\"https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_30MB.mp4\",\"webhook_url\":\"https://silly-island-20.webhook.cool\",\"cdn_domain\":\"https://video-cdn.xfoy.dev\",\"username\":\"huseyin\",\"custom_id\":\"POST_1001\",\"qualities\":[\"360p\",\"720p\"],\"sprite\":true,\"encrypt\":false,\"storage_host\":\"u625088.your-storagebox.de\",\"storage_user\":\"u625088-sub1\",\"storage_pass\":\"videoCdn500!\",\"storage_port\":23,\"target_dir\":\"hls\"}"
    }
  }' \
  "https://ORGANIZATION.semaphoreci.com/api/v1alpha/plumber-workflows"
```

**Başarılı Yanıt (HTTP 200):**
```json
{
  "workflow_id": "32a689e0-9082-4c5b-a648-bb3dc645452d",
  "pipeline_id": "2abeb1a9-eb4a-4834-84b8-cb7806aec063"
}
```

---

### 2. cURL ile Ayrı Değişkenler (Parameters) Gönderimi

```bash
curl -X POST \
  -H "Authorization: Token SEMAPHORE_API_TOKEN_BURAYA" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "895e9d6d-7fd2-48e4-8623-558295f7cdca",
    "reference": "refs/heads/main",
    "commit_sha": "HEAD",
    "pipeline_file": ".semaphore/semaphore.yml",
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
  "https://ORGANIZATION.semaphoreci.com/api/v1alpha/plumber-workflows"
```

---

### 3. PHP ile Entegrasyon (Otomatik Project UUID Çözümleme ile)

```php
<?php
$semaphoreOrg = "your-org";
$apiToken = "sem_tok_xxxx";
// Doğrudan UUID veya Proje İsmi girebilirsiniz:
$projectInput = "895e9d6d-7fd2-48e4-8623-558295f7cdca"; // veya "video-convert"

// Otomatik UUID Çözümleme: Eğer girilen değer UUID değilse API'den ID bulunur
function resolveSemaphoreProjectId($org, $token, $projectInput) {
    // UUID regex formatı kontrolü
    if (preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i', $projectInput)) {
        return $projectInput;
    }
    // İsim verilmişse API üzerinden ID'yi bul
    $ch = curl_init("https://{$org}.semaphoreci.com/api/v1alpha/projects");
    curl_setopt($ch, CURLOPT_HTTPHEADER, ["Authorization: Token {$token}"]);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    $resp = curl_exec($ch);
    curl_close($ch);
    $projects = json_decode($resp, true);
    if (is_array($projects)) {
        foreach ($projects as $p) {
            $name = $p['metadata']['name'] ?? ($p['name'] ?? '');
            $id = $p['metadata']['id'] ?? ($p['id'] ?? '');
            if (strcasecmp($name, $projectInput) === 0 && $id) {
                return $id;
            }
        }
    }
    return $projectInput;
}

$resolvedProjectId = resolveSemaphoreProjectId($semaphoreOrg, $apiToken, $projectInput);

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
    "project_id"    => $resolvedProjectId,
    "reference"     => "refs/heads/main",
    "commit_sha"    => "HEAD",
    "pipeline_file" => ".semaphore/semaphore.yml",
    "parameters"    => [
        "PAYLOAD_JSON" => json_encode($payload)
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
echo "Workflow ID: " . ($result["workflow_id"] ?? "Bilinmiyor") . "\n";
echo "Pipeline ID: " . ($result["pipeline_id"] ?? "Bilinmiyor") . "\n";
?>
```

---

### 4. Python ile Entegrasyon (Otomatik UUID Çözümleme ile)

```python
import json
import re
import requests

SEMAPHORE_ORG = "your-org"
SEMAPHORE_TOKEN = "sem_tok_xxxx"
PROJECT_INPUT = "895e9d6d-7fd2-48e4-8623-558295f7cdca"  # veya "video-convert"

def resolve_project_id(org, token, proj_input):
    if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', proj_input, re.I):
        return proj_input
    # İsim verilmişse API'den UUID'yi bul
    res = requests.get(
        f"https://{org}.semaphoreci.com/api/v1alpha/projects",
        headers={"Authorization": f"Token {token}"},
        timeout=5
    )
    if res.status_code == 200:
        for p in res.json():
            name = p.get("metadata", {}).get("name") or p.get("name")
            pid = p.get("metadata", {}).get("id") or p.get("id")
            if name and name.lower() == proj_input.lower() and pid:
                return pid
    return proj_input

project_uuid = resolve_project_id(SEMAPHORE_ORG, SEMAPHORE_TOKEN, PROJECT_INPUT)

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
    f"https://{SEMAPHORE_ORG}.semaphoreci.com/api/v1alpha/plumber-workflows",
    headers={
        "Authorization": f"Token {SEMAPHORE_TOKEN}",
        "Content-Type": "application/json"
    },
    json={
        "project_id": project_uuid,
        "reference": "refs/heads/main",
        "commit_sha": "HEAD",
        "pipeline_file": ".semaphore/semaphore.yml",
        "parameters": {
            "PAYLOAD_JSON": json.dumps(payload)
        }
    },
    timeout=10
)

data = resp.json()
print("Workflow ID:", data.get("workflow_id"))
print("Pipeline ID:", data.get("pipeline_id"))
```

---

### 5. Node.js / JavaScript ile Entegrasyon

```javascript
const axios = require('axios');

const SEMAPHORE_ORG = "your-org";
const SEMAPHORE_TOKEN = "sem_tok_xxxx";
const PROJECT_UUID = "895e9d6d-7fd2-48e4-8623-558295f7cdca"; // Project UUID

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

axios.post(`https://${SEMAPHORE_ORG}.semaphoreci.com/api/v1alpha/plumber-workflows`, {
  project_id: PROJECT_UUID,
  reference: "refs/heads/main",
  commit_sha: "HEAD",
  pipeline_file: ".semaphore/semaphore.yml",
  parameters: {
    PAYLOAD_JSON: JSON.stringify(payload)
  }
}, {
  headers: {
    "Authorization": `Token ${SEMAPHORE_TOKEN}`,
    "Content-Type": "application/json"
  }
})
.then(res => {
  console.log("Workflow ID:", res.data.workflow_id);
  console.log("Pipeline ID:", res.data.pipeline_id);
})
.catch(err => console.error("Hata:", err.response?.data || err.message));
```

---

## 🛑 İşlem Durdurma ve Durum Sorgulama API'leri

### 1. Devam Eden Workflow'u Durdurma (Terminate)
```bash
curl -X POST \
  -H "Authorization: Token {api_token}" \
  "https://<organization-url>.semaphoreci.com/api/v1alpha/plumber-workflows/{workflow_id}/terminate"
```

### 2. Pipeline Durumunu Sorgulama (Describe Pipeline)
```bash
curl -H "Authorization: Token {api_token}" \
  "https://<organization-url>.semaphoreci.com/api/v1alpha/pipelines/{pipeline_id}"
```

### 3. Pipeline'ı Durdurma (Stop Pipeline)
```bash
curl -X PATCH \
  -H "Authorization: Token {api_token}" \
  -H "Content-Type: application/json" \
  -d '{"terminate_request": true}' \
  "https://<organization-url>.semaphoreci.com/api/v1alpha/pipelines/{pipeline_id}"
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
| `storage_pass`| String | **Evet** | - | SSH Şifresi (Düz metin, `enc:` ile AES-256 şifreli veya `b64:` ile Base64) |
| `storage_port`| Integer| Hayır | `22` | SSH Portu (Hetzner için `23`) |
| `target_dir` | String | Hayır | `hls` | Hedef sunucudaki ana dizin |
| `web_dir` | String | Hayır | `""` | CDN alt web dizini (Boşsa doğrudan domain/{user}/{id}) |

---

### 🔒 Güvenli SFTP Şifresi Gönderimi (Şifreli / Plaintext Seçenekleri)

`storage_pass` parametresini 3 farklı formatta gönderebilirsiniz:

1. **Düz Metin (Plaintext - Orijinal Hali):**
   ```json
   "storage_pass": "videoCdn500!"
   ```
2. **AES-256-CBC Şifreli (`enc:...` - Önerilen Güvenli Yöntem):**
   ```json
   "storage_pass": "enc:Bxj0PIlWGqBbNp9qc6tc/XFM/00KC4gGQjsbYU5Fog0="
   ```
   *(veya alternatif parametre adı: `"storage_pass_enc": "enc:..."`)*
3. **Base64 Kodlu (`b64:...`):**
   ```json
   "storage_pass": "b64:dmlkZW9DZG41MDAh"
   ```

#### 🐘 PHP ile Şifreleme Yardımcı Fonksiyonu:
```php
function encryptStoragePass(string $plainPassword, string $secretKey = 'hls_sec_3b5a7d9e1f2c4b6a8d0e2f4a6b8c0d2e4f6a8b0c2d4e6f8a'): string {
    $key = hash('sha256', $secretKey, true);
    $iv = openssl_random_pseudo_bytes(16);
    $ciphertext = openssl_encrypt($plainPassword, 'AES-256-CBC', $key, OPENSSL_RAW_DATA, $iv);
    return 'enc:' . base64_encode($iv . $ciphertext);
}

// Kullanım:
$payload['storage_pass'] = encryptStoragePass('videoCdn500!');
```

---

## 📤 Webhook Bildirim Yapıları (Webhook Events)

Sistem işlem boyunca aşağıdaki adımlarda `webhook_url` adresinize HTTP POST istekleri iletir:

### 1. Başarılı Tamamlandı Bildirimi (`status: "completed"`)

```json
{
  "status": "completed",
  "step": "completed",
  "progress": 100,
  "video_id": "sem_32a689e0",
  "custom_id": "POST_1001",
  "username": "huseyin",
  "cdn_domain": "https://video-cdn.xfoy.dev",
  "encrypted": false,
  "key_url": null,
  "duration_seconds": 10.0,
  "duration": 10.0,
  "duration_formatted": "00:00:10",
  "master_url": "https://video-cdn.xfoy.dev/huseyin/sem_32a689e0/master.m3u8",
  "poster_url": "https://video-cdn.xfoy.dev/huseyin/sem_32a689e0/poster.jpg",
  "sprite_url": "https://video-cdn.xfoy.dev/huseyin/sem_32a689e0/sprite.jpg",
  "vtt_url": "https://video-cdn.xfoy.dev/huseyin/sem_32a689e0/thumbnails.vtt",
  "info_json_url": "https://video-cdn.xfoy.dev/huseyin/sem_32a689e0/info.json",
  "qualities": ["360p", "720p"],
  "remaining_credits": 798.0,
  "credit_unit": "minutes",
  "credits": {
    "remaining": 798.0,
    "total": 1000.0,
    "job_used": 0.31,
    "percent_remaining": 79.8,
    "unit": "minutes"
  },
  "billing": {
    "job_cost": 0.31,
    "monthly_limit": 1000.0,
    "estimated_remaining": 798.0,
    "unit": "minutes"
  },
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
  "video_id": "sem_32a689e0",
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
│   └── semaphore.yml              # Semaphore CI 2.0 Pipeline tanımı
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
