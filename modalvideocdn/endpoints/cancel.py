import os
import modal

from ..config import app, volume, STAGE_CFG_CANCEL
from ..core import image_cpu, verify_request_auth, send_webhook_sync


@app.function(image=image_cpu, volumes={"/vol": volume}, **STAGE_CFG_CANCEL)
@modal.concurrent(max_inputs=100)
@modal.fastapi_endpoint(method="POST")
def cancel_request(data: dict):
    """
    HTTP POST Endpoint: Devam eden bir video indirme/dönüştürme/yükleme işlemini iptal eder.
    Payload:
    {
        "video_id": "6733a252",
        "custom_id": "VID_123", (opsiyonel)
        "webhook_url": "https://domain.com/webhook", (opsiyonel)
        "token": "..." (veya X-Admin-Token header)
    }
    """
    if not isinstance(data, dict):
        return {"status": "failed", "error": "Geçersiz JSON verisi."}

    verify_request_auth(data)

    video_id = data.get("video_id")
    if not video_id:
        return {"status": "failed", "error": "video_id parametresi zorunludur."}

    custom_id = data.get("custom_id", video_id)
    webhook_url = data.get("webhook_url")
    work_dir = f"/vol/{video_id}"

    volume.reload()

    if not os.path.exists(work_dir):
        return {
            "status": "warning",
            "message": f"Durdurulacak aktif bir '{video_id}' işlemi bulunamadı.",
            "video_id": video_id
        }

    flag_path = f"{work_dir}/cancel.flag"
    with open(flag_path, "w", encoding="utf-8") as f:
        f.write("CANCELLED_BY_API")

    volume.commit()

    print(f"[{video_id}] /cancel_request tetiklendi. Durdurma bayrağı (/vol/{video_id}/cancel.flag) yazıldı.")

    if webhook_url:
        send_webhook_sync(webhook_url, {
            "status": "cancelled",
            "step": "cancelled",
            "progress": 0,
            "video_id": video_id,
            "custom_id": custom_id,
            "message": "İşlem API (/cancel_request) üzerinden kullanıcı tarafından durduruldu."
        })

    return {
        "status": "success",
        "message": f"'{video_id}' işlemini durdurma sinyali başarıyla gönderildi.",
        "video_id": video_id,
        "custom_id": custom_id
    }
