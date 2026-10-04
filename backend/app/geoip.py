import ipaddress
import logging
import threading

import geoip2.database
import geoip2.errors

from app.models import UNKNOWN_COUNTRY

logger = logging.getLogger(__name__)


class CountryResolver:
    def __init__(self, db_path: str | None) -> None:
        self._db_path = db_path
        self._reader: geoip2.database.Reader | None = None
        self._lock = threading.Lock()

    def _ensure_reader(self) -> geoip2.database.Reader | None:
        if self._db_path is None:
            return None
        if self._reader is None:
            with self._lock:
                if self._reader is None:  # re-check: another thread may have won the race
                    try:
                        self._reader = geoip2.database.Reader(self._db_path)
                    except OSError:
                        logger.warning(
                            "geoip database not found at %s; country will read as %s",
                            self._db_path,
                            UNKNOWN_COUNTRY,
                        )
                        return None
        return self._reader

    def resolve(self, ip: str) -> str:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return UNKNOWN_COUNTRY

        if addr.is_private or addr.is_loopback:
            return UNKNOWN_COUNTRY

        reader = self._ensure_reader()
        if reader is None:
            return UNKNOWN_COUNTRY

        try:
            result = reader.country(ip)
        except geoip2.errors.AddressNotFoundError:
            return UNKNOWN_COUNTRY

        return result.country.iso_code or UNKNOWN_COUNTRY

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
