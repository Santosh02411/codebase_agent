DEFAULT = 30


def calculate_eta(distance_km, speed_kmh=None):
    speed = speed_kmh or DEFAULT
    return round(distance_km / speed * 60)

def extra(a):
    return a +
