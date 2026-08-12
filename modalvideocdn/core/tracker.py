import os
import shutil
import signal
import sys
import threading
import time

import requests


def send_webhook_async(webhook_url: str, payload: dict):
    try:
        requests.post(webhook_url, json=payload, timeout=5)
    except Exception as err:
        print(f"Webhook gönderme hatası ({payload.get('step')}, %{payload.get('progress')}): {err}")


def send_webhook_sync(webhook_url: str, payload: dict):
    """Konteyner sonlanmadan önce webhook'un ulaştığını garanti eder."""
    try:
        res = requests.post(webhook_url, json=payload, timeout=8)
        print(f"[{payload.get('video_id')}] Senkron Webhook gönderildi "
              f"(step: {payload.get('step')}, status: {payload.get('status')}, HTTP {res.status_code})")
    except Exception as err:
        print(f"[{payload.get('video_id')}] Senkron Webhook uyarısı "
              f"({payload.get('step')}, %{payload.get('progress')}): {err}")


class ProgressTracker:
    def __init__(self, webhook_url: str, video_id: str, custom_id: str):
        self.webhook_url = webhook_url
        self.video_id = video_id
        self.custom_id = custom_id
        self.last_sent_step = -10
        self.completed_qualities = []
        self.lock = threading.Lock()

    def send_event(self, step: str, progress: int = None, status="processing", extra=None):
        with self.lock:
            pct = progress if progress is not None else (self.last_sent_step if self.last_sent_step >= 0 else 0)

            if progress is not None and status == "processing" and step == "converting":
                target_step = (progress // 10) * 10
                if target_step < self.last_sent_step + 10:
                    return
                self.last_sent_step = target_step
                pct = target_step
            elif progress is not None:
                self.last_sent_step = progress

            payload = {
                "status": status,
                "step": step,
                "progress": pct,
                "video_id": self.video_id,
                "custom_id": self.custom_id
            }
            if extra:
                payload.update(extra)

            if status in ["failed", "completed"] or step in ["failed", "completed"]:
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
    Modal sunucusunun veya kullanıcının tetiklediği SIGTERM, SIGINT veya SIGALRM
    sinyallerini yakalar ve senkron 'failed' webhook'u gönderir.
    """
    def handle_signal(sig, frame):
        sig_name = (
            "SIGTERM (İptal/Cancel)" if sig == signal.SIGTERM
            else ("SIGINT (Kullanıcı İptali)" if sig == signal.SIGINT else f"Sinyal {sig}")
        )
        elapsed_sec = round(time.time() - start_time, 2)
        print(f"[{tracker.video_id}] Modal Sinyali yakalandı ({sig_name}). Webhook gönderiliyor...")
        tracker.send_event(
            step="failed", status="failed",
            extra={
                "error": f"TaskCancelledOrTimeout: İşlem {sig_name} sinyali ile durduruldu.",
                "message": "Dönüştürme işlemi iptal edildi veya zaman aşımına uğradı.",
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
