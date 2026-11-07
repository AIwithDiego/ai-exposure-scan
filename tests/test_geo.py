import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scan import geo  # noqa: E402

SAMPLE = Path(__file__).resolve().parent / "geoip-sample.csv"


def test_public_ip_resolves():
    assert geo.country_of("85.214.132.117", SAMPLE) == "DE"
    assert geo.country_of("8.8.8.8", SAMPLE) == "US"
    assert geo.country_of("2a00:1450:4001:80b::200e", SAMPLE) == "IE"
    assert geo.country_of("[2a00:1450::1]", SAMPLE) == "IE"


def test_env_var_points_at_file(monkeypatch):
    monkeypatch.setenv(geo.ENV_VAR, str(SAMPLE))
    assert geo.country_of("1.1.1.1") == "AU"


def test_private_loopback_and_invalid_are_none():
    for ip in ("127.0.0.1", "::1", "192.168.1.10", "10.0.0.1", "169.254.1.1", "0.0.0.1", "not an ip", "", None):
        assert geo.country_of(ip, SAMPLE) is None


def test_ip_outside_any_range_is_none():
    assert geo.country_of("9.9.9.9", SAMPLE) is None


def test_missing_file_is_none_without_crashing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(geo, "_warned", set())
    assert geo.country_of("8.8.8.8", tmp_path / "nope.csv.gz") is None
    monkeypatch.delenv(geo.ENV_VAR, raising=False)
    monkeypatch.setattr(geo, "GEOIP_DIR", tmp_path)
    assert geo.country_of("8.8.8.8") is None
    assert geo.country_of("8.8.8.8") is None
    assert capsys.readouterr().err.count("geo:") == 1


def test_unreadable_file_is_none(tmp_path):
    bad = tmp_path / "bad.csv.gz"
    bad.write_bytes(b"not gzip")
    assert geo.country_of("8.8.8.8", bad) is None


def test_partial_download_is_not_picked(tmp_path, monkeypatch):
    monkeypatch.delenv(geo.ENV_VAR, raising=False)
    monkeypatch.setattr(geo, "GEOIP_DIR", tmp_path)
    (tmp_path / "dbip-country-lite-2026-10.csv").write_text(SAMPLE.read_text())
    (tmp_path / "dbip-country-lite-2026-11.csv.gz.part").write_bytes(b"half")
    assert geo.default_path().name == "dbip-country-lite-2026-10.csv"
    assert geo.country_of("8.8.8.8") == "US"
