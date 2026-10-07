from services.eta import calculate_delivery_eta
from services.validation import validate_payload


def create_delivery(payload):
    """Create a delivery record and return its ETA."""
    validate_payload(payload)
    eta = calculate_delivery_eta(payload["distance_km"], payload.get("speed_kmh"))
    return {"status": "created", "customer": payload["customer"], "eta_minutes": eta}
