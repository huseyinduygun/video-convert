# Video HLS Processor & Converter Service

**Video HLS Processor**, Modal.com sunucusuz (serverless) altyapısı üzerinde çalışan, dinamik CDN domainlerini, çok kullanıcılı (multi-tenant) klasör yapısını, rsync/SSH depolama sunucularını, HLS AES-128 şifreleme, Akıllı Otomatik Maliyet Seçimi (`"auto_gpu": true`), NVIDIA L4 Ada Lovelace GPU hızlandırması, filigran (watermark) basma, timeline sprite haritası ve sunucudan tek tıkla video silme özelliklerini destekleyen yüksek performanslı, ölçeklenebilir ve ultra maliyet-optimasyonlu video HLS dönüştürme mikroservisidir.

---

## 🚀 Öne Çıkan Özellikler & Performans İyileştirmeleri

* **🏎️ Yeni Nesil NVIDIA L4 GPU Desteği:** GPU işlem motoru **NVIDIA L4 (Ada Lovelace)** seviyesine yükseltildi. İçindeki 8. nesil NVENC donanım çipi sayesinde T4'e kıyasla **3-4 kat daha hızlı kodlama** sağlar.
* **⚠️ Senkron Hata, Timeout & İptal Webhook Garantisi:** İndirme, dönüştürme veya yükleme aşamalarının herhangi birinde hata oluşursa veya **Zaman Aşımı (Timeout)** veya **Kullanıcı İptali (Cancel / SIGTERM)** yaşanırsa, konteyner kapanmadan önce senkron HTTP POST ile backend'inize anında `status: "failed"` webhook'u iletilir.
* **⚡ AAC Ses Passthrough (Direct Copy):** Kaynak videodaki ses zaten `AAC` formatındaysa ses kanalı yeniden kodlanmaz, saniyesinde doğrudan kopyalanır (`-c:a copy`).
* **🎯 GOP & Keyframe Hızlı Segment Kesimi:** HLS parçalamasında `-g 120 -keyint_min 60 -sc_threshold 0` ayarları ile sahne arama yükü kaldırılmış ve HLS parçalama hızı pik noktaya çekilmiştir.
* **⚡ Akıllı Otomatik Maliyet Seçimi (`"auto_gpu": true` veya `"gpu": "auto"`):** Video indirildikten sonra süresi ve çözünürlüğü milisaniyeler içinde analiz edilir. En ucuz maliyeti sağlayacak işlemci (CPU veya GPU) otomatik seçilir.
  * **Kısa / Orta Videolar (< 10 dk / 1080p):** **CPU (libx264 Ultrafast)** seçilir (GPU'ya göre **3 kat daha ucuz**).
  * **Uzun Videolar (>= 10 dk / 600s) veya 4K/2K (>= 1440p) Videolar:** **NVIDIA L4 GPU (NVENC P1)** seçilir (CPU'ya göre **2 kat daha ucuz ve 17 kat daha hızlı**).
* **🔐 HLS AES-128 Şifreleme (`"encrypt": true`):** İsteğe bağlı olarak tüm `.jpg`/`.ts` video parçaları 128-bit AES algoritması ile şifrelenir. `"encrypt": true` gönderildiğinde `"key_url"` (anahtar API linki) zorunludur. Gizli anahtar dosyası public CDN sunucusuna kesinlikle yüklenmez.
* **🗑️ Sunucudan Video Silme Endpoint'i (`POST /delete_request`):** Müşteriniz panelden bir videoyu sildiğinde, depolama sunucusundaki `{target_dir}/{username}/{video_id}` klasörü rsync/SSH üzerinden güvenle silinir.
* **🖼️ Timeline Sprite ve WebVTT Haritası (`"sprite": true`):** Video oynatıcılarında (Player) sarma çubuğunda (seek bar) fareyle ilerlerken çıkan küçük kare resimler (`sprite.jpg` ve `thumbnails.vtt`) otomatik üretilir.
* **💧 Nisbi Ölçeklenen Filigran / Logo (Watermark):** `watermark_url` gönderildiğinde logo, video çözünürlüğüne (360p, 720p, 1080p) orantılı olarak (%15 genişlikte) otomatik küçültülür ve 10 farklı pozisyon seçeneğiyle videoya basılır.

---

## 📤 Webhook Bildirim Yapıları (Webhook Events)

### 1. Başarılı Tamamlandı Bildirimi (`status: "completed"`)

```json
{
  "status": "completed",
  "step": "completed",
  "progress": 100,
  "video_id": "6733a252",
  "custom_id": "POST_1001",
  "username": "huseyin",
  "cdn_domain": "https://cdn.xfoy.dev",
  "encrypted": true,
  "key_url": "https://siteniz.com/api/get_video_key?id=POST_1001",
  "duration_seconds": 29.95,
  "duration": 29.95,
  "duration_formatted": "00:00:29",
  "master_url": "https://cdn.xfoy.dev/huseyin/6733a252/master.m3u8",
  "poster_url": "https://cdn.xfoy.dev/huseyin/6733a252/poster.jpg",
  "sprite_url": "https://cdn.xfoy.dev/huseyin/6733a252/sprite.jpg",
  "vtt_url": "https://cdn.xfoy.dev/huseyin/6733a252/thumbnails.vtt",
  "info_json_url": "https://cdn.xfoy.dev/huseyin/6733a252/info.json",
  "qualities": ["360p", "720p", "1080p"],
  "elapsed_time_seconds": 24.5,
  "processing_time": "24.5s"
}
```

### 2. Hata / Timeout / İptal Bildirimi (`status: "failed"`)

Beklenmeyen bir hata, zaman aşımı (timeout) veya görev iptali (cancel) yaşandığında gönderilen bildirim:

```json
{
  "status": "failed",
  "step": "failed",
  "progress": 0,
  "video_id": "6733a252",
  "custom_id": "POST_1001",
  "error": "TaskCancelledOrTimeout: Dönüştürme görevi SIGTERM (İptal/Cancel) sinyali ile durduruldu veya zaman aşımına (timeout) uğradı.",
  "message": "Dönüştürme işlemi iptal edildi veya zaman aşımına (timeout) uğradı.",
  "elapsed_time_seconds": 1800.0,
  "processing_time": "1800s"
}
```

---

## 🛠️ Kurulum ve Canlıya Alma (Deployment)

```bash
modal deploy main.py
```
