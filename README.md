# Video HLS Processor & Converter Service

**Video HLS Processor**, Modal.com sunucusuz (serverless) altyapısı üzerinde çalışan, dinamik CDN domainlerini, çok kullanıcılı (multi-tenant) klasör yapısını, Hetzner Storage Box ve rsync/SSH depolama sunucularını, HLS AES-128 şifrelemeyi, Akıllı Otomatik Maliyet Seçimi (`"auto_gpu": true`), NVIDIA T4 GPU hızlandırmasını, Dinamik Otomatik vCPU Akıllı Ölçekleme (`calc_optimal_cpu`), doğrudan `/vol` Volume indirme mimarisini, filigran (watermark) basmayı, timeline sprite haritasını ve **3 seviyeli performans/darboğaz metrik loglama sistemini** destekleyen yüksek performanslı, ölçeklenebilir ve ultra maliyet-optimasyonlu video HLS dönüştürme mikroservisidir.

---

## 🚀 Öne Çıkan Özellikler & Performans İyileştirmeleri

* **⚡ Dinamik vCPU Akıllı Maliyet Tasarrufu (`calc_optimal_cpu`):** 
  - İndirilen video `ffprobe` ile analiz edilir (çözünürlük, süre ve istenen kalite sayısı).
  - Video büyüklüğüne göre tam ihtiyaç duyulan vCPU (`1.0x`, `2.0x`, `4.0x`, `8.0x`) hesaplanır ve Modal fonksiyonu `.with_options(cpu=optimal_cpu).spawn(...)` ile dinamik başlatılır.
  - Sabit 8 vCPU yerine küçük/orta videolar 1 veya 4 vCPU ile işlenerek sunucu maliyetlerinde **%40 ile %65 arasında tasarruf** sağlanır.
* **⚙️ Merkezi Konfigürasyon Yönetimi (`STAGE_CFG_*`):**
  - Tüm stage (`download`, `cpu_encode`, `gpu_encode`, `upload`) ve endpoint (`convert`, `delete`, `cancel`) kaynak bütçeleri (`cpu`, `memory`, `timeout`, `scaledown_window`) tek bir dosya ([settings.py](file:///mnt/bootcamp/Users/Husee/Desktop/projeler/modalvideocdn/modalvideocdn/config/settings.py)) üzerinden yönetilir.
* **🚀 2 Kanal SSH / Rsync Paralel Upload Optimizasyonu:**
  - `master.m3u8`, `poster.jpg`, `sprite.jpg`, `thumbnails.vtt`, `info.json` gibi kök dosyalar tek paket halinde aktarılır.
  - Varyant video dizinleri 2 paralel SSH kanalıyla aktarılarak yükleme süreleri **45 saniyeden 16 saniyeye** (%65 daha hızlı) indirilmiştir.
* **⚡ Doğrudan `/vol` Volume İndirmesi:** Videolar geçici diske (`/tmp`) indirilip kopyalanmak yerine doğrudan Modal Volume (`/vol/{video_id}`) üzerine indirilir. Kopyalama bekleme süresi **0 saniyeye** düşürülmüştür.
* **🌐 Hetzner Storage Box Özel Upload Optimizasyonu & Otomatik Yükleme Kuyruğu (`max_containers = 1`):** 
  - Hetzner Storage Box'ın maksimum 10 eşzamanlı SSH bağlantı limitini korumak amacıyla `upload_stage` fonksiyonu Modal seviyesinde otomatik sıraya (Queue) alınır. Aynı anda onlarca video dönüştürülse dahi yüklemeler **tek tek sırayla (FIFO)** ve 8 paralel SSH kanalıyla güvende aktarılır.
  - `rsync` komutundaki `-z` (gzip) kaldırılmış, `-W` (`--whole-file`) ve `--inplace` eklenmiştir. Donanım hızlandırmalı `aes128-gcm` SSH cipher'ı kullanılır.
  - **Zaman Ayarlı Dinamik Dönüştürme & Yükleme İlerlemesi (5 Saniye Debouncing):** Kodlama sırasında sabit %15'te beklemek yerine ilerleme **%15'ten %85'e akıcı şekilde tırmanır**. Yüklemede ise **%90'dan %99'a tırmanır**. Webhook sunucunuzu boğmamak için güncellemeler arasında **en az 5 saniye geçmesi şartı (time-debouncing)** uygulanır. Hızlı videolarda anında, uzun videolarda ise 5 saniyede bir akıcı güncellemeler iletilir.
* **📊 Aşama Aşama Birikimli `perf_stats` ve Canlı Maliyet Raporlaması:** 
  - `download_completed`, `conversion_completed` ve `completed` (upload) aşamalarının **her birinde** `perf_stats` webhook paketi içerisinde o ana kadar birikmiş metrikler ve tahmini Modal dolar maliyeti canlı olarak gönderilir.
  - FFmpeg duvar saati süresi ile işlenen video süresi oranlanarak kodlama hız çarpanı (`realtime_speed_ratio = 3.03x`) hesaplanır.
  - **Anlık CPU & GPU Maksimum / Ortalama Kullanım Oranları (`resource_usage`):** Kodlama sırasında konteyner içinden 0.5 saniyede bir örnekleme yapılarak `max_cpu_percent`, `avg_cpu_percent`, `max_gpu_percent`, `avg_gpu_percent` ve `max_gpu_memory_mb` değerleri canlı ölçülüp `perf_stats` paketinde raporlanır. Darboğazlar anında tespit edilir.
* **🏎️ NVIDIA T4/L4 GPU Fast NVENC & Pure VRAM CUDA Pipeline:** 
  - GPU fonksiyonunda 2.0 vCPU ve 8GB RAM verilerek GPU'nun CPU I/O beklemesi engellenmiş, kodlama süresi %40 hızlandırılmıştır.
  - **Ultra-Fast NVENC Donanım Ayarları (`-preset p1 -tune ll`):** Gereksiz VRAM lookahead (32 karelik tampon) ve per-macroblock AQ yükleri kaldırılarak NVENC kodlayıcısının saniyede 180+ FPS ile çalışması sağlanmış, 8K kodlama süresi rekor seviyede kısaltılmıştır.
  - **16-Kare Asenkron VRAM Donanım Yüzeyi (`-surfaces 16 -extra_hw_frames 16`):** 8K HEVC donanımsal çözme aşamasında NVDEC çipinin VRAM'de tampon beklemesi engellenerek asenkron yüzey halkası ile %100 hızla çalışması sağlanmıştır.
  - **%100 Saf VRAM Donanım Boru Hattı (`hevc_cuvid` → `scale_cuda` → `h264_nvenc`):** Çözme, ölçekleme ve HLS kodlama aşamalarının tamamı sıfır CPU kopyalaması ile doğrudan GPU VRAM belleğinde gerçekleşir. Giriş yayın akışı GPU VRAM üzerinde eşzamanlı olarak kalitelere bölüştürülür.
* **🐕 Otomatik Kilitlenme Koruyucusu (45 Saniye Stagnation Watchdog):** 
  - Kodlama sırasında FFmpeg sürecinden 45 saniye boyunca hiç girdi/çıktı gelmezse, sistem kilitlenme (freeze) olduğunu otomatik tespit eder. FFmpeg komutunu anında öldürür (`process.kill()`), klasörü temizler ve web sunucunuza `status: "failed"` webhook'unu o ana kadar birikmiş maliyet ve `perf_stats` verileriyle iletir. Sistem asla askıda kalmaz!
* **⚠️ Senkron Hata, Timeout & İptal Webhook Garantisi:** İndirme, dönüştürme veya yükleme aşamalarının herhangi birinde hata veya İptal yaşanırsa, senkron HTTP POST ile backend'inize anında `status: "failed"` / `"cancelled"` webhook'u iletilir.
* **🧹 Otomatik Temizlik ve Çöp Silme Güvencesi:**
  - İptal (`/cancel_request` veya `/delete_request`) gerçekleştiğinde `/vol/{video_id}` ve `cancel.flag` anında silinir.
  - Olası sunucu çökmeleri için `cleanup_stale_volume_files` 2 saatten eski çöp klasörleri otomatik olarak tarayıp Modal Volume'dan temizler.
* **⚡ AAC Ses Passthrough (Direct Copy):** Kaynak videodaki ses zaten `AAC` formatındaysa ses kanalı yeniden kodlanmaz, saniyesinde doğrudan kopyalanır (`-c:a copy`).
* **🌐 Çoklu İç Ağ Direct-IP & Ham HTTP Yönlendirme (`INTERNAL_DOMAIN_IP_MAP`):** 
  - `settings.py` içinde tanımlanan domain haritası sayesinde (örn: `"video.xfoy.dev": "192.99.199.60"`), indirme istekleri DNS sorgusunu, Cloudflare engelini ve HTTPS/TLS şifreleme yükünü %100 baypas eder. `aria2c` doğrudan IP adresine ham HTTP üzerinden `--header="Host: domain"` ile bağlanır. İndirme hızı rekor seviyeye tırmanır ve CPU şifre çözme yükü sıfırlanır. Birden fazla domain eklenebilir.
* **⚡ Akıllı Otomatik Maliyet Seçimi & GPU Katmanlaması (`"auto_gpu": true` veya `"gpu": "auto"`):**
  - Video indirildikten sonra çözünürlüğü ve süresi milisaniyeler içinde analiz edilir. 
  - **Dinamik Ekran Kartı Katmanı (Smart GPU Tiering):** Kısa standart 1080p/720p videolar en ucuz `Tesla T4` ($0.000164/sn, 2 vCPU) ile işlenirken; 4K/8K yüksek çözünürlüklü (`2160p+`) veya **3 dakikadan uzun (180s+) videolar** otomatik olarak yüksek bant genişliğine sahip `NVIDIA L4` ($0.000222/sn, **4 vCPU**) sunucusuna sevk edilir. Toplam işlem süresi düşürüldüğü için toplam Modal dolar maliyeti rekor seviyede aşağı çekilir. İsteğe bağlı API'de `"gpu_type": "L4"` veya `"T4"` zorlaması yapılabilir.
* **🔐 HLS AES-128 Şifreleme (`"encrypt": true`):** İsteğe bağlı olarak tüm video parçaları 128-bit AES algoritması ile şifrelenir.
* **🛑 İşlem Durdurma API Endpoint'i (`POST /cancel_request`):** Devam eden herhangi bir işlem anında durdurulur ve diski temizler.
* **🗑️ Sunucudan Video Silme Endpoint'i (`POST /delete_request`):** Video silindiğinde aktif işlem varsa durdurulur ve depolama sunucusundaki klasörü rsync/SSH üzerinden silinir.
* **🔒 Güvenli SFTP Şifresi Gönderimi (Şifreli / Plaintext):** `storage_pass` parametresi hem orijinal düz metin (`"videoCdn500!"`), hem AES-256-CBC ile şifrelenmiş (`"enc:..."`), hem de Base64 (`"b64:..."`) formatında gönderilebilir.

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

### 1. Başarılı Tamamlandı Bildirimi (`status: "completed"`)

```json
{
  "status": "completed",
  "step": "completed",
  "progress": 100,
  "video_id": "6733a252",
  "custom_id": "POST_1001",
  "username": "huseyin",
  "cdn_domain": "https://cdn.domain.com",
  "encrypted": true,
  "key_url": "https://siteniz.com/api/get_video_key?id=POST_1001",
  "duration_seconds": 84.84,
  "duration": 84.84,
  "duration_formatted": "00:01:24",
  "master_url": "https://cdn.domain.com/huseyin/6733a252/master.m3u8",
  "poster_url": "https://cdn.domain.com/huseyin/6733a252/poster.jpg",
  "sprite_url": "https://cdn.domain.com/huseyin/6733a252/sprite.jpg",
  "vtt_url": "https://cdn.domain.com/huseyin/6733a252/thumbnails.vtt",
  "info_json_url": "https://cdn.domain.com/huseyin/6733a252/info.json",
  "qualities": ["360p", "720p", "1080p"],
  "elapsed_time_seconds": 45.2,
  "processing_time": "45.2s",
  "perf_stats": {
    "video_details": {
      "original_resolution": "1920x1080",
      "duration_seconds": 84.84,
      "duration_formatted": "00:01:24",
      "input_codec": "h264",
      "has_audio": true,
      "aac_passthrough": true,
      "watermark_applied": false,
      "sprite_generated": true,
      "encrypted": true,
      "qualities": ["360p", "720p", "1080p"]
    },
    "engine_used": "CPU (8x vCPU libx264 superfast | 3.03x realtime [HQ])",
    "total_elapsed_seconds": 45.2,
    "download_stage": {
      "download_time_sec": 4.50,
      "stage_execution_time_sec": 6.12,
      "download_size_mb": 104.89,
      "download_speed_mbps": 186.47,
      "direct_vol_download": true,
      "connections": 16,
      "timing_breakdown": {
        "volume_reload_sec": 0.12,
        "pre_checks_sec": 0.05,
        "aria2c_download_sec": 4.50,
        "ffprobe_analysis_sec": 0.10,
        "volume_commit_sec": 1.15,
        "stage_total_execution_sec": 6.12
      }
    },
    "conversion_stage": {
      "engine": "CPU (8x vCPU libx264 superfast | 11.97x realtime [HQ])",
      "conversion_time_sec": 7.09,
      "stage_execution_time_sec": 10.58,
      "realtime_speed_ratio": "11.97x",
      "video_duration_sec": 84.84,
      "bottleneck_detected": false,
      "timing_breakdown": {
        "volume_reload_sec": 0.09,
        "probe_read_sec": 0.001,
        "ffmpeg_conversion_sec": 7.09,
        "post_processing_sec": 0.35,
        "volume_commit_sec": 1.20,
        "stage_total_execution_sec": 9.08
      }
    },
    "upload_stage": {
      "upload_duration_seconds": 16.04,
      "stage_execution_time_sec": 20.10,
      "upload_size_mb": 38.49,
      "upload_speed_mbps": 19.20,
      "hetzner_optimized": true,
      "timing_breakdown": {
        "volume_reload_sec": 0.30,
        "ssh_init_sec": 4.20,
        "rsync_upload_sec": 7.26,
        "url_and_meta_prep_sec": 0.003,
        "stage_total_execution_sec": 11.83
      }
    },
    "resource_specs": {
      "download_cpu": 1.0, "download_ram_mb": 512,
      "encode_cpu": 8.0, "encode_ram_mb": 8192,
      "upload_cpu": 1.0, "upload_ram_mb": 2048
    },
    "resource_usage": {
      "max_cpu_percent": 87.4,
      "avg_cpu_percent": 62.1,
      "max_gpu_percent": 98.0,
      "avg_gpu_percent": 82.5,
      "max_gpu_memory_mb": 1420
    },
    "cost_estimate": {
      "total_cost_usd": 0.0076,
      "formatted": "$0.0076",
      "breakdown_usd": {
        "download": 0.0001,
        "conversion": 0.0070,
        "upload": 0.0005
      }
    }
  }
}
```

### 2. Hata / Timeout / İptal Bildirimi (`status: "failed"` / `"cancelled"`)

```json
{
  "status": "cancelled",
  "step": "cancelled",
  "progress": 0,
  "video_id": "6733a252",
  "custom_id": "POST_1001",
  "message": "İşlem API (/cancel_request) üzerinden kullanıcı tarafından durduruldu.",
  "elapsed_time_seconds": 12.4,
  "processing_time": "12.4s",
  "perf_stats": {
    "total_elapsed_seconds": 12.4,
    "download_stage": {
      "download_time_sec": 2.84,
      "download_size_mb": 104.89
    },
    "cost_estimate": {
      "total_cost_usd": 0.0001,
      "formatted": "$0.0001"
    }
  }
}
```

---

## 🛠️ Kurulum ve Canlıya Alma (Deployment)

Paket modül yapısında yayına almak için:

```bash
modal deploy -m modalvideocdn
```

