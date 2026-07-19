from __future__ import annotations

from pathlib import Path

from aviationdb.download import extract_faa_cifp_products, extract_swim_aip_services
from aviationdb.parsers.chile import parse_chile_pdf_documents
from aviationdb.parsers.denmark import parse_denmark_text_documents
from aviationdb.parsers.france import parse_france_text_documents
from aviationdb.parsers.hongkong import parse_hongkong_eaip_documents
from aviationdb.parsers.india import parse_india_eaip_documents
from aviationdb.parsers.korea import parse_korea_eaip_documents
from aviationdb.parsers.malaysia import parse_malaysia_text_documents
from aviationdb.parsers.romania import parse_romania_text_documents
from aviationdb.parsers.singapore import parse_singapore_eaip_documents
from aviationdb.parsers.spain import parse_spain_documents
from aviationdb.parsers.taiwan import parse_taiwan_eaip_documents


def test_extract_faa_cifp_products() -> None:
    html = """
    <table>
      <tbody>
        <tr>
          <td><a href="https://aeronav.faa.gov/Upload_313-d/cifp/CIFP_260709.zip">CIFP 260709</a></td>
          <td> Jul 09, 2026 </td>
          <td> Aug 06, 2026 </td>
        </tr>
        <tr><td>CIFP 260806</td><td> Aug 06, 2026 </td><td> Sep 03, 2026 </td></tr>
      </tbody>
    </table>
    """

    products = extract_faa_cifp_products(
        html,
        "https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/cifp/download/",
    )

    assert len(products) == 1
    assert products[0].cycle == "260709"
    assert products[0].url == "https://aeronav.faa.gov/Upload_313-d/cifp/CIFP_260709.zip"
    assert products[0].effective_date == "Jul 09, 2026"
    assert products[0].ending_date == "Aug 06, 2026"


def test_extract_swim_aip_services() -> None:
    payload = {
        "statusCode": 0,
        "datas": [
            {
                "serviceId": "S2004",
                "serviceName": "AIP閲覧サービス",
                "serviceCategoryCode": 2,
                "lifecycleName": "製品",
                "workingStatusName": "運用中",
                "lastUpdate": "2026/06/30 10:13:57.869",
            },
            {
                "serviceId": "S1001",
                "serviceName": "フライトプラン登録サービス",
                "serviceCategoryCode": 7,
            },
        ],
    }

    services = extract_swim_aip_services(payload)

    assert services == [
        {
            "serviceId": "S2004",
            "serviceName": "AIP閲覧サービス",
            "serviceCategoryCode": 2,
            "lifecycleName": "製品",
            "workingStatusName": "運用中",
            "lastUpdate": "2026/06/30 10:13:57.869",
        }
    ]


def test_parse_taiwan_official_enr44_points() -> None:
    html = """
    <table>
      <thead>
        <tr>
          <th>重要點 Name-code Designator</th>
          <th>坐標 Coordinates</th>
          <th>航路 ATS Route or other route</th>
          <th>備註 Remarks</th>
        </tr>
      </thead>
      <tbody>
        <tr><td>1</td><td>2</td><td>3</td><td>4</td></tr>
        <tr><td>ABSOL</td><td>224837N 1201729E</td><td>Q14</td><td></td></tr>
      </tbody>
    </table>
    """

    dataset = parse_taiwan_eaip_documents({"enr_4_4": html}, "taiwan")

    assert len(dataset.points) == 1
    assert dataset.points[0].ident == "ABSOL"
    assert dataset.points[0].point_type == "SIGNIFICANT_POINT"
    assert dataset.points[0].country == "TW"
    assert not dataset.issues


def test_parse_taiwan_official_route_segments() -> None:
    html = """
    <table><tr><td>▲</td><td>BULAN (FIR BDRY)</td></tr><tr><td></td><td>270530N 1240000E</td></tr></table>
    <table><tr><td></td><td>236°</td><td></td></tr><tr><td></td><td>055°</td><td></td></tr></table>
    <table><tr><td>△</td><td>AIPOM</td></tr><tr><td></td><td>263923N 1232528E</td></tr></table>
    <table><tr><td>▲</td><td>ANBU VOR/DME 'APU'</td></tr><tr><td></td><td>251037N 1213120E</td></tr></table>
    """

    dataset = parse_taiwan_eaip_documents({"route_A1": html}, "taiwan")

    assert [point.ident for point in dataset.points] == ["BULAN", "AIPOM", "APU"]
    assert dataset.points[-1].point_type == "NAVAID"
    assert len(dataset.airways) == 1
    assert dataset.airways[0].designator == "A1"
    assert len(dataset.segments) == 2
    assert not dataset.issues


def test_parse_taiwan_direct_routes_and_holding_points() -> None:
    direct_html = """
    <table>
      <tr><th>Route Designator Name of Significant Points Coordinates</th><th>Great circle DIST NM</th></tr>
      <tr><td>DIRECT ROUTE (for ISHIGAKI)</td></tr>
      <tr><td>△BRENT* 250106N 1231058E</td><td>IGE R-307/69D</td></tr>
      <tr><td></td><td></td><td>31 NM</td></tr>
      <tr><td>△NATAC* 244429.68N 1233917.49E</td><td>IGE R-307/38D</td></tr>
    </table>
    """
    holding_html = """
    <table>
      <tr><th>HLDG ID/FIX/WPT Coordinates</th><th>INBD TR</th></tr>
      <tr><td>1</td><td>2</td></tr>
      <tr><td>ABSOL 224837N 1201729E</td><td>351</td></tr>
    </table>
    """

    dataset = parse_taiwan_eaip_documents({"enr_3_4": direct_html, "enr_3_5": holding_html}, "taiwan")

    assert [point.ident for point in dataset.points] == ["BRENT", "NATAC", "ABSOL"]
    assert dataset.points[-1].point_type == "HOLDING_FIX"
    assert len(dataset.airways) == 1
    assert dataset.airways[0].designator == "DIRECT_ROUTE_FOR_ISHIGAKI"
    assert len(dataset.segments) == 1
    assert not dataset.issues


def test_parse_hongkong_enr44_and_route_segments() -> None:
    enr44_html = """
    <table>
      <tr><th>Name-code designator</th><th>Co-ordinates</th><th>ATS Route / PBN Route / TTR</th></tr>
      <tr><td>1</td><td>2</td><td>3</td></tr>
      <tr class="Table-row-type-3 hspace">
        <td>IKELA</td><td>183942.00N 1121442.00E</td><td>A1</td>
      </tr>
      <tr class="Table-row-type-3 hspace"><td>IDOSI</td><td>190000.00N 1123000.00E</td><td>A1</td></tr>
    </table>
    """
    enr31_html = """
    <table>
      <tr class="Table-row-type-1"><td>A1</td><td>Route availability:</td></tr>
      <tr class="Table-row-type-2">
        <td>▲</td><td>IKELA(Hong Kong/Sanya FIR BDRY)</td>
        <td>183942.00N 1121442.00E</td><td></td>
      </tr>
      <tr class="Table-row-type-3"><td></td><td></td><td>24.9</td><td></td></tr>
      <tr class="Table-row-type-2"><td>∆</td><td>IDOSI</td><td>190000.00N 1123000.00E</td><td></td></tr>
    </table>
    """

    dataset = parse_hongkong_eaip_documents({"enr_4_4": enr44_html, "enr_3_1": enr31_html}, "hongkong")

    assert [point.ident for point in dataset.points] == ["IKELA", "IDOSI"]
    assert dataset.points[0].country == "HK"
    assert len(dataset.airways) == 1
    assert dataset.airways[0].designator == "A1"
    assert len(dataset.segments) == 1
    assert dataset.segments[0].distance_nm == 24.9
    assert not dataset.issues


def test_parse_korea_enr44_and_route_segments() -> None:
    enr44_html = """
    <table>
      <tr><th>Name-code designator</th><th>Co-ordinates</th><th>ATS route or other route</th></tr>
      <tr><td>1</td><td>2</td><td>3</td></tr>
      <tr><td>POLEG</td><td>371249N1265935E</td><td>A582</td></tr>
    </table>
    """
    enr31_html = """
    <table>
      <tr class="Table-row-type-1"><td>A582</td><td>Route availability:</td></tr>
      <tr class="Table-row-type-2">
        <td>∆</td><td>ANYANG VORTAC (SEL)</td><td>372449N 1265542E</td><td></td>
      </tr>
      <tr class="Table-row-type-3"><td></td><td></td><td>12.4</td><td></td></tr>
      <tr class="Table-row-type-2"><td>∆</td><td>POLEG</td><td>371249N 1265935E</td><td></td></tr>
    </table>
    """

    dataset = parse_korea_eaip_documents({"enr_4_4": enr44_html, "enr_3_1": enr31_html}, "korea")

    assert [point.ident for point in dataset.points] == ["POLEG", "SEL"]
    assert dataset.points[1].point_type == "NAVAID"
    assert dataset.airways[0].designator == "A582"
    assert len(dataset.segments) == 1
    assert dataset.segments[0].distance_nm == 12.4
    assert not dataset.issues


def test_parse_singapore_enr44_and_route_segments() -> None:
    enr44_html = """
    <table>
      <tr><th>Name-code<br/>designator</th><th>Coordinates</th><th>ATS route or other route</th></tr>
      <tr><td>1</td><td>2</td><td>3</td></tr>
      <tr><td>OMKOM</td><td>013112N<br/>1035910E</td><td>W651</td></tr>
    </table>
    """
    enr31_html = """
    <table>
      <tr><th>Route Designator<br/>{RNP Type}</th><th>[Route Usage Notes]</th></tr>
      <tr><td></td><td>Significant Point Name</td><td>Significant Point Coordinates</td></tr>
      <tr><td>1</td><td>2</td><td>3</td></tr>
      <tr><td>W651</td><td>Route availability:</td></tr>
      <tr><td>▲</td><td>JOHOR BAHRU DVOR/DME (VJB)</td><td>013950N 1033939E</td></tr>
      <tr><td></td><td>114° 294°</td><td>21.3NM</td></tr>
      <tr><td>▲</td><td>OMKOM</td><td>013112N 1035910E</td></tr>
    </table>
    """

    dataset = parse_singapore_eaip_documents({"enr_4_4": enr44_html, "enr_3_1": enr31_html}, "singapore")

    assert [point.ident for point in dataset.points] == ["OMKOM", "VJB"]
    assert dataset.points[1].point_type == "NAVAID"
    assert dataset.airways[0].designator == "W651"
    assert len(dataset.segments) == 1
    assert dataset.segments[0].distance_nm == 21.3
    assert not dataset.issues


def test_parse_malaysia_enr43_and_route_segments() -> None:
    enr43_text = """
    ENR 4.3 NAME-CODE DESIGNATORS FOR SIGNIFICANT POINTS
    AGOSA 03 08 41N
    101 13 09E
    A457, R467
    ENKOL 02 22 22N
    102 18 16E
    A457
    """
    enr31_text = """
    ENR 3.1 LOWER AND UPPER ATS ROUTES
    A457
    AGOSA
    030841N 1011309E 309°
    40 NM
    ENKOL
    022222N 1021816E
    """

    dataset = parse_malaysia_text_documents(
        {"enr_4_3": enr43_text, "enr_3_1": enr31_text},
        "malaysia",
    )

    assert [point.ident for point in dataset.points] == ["AGOSA", "ENKOL"]
    assert dataset.airways[0].designator == "A457"
    assert len(dataset.segments) == 1
    assert dataset.segments[0].distance_nm == 40
    assert not dataset.issues


def test_parse_france_enr44_and_rnav_route_segments() -> None:
    enr44_text = """
    Observations RemarksRoutes ATS ATS routesCoordonnées CoordinatesName-codes designator |
    45°35'26.0"N 005°21'01.0"ERUBLO |
    45°43'33.9"N 005°13'53.5"EGIRED |
    """
    enr32_text = """
    Designation | A2 |
    45°29'20.3"N 005°26'20.6"ELA TOUR DU PIN-Lyon Est DME | ( LTP )▲ |
    MARSEILLE⇓4700FL 065FL 5007.2326RNAV 5 |
    45°35'26.0"N 005°21'01.0"ERUBLO▲ |
    MARSEILLE⇓4200FL 065FL 5009.5326RNAV 5 |
    45°43'33.9"N 005°13'53.5"EGIRED∆ |
    """

    dataset = parse_france_text_documents({"enr_4_4": enr44_text, "enr_3_2": enr32_text}, "france")

    assert [point.ident for point in dataset.points] == ["RUBLO", "GIRED", "LTP"]
    assert dataset.points[-1].point_type == "NAVAID"
    assert dataset.points[0].region_code == "europe"
    assert dataset.airways[0].designator == "A2"
    assert dataset.airways[0].route_type == "RNAV 5"
    assert len(dataset.segments) == 2
    assert dataset.segments[0].distance_nm == 7.2
    assert dataset.segments[1].distance_nm == 9.5
    assert not dataset.issues


def test_parse_denmark_pdf_text_points_navaids_and_route_segments() -> None:
    enr44_text = """
    ENR 4.4 Name-Code Designators for Significant Points
    ASKEK 554726N 0035934E KY610, KY615
    ADIKU 552050N 0041759E KY610
    """
    enr41_text = """
    BELLA
    DME
    BEL 114.65 MHZ
    CH 93Y
    H24 554728N
    0120545E
    """
    enr32_text = """
    KY610
    (RNAV 1)
    ASKEK
    554726N 0035934E
    BELLA DME
    (BEL)
    554728N 0120545E
    ADIKU
    552050N 0041759E
    NIL
    Extremity KY610
    156°/337°
    28.6
    FL 85
    100°/280°
    12.4
    Total DIST:
    41.0 NM
    """

    dataset = parse_denmark_text_documents(
        {"enr_4_4": enr44_text, "enr_4_1": enr41_text, "enr_3_2": enr32_text},
        "denmark",
    )

    assert [point.ident for point in dataset.points] == ["ASKEK", "ADIKU", "BEL"]
    assert dataset.points[-1].point_type == "NAVAID"
    assert dataset.airways[0].designator == "KY610"
    assert dataset.airways[0].route_type == "RNAV 1"
    assert len(dataset.segments) == 2
    assert dataset.segments[0].distance_nm == 28.6
    assert dataset.segments[1].distance_nm == 12.4
    assert not dataset.issues


def test_parse_romania_pdf_text_points_navaids_and_route_segments() -> None:
    enr44_text = """
    ENR 4.4 NAME-CODE DESIGNATORS FOR SIGNIFICANT POINTS
    CETUL 444151N0283737E L130 NIL
    TURIR 444958N0283922E L130 NIL
    """
    enr41_text = """
    BACĂU
    DVOR/DME
    (7°E/2020)
    BCU 109.400 MHz
    (CH 31X)
    H24 463039N
    0264932E
    """
    enr32_text = """
    L130
    (RNAV 5)
    %CETUL
    444151N0283737E
    TLA
    003°
    8.2
    183°
    +/- 5NM
    +BACĂU DVOR/DME (BCU)
    463039N0264932E
    TLA
    010°
    9.7
    190°
    +/- 5NM
    +TURIR
    444958N0283922E
    """

    dataset = parse_romania_text_documents(
        {"enr_4_4": enr44_text, "enr_4_1": enr41_text, "enr_3_2": enr32_text},
        "romania",
    )

    assert [point.ident for point in dataset.points] == ["CETUL", "TURIR", "BCU"]
    assert dataset.points[-1].point_type == "NAVAID"
    assert dataset.airways[0].designator == "L130"
    assert dataset.airways[0].route_type == "RNAV 5"
    assert len(dataset.segments) == 2
    assert dataset.segments[0].distance_nm == 8.2
    assert dataset.segments[1].distance_nm == 9.7
    assert not dataset.issues


def test_parse_chile_pdf_blocks_points_and_route_segments() -> None:
    raw_dir = Path(__file__).resolve().parent.parent / "data" / "raw" / "chile" / "current"
    documents = {
        "bENR 3 CONVENCIONAL B": (raw_dir / "bENR 3 CONVENCIONAL B.pdf").read_bytes(),
        "zENR 3 RNAV Q": (raw_dir / "zENR 3 RNAV Q.pdf").read_bytes(),
    }

    dataset = parse_chile_pdf_documents(documents, "chile")

    designators = {airway.designator for airway in dataset.airways}
    assert {"B432", "B556", "Q802"}.issubset(designators)
    assert any(point.ident == "MUNER" for point in dataset.points)
    assert any(point.ident == "SIRAM" for point in dataset.points)
    assert len(dataset.segments) >= 20
    assert not [issue for issue in dataset.issues if issue.severity == "error"]


def test_parse_spain_csv_points_navaids_and_route_segments() -> None:
    enr44_csv = (
        "ACCION;Identificador_Identifier;Tipo_Type;Latitud_Latitude;Longitud_Longitude;GFID\n"
        "NOCHANGE;NEPAL;ICAO;404134N;0015529E;pt1\n"
        "NOCHANGE;ESPOR;ICAO;401659N;0020544E;pt2\n"
    )
    enr41_csv = (
        "ACCION;Nombre_Name;Radioayuda_Navaid;Identificador_Identifier;Frecuencia_Frequency;Canal_Channel;"
        "Latitud_Latitude;Longitud_Longitude;GFID\n"
        "NOCHANGE;VILLANUEVA;NDB;VNV;305.00;;411238N;0014221E;nav1\n"
    )
    enr32_csv = (
        "ACCION;DESIGNATOR_TXT;ORDEN;PUNTO_INICIO;COOR_LAT_INICIO;COOR_LON_INICIO;"
        "PUNTO_FINAL;COOR_LAT_FINAL;COOR_LON_FINAL;PBNACCURACY_VAL;MAGTRACK_VAL;"
        "REVERSEMAGTRACK_VAL;LENGTH_VAL;DISTVERTUPPER_VAL;DISTVERTUPPER_UOM;"
        "DISTVERTLOWER_VAL;DISTVERTLOWER_UOM;DIRECTION_CODE_IMPAR_ODD;DIRECTION_CODE_PAR_EVEN\n"
        "NOCHANGE;L2;1000;VILLANUEVA NDB (VNV);411238N;0014221E;"
        "NEPAL;404134N;0015529E;RNAV5;;340;32.6;305;FL;95;FL;;B\n"
        "NOCHANGE;L2;2000;NEPAL;404134N;0015529E;"
        "ESPOR;401659N;0020544E;RNAV5;;340;25.8;305;FL;95;FL;;B\n"
    )

    dataset = parse_spain_documents(
        {
            "enr_4_4_csv": enr44_csv.encode(),
            "enr_4_1_csv": enr41_csv.encode(),
            "enr_3_2_csv": enr32_csv.encode(),
        },
        "spain",
    )

    assert [point.ident for point in dataset.points] == ["NEPAL", "ESPOR", "VNV"]
    assert dataset.points[-1].point_type == "NAVAID"
    assert dataset.airways[0].designator == "L2"
    assert dataset.airways[0].route_type == "RNAV5"
    assert len(dataset.segments) == 2
    assert dataset.segments[0].distance_nm == 32.6
    assert dataset.segments[0].maximum_altitude_ft == 30500
    assert dataset.segments[0].minimum_altitude_ft == 9500
    assert dataset.segments[0].direction == "even"
    assert not dataset.issues


def test_parse_india_enr44_and_route_segments() -> None:
    enr44_html = """
    <table>
      <tr><th>Waypoints</th><th>Coordinates</th><th>Number of routes</th></tr>
      <tr><td>ABVUL</td><td>273854N 0715353E</td><td>Z8, Z9</td></tr>
      <tr><td>OMDEV</td><td>160557N 0730501E</td><td>T9</td></tr>
    </table>
    """
    route_html = """
    <table>
      <tr><th>Route Designator (RNP Type) Name of Significant Points Coordinates</th><th>Remarks</th></tr>
      <tr><td></td><td>T9 [RNP2] (GUNDI - BOBEX)</td></tr>
      <tr><td>p</td><td>GUNDI 172137N 0712936E</td></tr>
      <tr><td></td><td></td><td>130/311 118.6 NM</td></tr>
      <tr><td>p</td><td>GOA DVOR DVOR/DME (GGO) 152241N 0734837E</td></tr>
      <tr><td></td><td></td><td>113/294 38.1 NM</td></tr>
      <tr><td>p</td><td>OMDEV 160557N 0730501E</td></tr>
    </table>
    """

    dataset = parse_india_eaip_documents({"enr_4_4": enr44_html, "route_T9": route_html}, "india")

    assert [point.ident for point in dataset.points] == ["ABVUL", "OMDEV", "GUNDI", "GGO"]
    assert dataset.points[-1].point_type == "NAVAID"
    assert dataset.airways[0].designator == "T9"
    assert dataset.airways[0].route_type == "RNP2"
    assert len(dataset.segments) == 2
    assert dataset.segments[0].distance_nm == 118.6
    assert dataset.segments[1].distance_nm == 38.1
    assert not dataset.issues
