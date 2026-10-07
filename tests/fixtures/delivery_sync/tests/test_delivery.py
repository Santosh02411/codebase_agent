import pytest
from delivery_app import create_delivery


def test_create_delivery_with_speed():
    assert create_delivery({"customer": "A", "distance_km": 30, "speed_kmh": 60})["eta_minutes"] == 30


def test_create_delivery_default_speed():
    # speed is optional: should default to 30 km/h
    assert create_delivery({"customer": "A", "distance_km": 15})["eta_minutes"] == 30


def test_missing_customer():
    with pytest.raises(ValueError):
        create_delivery({"distance_km": 5})
