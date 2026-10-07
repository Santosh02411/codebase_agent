REQUIRED_FIELDS = ("customer", "distance_km")


def validate_payload(payload):
    """Raise ValueError when a delivery payload is missing required fields."""
    for field in REQUIRED_FIELDS:
        if field not in payload:
            raise ValueError(f"missing field: {field}")
