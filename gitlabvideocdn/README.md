# GitLab CI/CD Video HLS Converter & Processor Service

Bu modül (`gitlabvideocdn/`), GitLab CI/CD Runner altyapısı üzerinde çalışan, **Modal.com servisiyle birebir aynı yetenek ve webhook JSON formatına sahip** yüksek performanslı bir video HLS dönüştürme ve CDN yükleme çözümüdür.

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

## 🛠️ Tetikleme Yöntemleri

### 1. FastAPI Gateway ile Tetikleme (Tavsiye Edilen)

Gateway sunucusunu başlatın:

```bash
uvicorn gitlabvideocdn.api_server:app --host 0.0.0.0 --port 8000
```

`POST /convert_request` endpoint'ine Modal ile birebir aynı istek atılır:

```bash
curl -X POST http://localhost:8000/convert_request \
  -H "Content-Type: application/json" \
  -d '{
    "admin_token": "hls_adm_7f9c2e4a1b8d3f5e6a0b9c8d7e6f5a4b3c2d1e0f9a8b7c6d",
    "video_url": "https://video.xfoy.dev/uploads/sample.mp4",
    "webhook_url": "https://siteniz.com/api/video_webhook",
    "cdn_domain": "https://cdn.domain.com",
    "username": "huseyin",
    "custom_id": "POST_1001",
    "qualities": ["360p", "720p", "1080p"],
    "sprite": true,
    "encrypt": true,
    "key_url": "https://siteniz.com/api/get_key?id=POST_1001",
    "storage_host": "u123456.your-storagebox.de",
    "storage_user": "u123456",
    "storage_pass": "gizli_sifre",
    "storage_port": 23,
    "target_dir": "hls"
  }'
```

---

### 2. Doğrudan GitLab Pipeline Trigger API ile Tetikleme

GitLab üzerinde **Settings -> CI/CD -> Pipeline trigger tokens** bölümünden bir token oluşturun:

```bash
curl -X POST \
  --form token="GL_TRIGGER_TOKEN_BURAYA" \
  --form ref="main" \
  --form "variables[PAYLOAD_JSON]={\"video_url\":\"https://domain.com/video.mp4\",\"webhook_url\":\"https://site.com/webhook\",\"cdn_domain\":\"https://cdn.domain.com\",\"username\":\"huseyin\",\"storage_host\":\"u123.your-storagebox.de\",\"storage_user\":\"u123\",\"storage_pass\":\"pass\"}" \
  "https://gitlab.com/api/v4/projects/huseyinduygun%2Fvideo-convert/trigger/pipeline"
```

---

### 3. GitLab CI/CD Ortam Değişkenleri (CI/CD Variables)

GitLab projenizde **Settings -> CI/CD -> Variables** altında varsayılan değerleri tanımlayabilirsiniz:

| Değişken | Açıklama |
| :--- | :--- |
| `ADMIN_TOKEN` | API Gateway yetkilendirme anahtarı |
| `SECRET_KEY` | HMAC SHA256 imza doğrulama anahtarı |
| `GITLAB_TRIGGER_TOKEN` | Pipeline trigger token |
| `GITLAB_PRIVATE_TOKEN` | Pipeline iptali ve durum sorgusu için Personal Access Token |
| `STORAGE_HOST` | Varsayılan Hetzner Storage Box / SSH host |
| `STORAGE_USER` | Varsayılan SSH kullanıcı adı |
| `STORAGE_PASS` | Varsayılan SSH şifresi |
| `STORAGE_PORT` | Varsayılan SSH portu (Genellikle 22 veya 23) |

---

## 📤 Webhook Olayları (Events)

| Step | Status | Progress | Açıklama |
| :--- | :--- | :--- | :--- |
| `download_started` | `processing` | %0 | aria2c indirme başladı |
| `download_completed` | `processing` | %10 | İndirme ve ffprobe analizi tamamlandı |
| `conversion_started` | `processing` | %15 | FFmpeg HLS kodlama başladı |
| `converting` | `processing` | %15-%85 | Canlı kodlama ilerlemesi (5s debounced) |
| `conversion_completed`| `processing` | %85 | Tüm kalite varyantları, sprite ve poster hazır |
| `upload_started` | `processing` | %90 | Depolama sunucusuna paralel rsync başladı |
| `completed` | `completed` | %100 | Tüm işlem başarıyla tamamlandı (CDN URL'leri ile) |
| `cancelled` | `cancelled` | %0 | İşlem iptal edildi |
| `failed` | `failed` | %0 | Hata oluştu |
