"""IP -> country from the DB-IP "IP to Country Lite" CSV (CC BY 4.0, https://db-ip.com).

Offline lookup only: the file is downloaded once by scripts/get-geoip.sh into data/geoip/.
Set GEOIP_CSV to point at another file (plain .csv or .csv.gz).
"""
import bisect
import csv
import gzip
import ipaddress
import os
import sys
from pathlib import Path

GEOIP_DIR = Path(__file__).resolve().parent.parent / "data" / "geoip"
ENV_VAR = "GEOIP_CSV"

_cache = {}
_warned = set()


def default_path():
    """GEOIP_CSV if set, else the newest dbip-country-lite-*.csv.gz in data/geoip/, else None."""
    if os.environ.get(ENV_VAR):
        return Path(os.environ[ENV_VAR])
    files = sorted(GEOIP_DIR.glob("dbip-country-lite-*.csv*"))
    return files[-1] if files else None


def _warn(key, message):
    if key not in _warned:
        _warned.add(key)
        print(f"geo: {message}", file=sys.stderr, flush=True)


def _open(path):
    return gzip.open(path, "rt", encoding="utf-8", newline="") if path.suffix == ".gz" else \
        open(path, encoding="utf-8", newline="")


def load(path):
    """{4: (starts, ends, countries), 6: (...)} sorted by range start. None if the file can't be read."""
    path = Path(path)
    if path in _cache:
        return _cache[path]
    rows = {4: [], 6: []}
    try:
        with _open(path) as fh:
            for row in csv.reader(fh):
                if len(row) < 3:
                    continue
                try:
                    start, end = ipaddress.ip_address(row[0].strip()), ipaddress.ip_address(row[1].strip())
                except ValueError:
                    continue
                if start.version != end.version:
                    continue
                rows[start.version].append((int(start), int(end), row[2].strip().upper()))
    except (OSError, EOFError, UnicodeDecodeError, csv.Error) as exc:
        _warn(path, f"can't read {path} ({exc.__class__.__name__}); hosting country is skipped")
        _cache[path] = None
        return None
    table = {}
    for version, items in rows.items():
        items.sort()
        table[version] = ([s for s, _, _ in items], [e for _, e, _ in items], [c for _, _, c in items])
    _cache[path] = table
    return table


def country_of(ip, path=None):
    """Two-letter country code for a public IP, e.g. "DE". None if private, invalid or unknown."""
    try:
        addr = ipaddress.ip_address(str(ip or "").strip().strip("[]"))
    except ValueError:
        return None
    if getattr(addr, "ipv4_mapped", None):
        addr = addr.ipv4_mapped
    if not addr.is_global or addr.is_multicast:
        return None
    path = Path(path) if path else default_path()
    if path is None or not path.exists():
        _warn("missing", "no IP-to-country file; run scripts/get-geoip.sh to show hosting countries")
        return None
    table = load(path)
    if not table:
        return None
    starts, ends, countries = table[addr.version]
    n = int(addr)
    i = bisect.bisect_right(starts, n) - 1
    if i < 0 or n > ends[i]:
        return None
    code = countries[i]
    return code if len(code) == 2 and code.isalpha() and code != "ZZ" else None
