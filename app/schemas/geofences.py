from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]
PolygonPoint = tuple[Latitude, Longitude]


def _orientation(a: PolygonPoint, b: PolygonPoint, c: PolygonPoint) -> float:
    return (b[1] - a[1]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[1] - a[1])


def _segments_intersect(
    a: PolygonPoint, b: PolygonPoint, c: PolygonPoint, d: PolygonPoint
) -> bool:
    o1, o2 = _orientation(a, b, c), _orientation(a, b, d)
    o3, o4 = _orientation(c, d, a), _orientation(c, d, b)
    epsilon = 1e-12

    def on_segment(start: PolygonPoint, point: PolygonPoint, end: PolygonPoint) -> bool:
        return (
            min(start[0], end[0]) - epsilon <= point[0] <= max(start[0], end[0]) + epsilon
            and min(start[1], end[1]) - epsilon <= point[1] <= max(start[1], end[1]) + epsilon
        )

    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    return (
        (abs(o1) <= epsilon and on_segment(a, c, b))
        or (abs(o2) <= epsilon and on_segment(a, d, b))
        or (abs(o3) <= epsilon and on_segment(c, a, d))
        or (abs(o4) <= epsilon and on_segment(c, b, d))
    )


def validate_polygon(points: list[PolygonPoint]) -> None:
    if len(points) < 4 or points[0] != points[-1]:
        raise ValueError("polygon_coordinates must have at least 3 vertices and be closed")
    if any(points[index] == points[index + 1] for index in range(len(points) - 1)):
        raise ValueError("Polygon edges cannot have zero length")
    if any(abs(points[i][1] - points[i + 1][1]) > 180 for i in range(len(points) - 1)):
        raise ValueError("Polygons crossing the antimeridian are not supported")

    area_twice = sum(
        points[i][1] * points[i + 1][0] - points[i + 1][1] * points[i][0]
        for i in range(len(points) - 1)
    )
    if abs(area_twice) < 1e-12:
        raise ValueError("Polygon area must be greater than zero")

    edge_count = len(points) - 1
    for first in range(edge_count):
        for second in range(first + 1, edge_count):
            if second in {first, first + 1} or (first == 0 and second == edge_count - 1):
                continue
            if _segments_intersect(
                points[first], points[first + 1], points[second], points[second + 1]
            ):
                raise ValueError("Polygon edges must not intersect")


class GeofenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    shape_type: Literal["circle", "polygon"] = "circle"
    center_latitude: Latitude | None = None
    center_longitude: Longitude | None = None
    radius_meters: float | None = Field(default=None, gt=0, le=100_000)
    polygon_coordinates: list[PolygonPoint] | None = Field(default=None, min_length=4, max_length=100)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_shape(self) -> "GeofenceCreate":
        if self.shape_type == "circle":
            if self.center_latitude is None or self.center_longitude is None or self.radius_meters is None:
                raise ValueError("Circle geofences require center coordinates and radius_meters")
            if self.polygon_coordinates is not None:
                raise ValueError("Circle geofences cannot include polygon_coordinates")
        else:
            if self.polygon_coordinates is None:
                raise ValueError("Polygon geofences require polygon_coordinates")
            if any(value is not None for value in (self.center_latitude, self.center_longitude, self.radius_meters)):
                raise ValueError("Polygon geofences cannot include circle fields")
            validate_polygon(self.polygon_coordinates)
        return self


class GeofencePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    shape_type: Literal["circle", "polygon"] | None = None
    center_latitude: Latitude | None = None
    center_longitude: Longitude | None = None
    radius_meters: float | None = Field(default=None, gt=0, le=100_000)
    polygon_coordinates: list[PolygonPoint] | None = Field(default=None, min_length=4, max_length=100)
    enabled: bool | None = None


class GeofenceRecord(GeofenceCreate):
    geofence_id: str
    tenant_id: str
    created_by: str
    created_at: datetime
    updated_at: datetime
