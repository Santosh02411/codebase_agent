DEFAULT_SPEED_KMH = 30


def calculate_delivery_eta(distance_km, speed_kmh):
    """Return estimated minutes for a delivery."""
    return round(distance_km / speed_kmh * 60)
