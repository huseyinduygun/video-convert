# Semaphore CI Video HLS Converter & Processor Service

Bu servis (`semaphorevideocdn/`), herhangi bir ara web servisi / API gateway gerektirmeden, **doğrudan Semaphore CI Pipeline / Workflow API ve parametreleri ile tetiklenen**, Modal.com ve GitLab servisleriyle birebir aynı yetenek ve webhook JSON formatına sahip video HLS dönüştürme ve CDN yükleme çözümüdür.

---

## 🌟 Özellikler

* **⚡ Sıfır Ek Sunucu:** Doğrudan Semaphore CI API ile tetiklenir.
* **🚀 16x Paralel aria2c İndirme & Direct-IP Baypas:** Cloudflare ve TLS yükünü baypas ederek doğrudan iç ağ IP'sinden indirme.
* **🎬 Çoklu Çözünürlük HLS libx264/NVENC:** `360p`, `720p`, `1080p`, `1440p`, `2160p`, `4320p` uyarlanabilir akış.
* **🔐 HLS AES-128 Şifreleme:** Güvenli anahtar yönetimi (`encrypt: true`).
* **🖼️ Timeline Sprite & Thumbnails VTT:** Oynatıcı önizleme çubuğu için sprite haritası.
* **⚡ Hetzner Storage Box 4x Paralel SSH rsync:** Optimize SSH ControlMaster ile hızlı aktarım.
* **📊 Canlı `perf_stats` ve 5 Saniye Debounced Webhook:** Darboğaz ve CPU/RAM kullanım raporlaması (`runner: "semaphore-ci"`).
* **🛑 Güvenli İptal ve Temizlik:** Semaphore CI workflow iptal edildiğinde (SIGTERM) senkron `cancelled` webhook bildirimi ve anında disk temizliği.

---

## 🚀 Semaphore CI Tetikleme (API) Kullanımı

Detaylı API entegrasyonu ve kod örnekleri için ana dizindeki [README_SEMAPHORE.md](../README_SEMAPHORE.md) dokümanını inceleyebilirsiniz.
