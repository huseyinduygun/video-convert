import os
import shutil
import signal
import sys
import threading
import time

import requests


def send_webhook_async(webhook_url: str, payload: dict):
    """Arka planda asenkron HTTP POST webhook gönderir."""
    try:
        requests.post(webhook_url, json=payload, timeout=5)
    except Exception as err:
        print(f"Webhook gönderme hatası ({payload.get('step')}, %{payload.get('progress')}): {err}")


def send_webhook_sync(webhook_url: str, payload: dict):
    """Konteyner/Job sonlanmadan önce webhook'un ulaştığını garanti eden senkron çağrı."""
    try:
        res = requests.post(webhook_url, json=payload, timeout=8)
        print(f"[{payload.get('video_id')}] Senkron Webhook gönderildi "
              f"(step: {payload.get('step')}, status: {payload.get('status')}, HTTP {res.status_code})")
    except Exception as err:
        print(f"[{payload.get('video_id')}] Senkron Webhook uyarısı "
              f"({payload.get('step')}, %{payload.get('progress')}): {err}")


class TaskCancelledOrTimeout(Exception):
    pass


def check_and_raise_cancellation(video_id: str, work_dir: str = None):
    """
    Çalışma dizini üzerindeki cancel.flag varlığını denetler.
    Eğer bayrak bulunduysa klasörü temizler ve TaskCancelledOrTimeout hatası fırlatır.
    """
    target_dir = work_dir or f"/tmp/gitlab_convert_{video_id}"
    flag_file = f"{target_dir}/cancel.flag"
    if os.path.exists(flag_file):
        print(f"[{video_id}] Durdurma bayrağı ({flag_file}) tespit edildi! İşlem sonlandırılıyor...")
        if os.path.exists(target_dir):
            try:
                shutil.rmtree(target_dir, ignore_errors=True)
            except Exception:
                pass
        raise TaskCancelledOrTimeout("İşlem kullanıcı tarafından durduruldu.")


class ProgressTracker:
    def __init__(self, webhook_url: str, video_id: str, custom_id: str):
        self.webhook_url = webhook_url
        self.video_id = video_id
        self.custom_id = custom_id
        self.last_sent_step = -10
        self.last_sent_time = 0.0
        self.completed_qualities = []
        self.lock = threading.Lock()

    def send_event(self, step: str, progress: int = None, status="processing", extra=None):
        if not self.webhook_url:
            return

        check_and_raise_cancellation(self.video_id)
        with self.lock:
            pct = progress if progress is not None else (self.last_sent_step if self.last_sent_step >= 0 else 0)
            now = time.time()

            # Debouncing: converting adımı sırasında çok sık webhook gitmesini önle (en az 5 saniye veya %10 fark)
            if progress is not None and status == "processing" and step == "converting":
                target_step = (progress // 10) * 10
                time_diff = now - self.last_sent_time
                if target_step < self.last_sent_step + 10 and time_diff < 5.0:
                    return
                self.last_sent_step = target_step
                self.last_sent_time = now
                pct = target_step
            elif progress is not None:
                self.last_sent_step = progress
                self.last_sent_time = now

            payload = {
                "status": status,
                "step": step,
                "progress": pct,
                "video_id": self.video_id,
                "custom_id": self.custom_id,
                "runner": "gitlab-ci"
            }
            if extra:
                payload.update(extra)

            if status in ["failed", "completed", "cancelled"] or step in ["failed", "completed", "cancelled"]:
                send_webhook_sync(self.webhook_url, payload)
            else:
                threading.Thread(target=send_webhook_async, args=(self.webhook_url, payload), daemon=True).start()

    def record_variant_completed(self, quality_name: str, progress: int):
        with self.lock:
            if quality_name not in self.completed_qualities:
                self.completed_qualities.append(quality_name)
            qualities_copy = list(self.completed_qualities)

        self.send_event(
            step="variant_completed",
            progress=progress,
            extra={
                "completed_quality": quality_name,
                "completed_qualities": qualities_copy
            }
        )


def setup_cancellation_and_timeout_handlers(tracker: ProgressTracker, start_time: float, work_dir: str = None):
    """
    GitLab Runner'ın veya sistemin tetiklediği SIGTERM, SIGINT sinyallerini yakalar
    ve senkron 'cancelled' / 'failed' webhook'u göndererek temizlik yapar.
    """
    def handle_signal(sig, frame):
        sig_name = (
            "SIGTERM (GitLab Cancel/Timeout)" if sig == signal.SIGTERM
            else ("SIGINT (İptal)" if sig == signal.SIGINT else f"Sinyal {sig}")
        )
        elapsed_sec = round(time.time() - start_time, 2)
        print(f"[{tracker.video_id}] Sinyal yakalandı ({sig_name}). Webhook gönderiliyor...")
        tracker.send_event(
            step="cancelled", status="cancelled",
            extra={
                "error": f"TaskCancelledOrTimeout: İşlem {sig_name} ile durduruldu.",
                "message": "Dönüştürme işlemi GitLab CI/CD üzerinden iptal edildi veya zaman aşımına uğradı.",
                "elapsed_time_seconds": elapsed_sec,
                "processing_time": f"{elapsed_sec}s"
            }
        )
        if work_dir and os.path.exists(work_dir):
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass
        sys.exit(1)

    try:
        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)
        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, handle_signal)
    except Exception as e:
        print(f"Signal handler kaydetme uyarısı: {e}")
