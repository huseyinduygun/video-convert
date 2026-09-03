import modal
from ..config import app, STAGE_CFG_API
from ..core import image_cpu, verify_request_auth, fetch_modal_workspace_billing


@app.function(image=image_cpu, **STAGE_CFG_API)
@modal.concurrent(max_inputs=100)
@modal.fastapi_endpoint(method="POST")
def billing_request(data: dict = None):
    """
    HTTP POST Endpoint: Modal Workspace faturalandırma ve kalan kredi durumunu döner.
    PHP backend veya Admin Panel üzerinden anlık bakiye sorgulamak için kullanılır.

    Payload:
    {
        "token": "..." (veya X-Admin-Token header)
    }

    Dönüş:
    {
        "status": "success",
        "remaining_credits": 29.9823,
        "credit_unit": "usd",
        "credits": {
            "remaining": 29.9823,
            "total": 30.00,
            "used": 0.0177,
            "percent_remaining": 99.94,
            "unit": "usd"
        },
        "billing": {
            "this_month_spent_usd": 0.0177,
            "monthly_free_credit_usd": 30.00,
            "estimated_remaining_credit_usd": 29.9823,
            "billed_cost_usd": 0.0,
            "breakdown": { ... },
            "adjustments": { ... }
        }
    }
    """
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return {"status": "failed", "error": "Geçersiz JSON verisi."}

    verify_request_auth(data)

    billing_data = fetch_modal_workspace_billing()
    is_success = billing_data.get("available", False)

    return {
        "status": "success" if is_success else "warning",
        **billing_data
    }
