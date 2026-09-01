# CircleCI Video HLS Converter & Processor Service

Bu servis (`circlecivideocdn/`), herhangi bir ara web servisi / API gateway gerektirmeden, **doğrudan CircleCI Pipeline API v2 ve pipeline parametreleri ile tetiklenen**, Modal.com, GitLab CI ve Semaphore CI servisleriyle birebir aynı yetenek ve webhook JSON formatına sahip video HLS dönüştürme ve CDN yükleme çözümüdür.

---

## 🌟 Özellikler

* **⚡ Sıfır Ek Sunucu:** Doğrudan CircleCI API v2 ile tetiklenir (`POST /api/v2/project/{project-slug}/pipeline`).
* **🚀 16x Paralel aria2c İndirme & Direct-IP Baypas:** Cloudflare ve TLS yükünü baypas ederek doğrudan iç ağ IP'sinden indirme.
* **🎬 Çoklu Çözünürlük HLS libx264/NVENC:** `360p`, `720p`, `1080p`, `1440p`, `2160p`, `4320p` uyarlanabilir akış.
* **🔐 HLS AES-128 Şifreleme:** Güvenli anahtar yönetimi (`encrypt: true`).
* **🖼️ Timeline Sprite & Thumbnails VTT:** Oynatıcı önizleme çubuğu için sprite haritası.
* **⚡ Hetzner Storage Box 4x Paralel SSH rsync:** Optimize SSH ControlMaster ile hızlı aktarım.
* **📊 Canlı `perf_stats` ve 5 Saniye Debounced Webhook:** Darboğaz ve CPU/RAM kullanım raporlaması (`runner: "circleci"`).
* **🛑 Güvenli İptal ve Temizlik:** CircleCI pipeline iptal edildiğinde (SIGTERM) senkron `cancelled` webhook bildirimi ve anında disk temizliği.

---

## 🚀 CircleCI Tetikleme (API) Kullanımı

Detaylı API entegrasyonu ve kod örnekleri için ana dizindeki [README_CIRCLECI.md](../README_CIRCLECI.md) dokümanını inceleyebilirsiniz.
