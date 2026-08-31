# GitLab CI/CD Video HLS Converter & Processor Service

Bu servis (`gitlabvideocdn/`), herhangi bir ara web servisi / API gateway gerektirmeden, **doğrudan GitLab Pipeline Trigger Token ve parametreler ile tetiklenen**, Modal.com servisiyle birebir aynı yetenek ve webhook JSON formatına sahip video HLS dönüştürme ve CDN yükleme çözümüdür.

---

## 🌟 Özellikler

* **🚀 16x Paralel aria2c İndirme & Direct-IP Baypas:** Cloudflare ve TLS yükünü baypas ederek doğrudan iç ağ IP'sinden indirme.
* **🎬 Çoklu Çözünürlük HLS libx264/NVENC:** `360p`, `720p`, `1080p`, `1440p`, `2160p`, `4320p` uyarlanabilir akış.
* **🔐 HLS AES-128 Şifreleme:** Güvenli anahtar yönetimi (`encrypt: true`).
* **🖼️ Timeline Sprite & Thumbnails VTT:** Oynatıcı önizleme çubuğu için sprite haritası.
* **⚡ Hetzner Storage Box 4x Paralel SSH rsync:** Optimize SSH ControlMaster ile hızlı aktarım.
* **📊 Canlı `perf_stats` ve 5 Saniye Debounced Webhook:** Darboğaz ve CPU/RAM kullanım raporlaması.
* **🛑 Güvenli İptal ve Temizlik:** GitLab Pipeline iptal edildiğinde (SIGTERM) senkron `cancelled` webhook bildirimi ve anında disk temizliği.

---

## 🚀 GitLab CI/CD Tetikleme (Trigger) Kullanımı

GitLab projenizde **Settings -> CI/CD -> Pipeline trigger tokens** bölümünden bir token oluşturun (örneğin: `glptt-xxxx`).

### 1. cURL ile JSON Payload Gönderimi (Tek Paket - Tavsiye Edilen)

```bash
curl -X POST \
  --form token="GL_TRIGGER_TOKEN_BURAYA" \
  --form ref="main" \
  --form "variables[PAYLOAD_JSON]={
    \"video_url\": \"https://video.xfoy.dev/uploads/sample.mp4\",
    \"webhook_url\": \"https://siteniz.com/api/video_webhook\",
    \"cdn_domain\": \"https://cdn.domain.com\",
    \"username\": \"huseyin\",
    \"custom_id\": \"POST_1001\",
    \"qualities\": [\"360p\", \"720p\", \"1080p\"],
    \"sprite\": true,
    \"encrypt\": true,
    \"key_url\": \"https://siteniz.com/api/get_key?id=POST_1001\",
    \"storage_host\": \"u123456.your-storagebox.de\",
    \"storage_user\": \"u123456\",
    \"storage_pass\": \"gizli_sifre\",
    \"storage_port\": 23,
    \"target_dir\": \"hls\"
  }" \
  "https://gitlab.com/api/v4/projects/huseyinduygun%2Fvideo-convert/trigger/pipeline"
```

---

### 2. cURL ile Ayrı Ayrı Değişkenler Gönderimi

```bash
curl -X POST \
  --form token="GL_TRIGGER_TOKEN_BURAYA" \
  --form ref="main" \
  --form "variables[VIDEO_URL]=https://domain.com/video.mp4" \
  --form "variables[WEBHOOK_URL]=https://siteniz.com/api/video_webhook" \
  --form "variables[CDN_DOMAIN]=https://cdn.domain.com" \
  --form "variables[USERNAME]=huseyin" \
  --form "variables[CUSTOM_ID]=POST_1001" \
  --form "variables[QUALITIES]=360p,720p,1080p" \
  --form "variables[STORAGE_HOST]=u123.your-storagebox.de" \
  --form "variables[STORAGE_USER]=u123" \
  --form "variables[STORAGE_PASS]=gizli_sifre" \
  --form "variables[STORAGE_PORT]=23" \
  --form "variables[ENABLE_SPRITE]=1" \
  --form "variables[ENCRYPT]=1" \
  --form "variables[KEY_URL]=https://siteniz.com/api/get_key?id=POST_1001" \
  "https://gitlab.com/api/v4/projects/huseyinduygun%2Fvideo-convert/trigger/pipeline"
```

---

### 3. Python ile Tetikleme Örneği

```python
import requests

GITLAB_TRIGGER_TOKEN = "glptt-xxxx"
PROJECT_ID = "huseyinduygun/video-convert"  # veya proje numeric ID'si
ENCODED_PROJECT_ID = "huseyinduygun%2Fvideo-convert"

payload = {
    "video_url": "https://video.xfoy.dev/uploads/sample.mp4",
    "webhook_url": "https://siteniz.com/api/video_webhook",
    "cdn_domain": "https://cdn.domain.com",
    "username": "huseyin",
    "custom_id": "POST_1001",
    "qualities": ["360p", "720p", "1080p"],
    "sprite": True,
    "encrypt": True,
    "key_url": "https://siteniz.com/api/get_key?id=POST_1001",
    "storage_host": "u123456.your-storagebox.de",
    "storage_user": "u123456",
    "storage_pass": "gizli_sifre",
    "storage_port": 23,
    "target_dir": "hls"
}

resp = requests.post(
    f"https://gitlab.com/api/v4/projects/{ENCODED_PROJECT_ID}/trigger/pipeline",
    data={
        "token": GITLAB_TRIGGER_TOKEN,
        "ref": "main",
        "variables[PAYLOAD_JSON]": requests.compat.json.dumps(payload)
    }
)

pipeline_info = resp.json()
print("GitLab Pipeline ID:", pipeline_info.get("id"))
print("Pipeline URL:", pipeline_info.get("web_url"))
```

---

### 4. PHP ile Tetikleme Örneği

```php
<?php
$triggerToken = "glptt-xxxx";
$projectId = "huseyinduygun%2Fvideo-convert";

$payload = [
    "video_url"    => "https://domain.com/video.mp4",
    "webhook_url"  => "https://siteniz.com/api/video_webhook",
    "cdn_domain"   => "https://cdn.domain.com",
    "username"     => "huseyin",
    "custom_id"    => "POST_1001",
    "qualities"    => ["360p", "720p", "1080p"],
    "sprite"       => true,
    "encrypt"      => true,
    "key_url"      => "https://siteniz.com/api/get_key?id=POST_1001",
    "storage_host" => "u123.your-storagebox.de",
    "storage_user" => "u123",
    "storage_pass" => "gizli_sifre",
    "storage_port" => 23
];

$ch = curl_init("https://gitlab.com/api/v4/projects/{$projectId}/trigger/pipeline");
curl_setopt($ch, CURLOPT_POST, 1);
curl_setopt($ch, CURLOPT_POSTFIELDS, [
    "token" => $triggerToken,
    "ref"   => "main",
    "variables[PAYLOAD_JSON]" => json_encode($payload)
]);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
$response = curl_exec($ch);
curl_close($ch);

$result = json_decode($response, true);
echo "Pipeline ID: " . $result["id"];
?>
```

---

## ⚙️ GitLab CI/CD Değişkenleri (Tüm Parametreler)

İstek gönderirken ister `PAYLOAD_JSON` içinde ister aşağıdaki ortam değişkenleri olarak parametre geçebilirsiniz:

| Parametre | Tipi | Varsayılan | Açıklama |
| :--- | :--- | :--- | :--- |
| `VIDEO_URL` | String | **Zorunlu** | İndirilecek kaynak video bağlantısı |
| `WEBHOOK_URL` | String | **Zorunlu** | İlerleme ve tamamlandı bildirimlerinin atılacağı URL |
| `CDN_DOMAIN` | String | **Zorunlu** | CDN alan adı (Örn: `https://cdn.domain.com`) |
| `USERNAME` | String | **Zorunlu** | Kullanıcı klasör adı (Sadece harf, rakam, tire) |
| `CUSTOM_ID` | String | video_id | Kendi veritabanınızdaki video/post ID'si |
| `QUALITIES` | Array / CSV | Otomatik | `["360p","720p","1080p"]` veya `360p,720p,1080p` |
| `POSTER_URL` | String | Opsiyonel | Özel kapak fotoğrafı URL'si (yoksa videodan otomatik çekilir) |
| `WATERMARK_URL`| String | Opsiyonel | Filigran/logo resim URL'si |
| `WATERMARK_POSITION`| String | `rt` | Pozisyon (`lt`, `lb`, `rt`, `rb`, `c`, `tc`, `bc`) |
| `ENABLE_SPRITE`| Boolean | `0` | Seekbar önizlemesi için `sprite.jpg` ve `thumbnails.vtt` üretir |
| `ENCRYPT` | Boolean | `0` | HLS AES-128 şifrelemeyi aktif eder |
| `KEY_URL` | String | Opsiyonel | AES-128 anahtarının okunacağı URI (encrypt=true ise zorunlu) |
| `STORAGE_HOST` | String | **Zorunlu** | Hetzner Storage Box / SSH Sunucusu IP/Host |
| `STORAGE_USER` | String | **Zorunlu** | SSH Kullanıcı Adı |
| `STORAGE_PASS` | String | **Zorunlu** | SSH Şifresi |
| `STORAGE_PORT` | Integer | `22` | SSH Portu (Hetzner için genellikle 23) |
| `TARGET_DIR` | String | `hls` | Hedef ana dizin yolu |
| `WEB_DIR` | String | `""` | CDN alt web dizini |

---

## 📤 Webhook Olayları (Events)

Modal.com ile %100 birebir aynı JSON formatında bildirim gönderilir:

| Step | Status | Progress | Açıklama |
| :--- | :--- | :--- | :--- |
| `download_started` | `processing` | %0 | aria2c indirme başladı |
| `download_completed` | `processing` | %10 | İndirme ve ffprobe analizi tamamlandı (`video_details` ile) |
| `conversion_started` | `processing` | %15 | FFmpeg HLS kodlama başladı |
| `converting` | `processing` | %15-%85 | Canlı kodlama ilerlemesi (5s debounced) |
| `conversion_completed`| `processing` | %85 | Tüm kalite varyantları, sprite ve poster hazır |
| `upload_started` | `processing` | %90 | Depolama sunucusuna paralel rsync başladı |
| `completed` | `completed` | %100 | Tüm işlem başarıyla tamamlandı (tüm CDN URL'leri ve `perf_stats` ile) |
| `cancelled` | `cancelled` | %0 | İşlem iptal edildi |
| `failed` | `failed` | %0 | Hata oluştu |
