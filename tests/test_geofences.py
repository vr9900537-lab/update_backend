import pytest
from pydantic import ValidationError

from app.services.location_service import haversine_meters
from app.schemas.geofences import GeofenceCreate
from app.utils.geo import polygon_relation


def test_haversine_distance_is_zero_for_same_coordinate() -> None:
    assert haversine_meters(17.385, 78.4867, 17.385, 78.4867) == pytest.approx(0)


def test_haversine_distance_calculates_known_distance() -> None:
    # Approximately 111.2 km between adjacent latitude degrees at the equator.
    assert haversine_meters(0, 0, 1, 0) == pytest.approx(111_195, rel=0.002)


def test_polygon_geofence_validates_closed_polygon() -> None:
    geofence = GeofenceCreate(
        name="yard",
        shape_type="polygon",
        polygon_coordinates=[(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)],
    )

    assert geofence.shape_type == "polygon"


def test_polygon_geofence_rejects_self_intersection() -> None:
    with pytest.raises(ValidationError):
        GeofenceCreate(
            name="invalid",
            shape_type="polygon",
            polygon_coordinates=[(0, 0), (1, 1), (0, 1), (1, 0), (0, 0)],
        )


def test_polygon_relation_returns_inside_and_meters_to_boundary() -> None:
    inside, distance = polygon_relation(
        0.5, 0.5, [(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)]
    )

    assert inside
    assert 50_000 < distance < 60_000
