import math


def haversine_meters(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    earth_radius_meters = 6_371_000
    lat_a, lat_b = math.radians(latitude_a), math.radians(latitude_b)
    delta_lat = math.radians(latitude_b - latitude_a)
    delta_lon = math.radians(longitude_b - longitude_a)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * earth_radius_meters * math.asin(math.sqrt(value))


def polygon_relation(
    latitude: float,
    longitude: float,
    coordinates: list[tuple[float, float]],
) -> tuple[bool, float]:
    """Return inside/outside and distance to polygon boundary in meters."""
    inside = False
    boundary_distance = float("inf")
    meters_per_degree_lat = 110_574.0
    meters_per_degree_lon = 111_320.0 * max(
        0.000001, abs(math.cos(math.radians(latitude)))
    )
    projected = [
        ((lon - longitude) * meters_per_degree_lon, (lat - latitude) * meters_per_degree_lat)
        for lat, lon in coordinates
    ]
    for index in range(len(projected) - 1):
        x1, y1 = projected[index]
        x2, y2 = projected[index + 1]
        denominator = (x2 - x1) ** 2 + (y2 - y1) ** 2
        ratio = 0.0 if denominator == 0 else max(
            0.0, min(1.0, -(x1 * (x2 - x1) + y1 * (y2 - y1)) / denominator)
        )
        boundary_distance = min(
            boundary_distance,
            ((x1 + ratio * (x2 - x1)) ** 2 + (y1 + ratio * (y2 - y1)) ** 2) ** 0.5,
        )

        lat1, lon1 = coordinates[index]
        lat2, lon2 = coordinates[index + 1]
        if (lat1 > latitude) != (lat2 > latitude):
            crossing_lon = (lon2 - lon1) * (latitude - lat1) / (lat2 - lat1) + lon1
            if longitude < crossing_lon:
                inside = not inside
    return inside, boundary_distance


__all__ = ["haversine_meters", "polygon_relation"]
