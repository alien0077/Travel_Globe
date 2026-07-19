from aviationdb.parsers.europe import parse_europe_eaip_documents


def test_europe_parser_builds_route_segments_from_eaip_rows() -> None:
    documents = {
        "enr_4_4": """
        <table>
          <tr><th>Name-code Designator</th><th>Coordinates</th></tr>
          <tr><td>AGNAV</td><td>493404.50N 0123652.21E</td></tr>
          <tr><td>BEKTO</td><td>495756.96N 0124243.36E</td></tr>
        </table>
        """,
        "enr_3_2": """
        <table>
          <tr><td>L132TEN_ROUTE_RTE;TXT_DESIG;1075</td></tr>
          <tr>
            <td></td>
            <td>AGNAVTDESIGNATED_POINT;CODE_ID;4277</td>
            <td>493404.50NTDESIGNATED_POINT;GEO_LAT;42770123652.21ETDESIGNATED_POINT;GEO_LONG;4277</td>
          </tr>
          <tr><td>24.2TRTE_SEG;VAL_LEN;1784 NMTRTE_SEG;UOM_DIST;1784</td></tr>
          <tr>
            <td></td>
            <td>BEKTOTDESIGNATED_POINT;CODE_ID;4294</td>
            <td>495756.96NTDESIGNATED_POINT;GEO_LAT;42940124243.36ETDESIGNATED_POINT;GEO_LONG;4294</td>
          </tr>
        </table>
        """,
    }

    dataset = parse_europe_eaip_documents(documents, "czech")

    assert len(dataset.points) == 2
    assert [airway.designator for airway in dataset.airways] == ["L132"]
    assert len(dataset.segments) == 1
    assert dataset.segments[0].distance_nm == 24.2
    assert dataset.issues == []


def test_row_class_parser_supports_cambodia_region_profile() -> None:
    documents = {
        "enr_4_4": """
        <table>
          <tr><th>Name-code Designator</th><th>Coordinates</th></tr>
          <tr><td>KADLO</td><td>225718N 1183230E</td></tr>
          <tr><td>DADON</td><td>221635N 1180010E</td></tr>
        </table>
        """,
        "enr_3_2": """
        <table>
          <tr><td>L1 RNAVTEN_ROUTE_RTE;TXT_DESIG;1075</td></tr>
          <tr><td>KADLO</td><td>225718NTDESIGNATED_POINT;GEO_LAT;11181183230ETDESIGNATED_POINT;GEO_LONG;1118</td></tr>
          <tr><td>39TRTE_SEG;VAL_LEN;1784 NMTRTE_SEG;UOM_DIST;1784</td></tr>
          <tr><td>DADON</td><td>221635NTDESIGNATED_POINT;GEO_LAT;11181180010ETDESIGNATED_POINT;GEO_LONG;1118</td></tr>
        </table>
        """,
    }

    dataset = parse_europe_eaip_documents(documents, "cambodia")

    assert [point.country for point in dataset.points] == ["KH", "KH"]
    assert [point.region_code for point in dataset.points] == ["asia-southeast", "asia-southeast"]
    assert [airway.fir for airway in dataset.airways] == ["PHNOM PENH"]


def test_row_class_parser_supports_cocesna_region_profile() -> None:
    documents = {
        "enr_4_4": """
        <table>
          <tr><th>Name-code Designator</th><th>Coordinates</th></tr>
          <tr><td>LIB</td><td>164107.36N 0882216.87W</td></tr>
          <tr><td>RODDI</td><td>161818N 0880424W</td></tr>
        </table>
        """,
        "enr_3_1": """
        <table>
          <tr><td>R640TEN_ROUTE_RTE;TXT_DESIG;1075</td></tr>
          <tr><td>LIB</td><td>164107.36NTDESIGNATED_POINT;GEO_LAT;11180882216.87WTDESIGNATED_POINT;GEO_LONG;1118</td></tr>
          <tr><td>24TRTE_SEG;VAL_LEN;1784 NMTRTE_SEG;UOM_DIST;1784</td></tr>
          <tr><td>RODDI</td><td>161818NTDESIGNATED_POINT;GEO_LAT;11180880424WTDESIGNATED_POINT;GEO_LONG;1118</td></tr>
        </table>
        """,
    }

    dataset = parse_europe_eaip_documents(documents, "cocesna")

    assert [point.country for point in dataset.points] == ["CS", "CS"]
    assert [point.region_code for point in dataset.points] == ["central-america", "central-america"]
    assert [airway.fir for airway in dataset.airways] == ["CENTRAL AMERICA"]


def test_row_class_parser_supports_sri_lanka_region_profile() -> None:
    documents = {
        "enr_4_4": """
        <table>
          <tr><th>Name-code Designator</th><th>Coordinates</th></tr>
          <tr><td>POMAL</td><td>063150N 0812100E</td></tr>
          <tr><td>BIDAN</td><td>061000N 0820000E</td></tr>
        </table>
        """,
        "enr_3_2": """
        <table>
          <tr><td>L645TEN_ROUTE_RTE;TXT_DESIG;1075</td></tr>
          <tr><td>POMAL</td><td>063150NTDESIGNATED_POINT;GEO_LAT;11180812100ETDESIGNATED_POINT;GEO_LONG;1118</td></tr>
          <tr><td>42TRTE_SEG;VAL_LEN;1784 NMTRTE_SEG;UOM_DIST;1784</td></tr>
          <tr><td>BIDAN</td><td>061000NTDESIGNATED_POINT;GEO_LAT;11180820000ETDESIGNATED_POINT;GEO_LONG;1118</td></tr>
        </table>
        """,
    }

    dataset = parse_europe_eaip_documents(documents, "sri_lanka")

    assert [point.country for point in dataset.points] == ["LK", "LK"]
    assert [point.region_code for point in dataset.points] == ["south-asia", "south-asia"]
    assert [airway.fir for airway in dataset.airways] == ["COLOMBO"]


def test_row_class_parser_supports_asecna_dms_coordinates() -> None:
    documents = {
        "enr_4_4": """
        <table>
          <tr><th>Indicatif code</th><th>Coordonnees</th></tr>
          <tr><td>EGADU</td><td>04°51'38"N 003°00'00"W</td></tr>
          <tr><td>GAPAK</td><td>00°56'26"N 005°30'32"E</td></tr>
        </table>
        """,
        "enr_3_1": """
        <table>
          <tr><td>A400</td><td>Disponibilite</td></tr>
          <tr><td>EGADU</td><td>04°51'38"N 003°00'00"W</td></tr>
          <tr><td>GAPAK</td><td>00°56'26"N 005°30'32"E</td></tr>
        </table>
        """,
    }

    dataset = parse_europe_eaip_documents(documents, "asecna")

    assert [point.country for point in dataset.points] == ["ASECNA", "ASECNA"]
    assert [point.region_code for point in dataset.points] == ["africa", "africa"]
    assert [airway.fir for airway in dataset.airways] == ["ASECNA"]
    assert len(dataset.segments) == 1


def test_row_class_parser_supports_saudi_double_apostrophe_dms_coordinates() -> None:
    documents = {
        "enr_4_4": """
        <table>
          <tr><th>Name-code Designator</th><th>Coordinates</th><th>ATS Route</th></tr>
          <tr><td>ABKAR</td><td>19°05'11''N 040°16'12''E</td><td>L677</td></tr>
          <tr><td>AKODI</td><td>27°50'12''N 046°13'20''E</td><td>Y518</td></tr>
        </table>
        """,
    }

    dataset = parse_europe_eaip_documents(documents, "saudiarabia")

    assert [point.ident for point in dataset.points] == ["ABKAR", "AKODI"]
    assert [point.country for point in dataset.points] == ["SA", "SA"]
    assert [point.region_code for point in dataset.points] == ["middle-east", "middle-east"]


def test_europe_parser_does_not_treat_flight_levels_as_route_designators() -> None:
    documents = {
        "enr_3_3": """
        <table>
          <tr class="Table-row-type-1"><td>L18</td><td>(RNAV 5)</td></tr>
          <tr class="Table-row-type-2"><td>∆</td><td>SUROX</td><td>535948N 0065936W</td></tr>
          <tr><td>FL245</td></tr>
          <tr><td>FL075</td></tr>
          <tr class="Table-row-type-3"><td></td><td></td><td>38.6 NM</td></tr>
          <tr class="Table-row-type-2"><td>▲</td><td>DUBLIN DVOR/DME (DUB)</td><td>532957.8N 0061825.6W</td></tr>
        </table>
        """,
    }

    dataset = parse_europe_eaip_documents(documents, "ireland")

    assert [airway.designator for airway in dataset.airways] == ["L18"]
    assert len(dataset.segments) == 1
    assert dataset.segments[0].distance_nm == 38.6
    assert dataset.issues == []
