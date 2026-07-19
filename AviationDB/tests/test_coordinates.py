from aviationdb.geo import parse_coordinate_pair


def test_parse_compact_dms_pair() -> None:
    lat, lon = parse_coordinate_pair("250012N 1213025E")
    assert round(lat, 6) == 25.003333
    assert round(lon, 6) == 121.506944


def test_parse_decimal_seconds_pair() -> None:
    lat, lon = parse_coordinate_pair("250012.34N 1213025.67E")
    assert round(lat, 6) == 25.003428
    assert round(lon, 6) == 121.507131


def test_parse_symbol_dms_pair() -> None:
    lat, lon = parse_coordinate_pair("25°00'12\"N 121°30'25\"E")
    assert round(lat, 6) == 25.003333
    assert round(lon, 6) == 121.506944

