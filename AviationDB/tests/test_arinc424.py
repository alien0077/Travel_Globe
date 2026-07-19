from aviationdb.parsers.arinc424 import parse_faa_cifp


def test_faa_cifp_parser_skips_discontinuous_airway_edges() -> None:
    text = "\n".join(
        [
            _faa_point_line("AAAAA", "N35000000W100000000"),
            _faa_point_line("BBBBB", "N36000000W101000000"),
            _faa_point_line("CCCCC", "N36000000W120000000"),
            _faa_point_line("DDDDD", "N36100000W121000000"),
            _faa_airport_line("KAAA", "AAA", "N35050000W100050000", "ALPHA TEST INTL"),
            _faa_airway_line("J1", 10, "AAAAA"),
            _faa_airway_line("J1", 20, "BBBBB"),
            _faa_airway_line("J1", 30, "CCCCC"),
            _faa_airway_line("J1", 40, "DDDDD"),
        ]
    )

    dataset = parse_faa_cifp(text, "faa")

    assert len(dataset.points) == 4
    assert len(dataset.airports) == 1
    assert dataset.airports[0].icao == "KAAA"
    assert len(dataset.airways) == 1
    assert len(dataset.segments) == 2
    assert [issue.code for issue in dataset.issues] == ["faa-airway-discontinuity"]


def _faa_point_line(ident: str, coordinate: str) -> str:
    chars = [" "] * 132
    chars[0] = "S"
    chars[1:4] = "USA"
    chars[4:6] = "EA"
    chars[13:18] = ident.ljust(5)
    chars[19:21] = "K1"
    chars[50 : 50 + len(coordinate)] = coordinate
    return "".join(chars)


def _faa_airway_line(designator: str, sequence: int, ident: str) -> str:
    chars = [" "] * 132
    chars[0] = "S"
    chars[1:4] = "USA"
    chars[4:6] = "ER"
    chars[13:18] = designator.ljust(5)
    chars[25:29] = f"{sequence:04d}"
    chars[29:34] = ident.ljust(5)
    chars[34:36] = "K1"
    return "".join(chars)


def _faa_airport_line(icao: str, iata: str, coordinate: str, name: str) -> str:
    chars = [" "] * 132
    chars[0] = "S"
    chars[1:4] = "USA"
    chars[4:6] = "P "
    chars[6:10] = icao
    chars[10:13] = "K1A"
    chars[13:16] = iata
    chars[32 : 32 + len(coordinate)] = coordinate
    chars[93 : 93 + len(name)] = name
    return "".join(chars)
