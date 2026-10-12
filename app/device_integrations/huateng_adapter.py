from typing import NoReturn

from app.schemas.tracking import LocationIngest


class HuatengC05Adapter:
    """Placeholder: no packet format is implemented without vendor documentation."""

    def parse(self, message: bytes) -> dict[str, object]:
        raise NotImplementedError(
            "C05 integration is pending verified vendor protocol documentation."
        )

    def _pending(self) -> NoReturn:
        raise NotImplementedError(
            "C05 event parsing is pending verified vendor protocol documentation."
        )

    def parse_location(self, message: dict[str, object]) -> LocationIngest:
        self._pending()

    def parse_heartbeat(self, message: dict[str, object]) -> dict[str, object]:
        self._pending()

    def parse_battery(self, message: dict[str, object]) -> dict[str, object]:
        self._pending()

    def parse_sos(self, message: dict[str, object]) -> dict[str, object]:
        self._pending()

    def parse_tamper(self, message: dict[str, object]) -> dict[str, object]:
        self._pending()

    def parse_acknowledgement(self, message: dict[str, object]) -> dict[str, object]:
        self._pending()
