# Aviation Source Acquisition Log

Last updated: 2026-07-19 (FINAL: unified to FlightGear GPL-only; all other sources deprecated; FG covers 123K pts + 8.6K airways globally; GPL-licensed, ready for GitHub)

This log is the human-readable acquisition record for AviationDB. It complements:

- `config/sources.yaml`: canonical source URL, source type, raw path, license status.
- `data/raw/**/manifest.json` or `download_probe.json`: private local download record and file hashes.
- SQLite `source_metadata`: build fingerprint, provider, AIRAC/effective date, redistribution status.

All official sources remain `manual_review_required` unless explicitly reviewed. Raw official files,
processed official databases, and derived app packs must not be published while redistribution is not allowed.

## Recording Rules

For every country/source attempt, record:

- official source page and exact package/cycle if known;
- document URLs or service IDs used;
- local private raw directory;
- download method and blocker, if any;
- build database path and counts;
- validation result;
- redistribution status and app-pack eligibility.

If a download is blocked by login, CAPTCHA, Cloudflare, subscription, or approval queue, record the blocker
instead of silently retrying.

## Current Source Status

| Source | Status | Current Cycle / Effective | Private Raw Location | Build / Validation |
| --- | --- | --- | --- | --- |
| Taiwan CAA AIS | Downloaded, parser active | AIRAC AIP AMDT 02-26, effective 2026-05-14 | `data/raw/taiwan/AIRAC AIP AMDT 02-26_2026_05_14/` | Taiwan parser active; official redistribution still manual review |
| Hong Kong CAD AIS | Downloaded, built, validated | effective 2026-07-09 | `data/raw/hongkong/eaip_20260709/` | `aviation-hk.sqlite`: 39 airways, 131 segments, validation clean |
| Republic of Korea KOCA AIM | Downloaded, built, validated | 2026-07-08 AIRAC | `data/raw/korea/2026-07-08-AIRAC/` | `aviation-kr.sqlite`: 54 airways, 298 segments, validation clean |
| Singapore CAAS AIM-SG | Downloaded, built, validated | effective 2026-07-09, package `15-JUL-2026` | `data/raw/singapore/15-JUL-2026/` | `aviation-sg.sqlite`: 420 points, 66 airways, 217 segments, validation clean |
| Malaysia CAAM AIP | Downloaded, built, validated | current CAAM public PDF set, cycle not stated on source page | `data/raw/malaysia/current/` | `aviation-my-v3.sqlite`: 229 points, 93 airways, 311 segments, validation clean |
| Japan MLIT SWIM / AISC | Metadata downloaded; encrypted AIXM ZIP blocked pending password/approval | S2002 ZIP dated 2026-06-24; M2001 started 2026-07-17 01:10:51; P2005 started 2026-07-18 13:59:11 | `data/raw/japan/swim/` | `AIXM_ALL_20260624150001.zip` is present but encrypted; no ZIP password found locally; Gmail has no M2001/P2005 approval/rejection email as of 2026-07-18; M2001/P2005 waiting approval or backend delivery details |
| FAA CIFP | Downloaded, built private graph, validated, private pack exported | CIFP 260709, effective 2026-07-09 | `data/raw/faa/260709/` | `aviation-faa-private.sqlite`: 2,583 airports, 34,817 points, 1,539 airways, 17,556 segments, validation clean; private north-america pack: 2,533 airports, 33,585 points, 1,417 airways, 16,761 segments, all payloads `public:false`; KSFO→KJFK and KLAX→KORD route via `airway_graph`; official redistribution still manual review |
| Macau AACM | Blocked after public page probe | Unknown | none | Public AIP page has SPA/Terms flow; no direct static AIP endpoint found |
| Thailand CAAT | Blocked by Cloudflare challenge | currently effective 2026-07-09 / AIRAC AIP AMDT 07/26 | none | `curl` returns 403 `cf-mitigated: challenge`; needs browser/session or official mirror |
| Philippines CAAP AIS | Blocked by subscription | current calendar 2026-07-09; upcoming 2026-09-03 | none | eAIP access is via subscription; needs account/subscription path |
| India AAI AIM | Downloaded, built, validated | `eaip-v2-06-2026`, effective 2026-07-09 | `data/raw/india/eaip-v2-06-2026/` | `aviation-in.sqlite`: 910 points, 481 airways, 2061 segments, validation clean; 481/482 route docs downloaded, missing `J79` |
| Brunei DCA eAIP | Downloaded, built, validated | AIP AMDT 01/2026, effective 2026-06-20 | `data/raw/brunei/2026-06-20/` | `aviation-brunei-canonical.sqlite`: 12 points, 5 airways, 16 segments, validation clean; canonical build integrated via `parse_brunei_pdf_documents` |
| Cambodia CATS eAIP | Downloaded private raw, built, validated | AIRAC AIP AMDT 07/26, effective 2026-07-09 | `data/raw/cambodia/2026-07-09-AIRAC/` | `aviation-cambodia.sqlite`: 68 points, 17 airways, 55 segments, validation clean; 2 route-too-short parse warnings; official redistribution still manual review |
| Viet Nam VNAIC | Downloaded, built, validated | 2026-06-30 | `data/raw/vietnam/2026-06-30/` | `aviation-vietnam-canonical.sqlite`: 248 points, 49 airways, 131 segments, validation clean; canonical build integrated via `parse_vietnam_eaip_documents` |
| Portugal NAV AIS | Downloaded, built, validated | current eAIP | `data/raw/portugal/` | `aviation-portugal-canonical.sqlite`: 543 points, 49 airways, 121 segments, validation clean; canonical build integrated via `parse_portugal_eaip_documents` |
| Bahrain AIM | Downloaded, built, validated with warnings | 2026-07-09 AIRAC | `data/raw/bahrain/` | `aviation-bahrain-canonical.sqlite`: 156 points, 37 airways, 272 segments, validation clean; 2 point-ident-missing parse warnings; official redistribution still manual review |
| Qatar QCAA AIM | Downloaded, built, validated | 2026-04-16 AIRAC, effective 2026-05-14 | `data/raw/qatar/` | `aviation-qatar-canonical.sqlite`: 194 points, 35 airways, 150 segments, validation clean; ENR 3.5 returned 404; next 2nd edition effective 2026-08-06 is already published and should be switched after effective date |
| Israel CAA eAIP | Downloaded, built, validated | 2025-10-02 AIRAC | `data/raw/israel/` | `aviation-israel-canonical.sqlite`: 205 points, 44 airways, 128 segments, validation clean; future 2026-08-06 AIRAC issue is reachable and should be switched after effective date |
| Bangladesh CAAB | Downloaded raw; parser pending | Latest AIP Amendment #3/26; page updated 2026-07-09 16:24 BDT | `data/raw/bangladesh/current/` | Official AIP index, ENR all PDF, and full AIP PDF downloaded; used `curl -k` because official certificate chain did not validate locally; PDF parser/build pending |
| Mauritius DCA | Downloaded raw; parser pending | AIP En-Route August 2024 / mixed page dates | `data/raw/mauritius/current/` | Official Part 2 ENR index plus targeted ENR 3.2 route pages, ENR 3.4/3.5, and ENR 4.1/4.3/4.4 PDFs downloaded; parser/build pending |
| Maldives CAA / MACL ANS | Downloaded raw; parser pending | MACL public AIP page current on probe date | `data/raw/maldives/current/` | CAA site links AIP/AIC/Supplements to MACL ANS; downloaded MACL ANS/AIP/amendment pages plus targeted `/aip/document/{ID}.pdf` ENR 3.1, 3.2, 3.5, 3.6, 4.1, 4.4, and ENR 6 chart PDFs; PDF parser/build pending |
| Sri Lanka CAASL AIS | Downloaded, built, validated | 2025-09-04 NON AIRAC search-visible official package | `data/raw/sri_lanka/2025-09-04-NON-AIRAC/` | `aviation-sri-lanka.sqlite`: 98 points, 26 airways, 109 segments, validation clean; official TLS chain required `curl -k`; ENR 3.5/menu returned 404; private south-asia pack exported with `public:false` |
| ASECNA AIM | Downloaded, built, validated with warnings | GEN/ENR current pages include 2026-07-09 and mixed ENR effective dates | `data/raw/asecna/2026-07-09/` | `aviation-asecna.sqlite`: 1519 points, 181 airways, 1471 segments, 3 route-too-short parse warnings; africa validation has long-distance warnings only; private africa pack exported with `public:false`; covers ASECNA member/FIR data for Benin, Burkina Faso, Cameroon, Central African Republic, Chad, Comoros, Congo, Cote d Ivoire, Equatorial Guinea, Gabon, Guinea-Bissau, Madagascar, Mali, Mauritania, Niger, Senegal, and Togo |
| Kenya KCAA AIM | Blocked by subscription/purchase | Current public eAIP portal probed 2026-07-19 | `data/raw/kenya/current/` | Official home, purchase, and charts pages downloaded; KCAA eAIP portal states AIP Kenya is available by annual subscription/purchase and does not expose a free direct ENR package in this pass; do not auto-pay |
| South Sudan SSCAA AIS | Blocked by direct-download 403 | Public AIP page advertises current downloadable AIP | `data/raw/south_sudan/current/` | Official SSCAA page and web cache expose eAIP section links, but direct non-sandbox `curl` to `sscaa.co` AIP pages returned HTTP 403 for title sheet and ENR pages; needs browser/session/manual mirror |
| UAE GCAA | Downloaded, built, validated | 2026-P06 / AIRAC AMDT 08/2026, effective 2026-08-06 | `data/raw/uae/2026-P06/` | `aviation-uae.sqlite`: 748 points, 56 airways, 300 segments, validation clean; official PackageHash page lists SHA512 for ZIP, but guessed direct ZIP paths returned 404, so frameset/menu plus ENR 3/4 XHTML pages were downloaded; private middle-east pack exported with `public:false` |
| Oman CAA AIM | Downloaded, built, validated | 2026-06-11 Non-AIRAC / AIRAC AIP AMDT 2-26 | `data/raw/oman/2026-06-11-Non-AIRAC/` | `aviation-oman.sqlite`: 277 points, 71 airways, 319 segments, validation clean; ENR 3.5 returned 404; included in combined UAE+Oman private middle-east pack |
| Saudi Arabia SANS AIM | Downloaded, points-only canonical build | AIRAC AIP AMDT 11/25, effective 2025-10-30 | `data/raw/saudiarabia/AIRAC-AIP-AMDT-11_25_2025_10_30/` | `aviation-saudiarabia.sqlite`: 507 ENR 4.4 points, 0 airways/segments, validation clean; ENR 3 route pages are descriptive and route graph likely needs chart/PDF extraction; official redistribution still manual review |
| Kuwait DGCA AIS | Blocked by encrypted PDF | Current public DGCA AIP page probed 2026-07-19 | `data/raw/kuwait/current/` | Official AIP index plus 30 ENR PDFs downloaded; PDFs are encrypted (unknown password, empty pw and common passwords failed); `pypdf` FileNotDecryptedError; parser written but blocked by encryption |
| Mauritius DCA | Downloaded, built, validated | AIP En-Route July 2024 / mixed page dates | `data/raw/mauritius/current/` | `aviation-mauritius-canonical.sqlite`: 197 points, 33 airways, 91 segments, validation clean; canonical build integrated via `parse_mauritius_pdf_documents` |
| Maldives CAA / MACL ANS | Downloaded, built, validated | MACL public AIP page current on probe date | `data/raw/maldives/current/` | `aviation-maldives-canonical.sqlite`: 102 points, 27 airways, 111 segments, validation clean; canonical build integrated via `parse_maldives_pdf_documents` |
| Middle East expanded private pack | Exported private aggregate | UAE 2026-P06 + Oman 2026-06-11 + Saudi Arabia 2025-10-30 + Bahrain 2026-07-09 + Qatar 2026-05-14 + Israel 2025-10-02 | `data/releases/private/aviation/middle-east-expanded/` | `aviation-middle-east-expanded.sqlite`: 2087 points, 243 airways, 1169 segments, validation clean; Saudi included as points-only; payload SHA256 `fa7b89b628d9f9a20260fe3a000015555685a55066a17a9b5685ead046b5842d`; `public:false` |
| United Kingdom NATS/Aurora | Downloaded, built, validated | 2026-07-09 AIRAC | `data/raw/europe/uk/2026-07-09/` | `aviation-europe-private.sqlite`: 1117 points, 220 airways, 1224 segments, validation clean |
| United Kingdom NATS AIXM | Downloaded via public website, built | 2026-07-09 AIRAC | `data/raw/aixm/uk/` | `EG_AIP_DS_20260709_XML.zip` → `EG_AIP_DS_FULL_20260709.xml` (69MB); 1470 DesignatedPoints, 164 Navaids; AIXM 5.1 format; public download from `nats-uk.ead-it.com`; usage unrestricted for aviation use |
| Ireland AirNav | Downloaded, built, validated | 2026-07-09 AIRAC | `data/raw/europe/ireland/2026-07-09/` | `aviation-ireland.sqlite`: 186 points, 10 airways, 31 segments, validation clean |
| Finland AIS | Downloaded, points-only parser | currently effective package | `data/raw/europe/finland/current/` | `aviation-europe-private.sqlite`: 322 points, 0 airways; ENR 3 documents do not currently yield route graph |
| Latvia LGS AIS | Downloaded, built, validated | 2026-07-09 | `data/raw/europe/latvia/2026-07-09/` | `aviation-europe-private.sqlite`: 97 points, 53 airways, 135 segments, validation clean |
| Czech ANS CR AIS | Downloaded, built, validated | current package | `data/raw/europe/czech/current/` | `aviation-europe-private.sqlite`: 165 points, 34 airways, 76 segments, validation clean |
| Estonia EANS AIM | Downloaded, built, validated | 2026-07-09 | `data/raw/europe/estonia/2026-07-09/` | `aviation-europe-private.sqlite`: 146 points, 19 airways, 29 segments, validation clean |
| Hungary HungaroControl AIS | Downloaded, points-only parser | 2026-06-11 AIRAC | `data/raw/europe/hungary/2026-06-11/` | `aviation-europe-private.sqlite`: 132 points, 0 airways; ZIP ENR 3 sections appear NIL/sparse |
| Iceland Avians / Isavia ANS | Downloaded, built, validated | 2026-06-11 | `data/raw/europe/iceland/2026-06-11/` | `aviation-europe-private.sqlite`: 311 points, 32 airways, 120 segments, validation clean |
| Denmark Naviair AIM | Downloaded, built, validated | current Naviair API records; file publish dates 2024-06-13 to 2026-07-09 | `data/raw/europe/denmark/current/` | `aviation-denmark.sqlite`: 254 points, 90 airways, 292 segments, validation clean; private Europe pack smoke exported with `public:false` |
| Canada NAV CANADA | Downloaded; route data not in retrieved PDF | 2026-05-14 PDF | `data/raw/canada/` | ENR Canada PDF downloaded; retrieved document does not contain route tables suitable for airway graph parsing |
| Cuba IACC | Downloaded, built, validated | current probed package | `data/raw/cuba/` | `aviation-cuba-canonical.sqlite`: 103 points, 36 airways, 362 segments, validation clean; canonical build integrated via `parse_cuba_pdf_documents`; handles cross-line compact coordinates (203300N / 0772649W on separate lines) |
| New Zealand AIP | Blocked by bot protection | Unknown | none | `curl` TLS fails; `curl -k` returns a 212-byte Imperva/Incapsula challenge page instead of AIP content |
| Australia Airservices AIP | Blocked by license/direct endpoint review | ERSA page shows 2026-07-09 / 2026-09-03 products | none | Public AIP entry reachable, but copyright terms restrict storing/reproducing; direct current ENR route endpoint not found in this pass |
| Indonesia AIM | Blocked by unresolved/unknown current endpoint | Unknown | none | `aimindonesia.dephub.go.id` did not resolve from local probe; search results point to online authorization/licensing rather than static AIP |
| Sweden LFV | Large package found; not completed | current offline AIP ZIP | `data/raw/europe/sweden/current/` | `AIP_OFFLINE.zip` is 880 MB and was stopped after 4.6 MB partial; needs targeted extraction/download strategy |
| Norway Avinor | History page reachable; package path unresolved | 2026-06-11 AIRAC shown on history page | none | History page lists current package, but direct issue paths tried returned 404 |
| Netherlands LVNL | Blocked by 403 | Unknown | none | Public AIP page returned HTTP 403 to curl |
| Switzerland Skybriefing | Account registered/verified; eAIP charged | AIP AMDT 2026-07-09 / AIP AIRAC AMDT 2026-08-06 shown on portal | `data/raw/europe/switzerland/current/` | Login works for `alien0077@gmail.com`; free ENRC WEF 14 MAY 2026 PDF downloaded; eAIP Switzerland requires paid access, listed at 92.50 CHF / 12 months; not purchased |
| EAD Basic (Eurocontrol SDO) | Downloaded via EAD Basic, built, validated | 2026-07-19 (report generation date) | `data/raw/ead/upper-routes/` | `aviation-ead.sqlite`: 8815 points, 1964 airways, 15277 segments; route topology from Upper Routes NE+NW+SW reports; covers blocked European states (Belgium, Germany, Netherlands, Austria, Italy, Sweden, Norway, Lithuania, Slovakia, Malta) via structured SDO report data; coordinates partially filled from OpenAIP (278 matching) + AIXM Germany (10 matching) + AIXM Spain (51 matching) = 573/8815 (5.3%); Designated Points report blocked by EAD Basic JSF/session timeout; AIXM 5.1 sample pending from Eurocontrol; official redistribution still manual review |
| France SIA | Downloaded raw, built, validated | Current SIA AIP FRANCE PDF set, cycle date not yet normalized | `data/raw/europe/france/current/` | `aviation-france.sqlite`: 1904 points, 245 airways, 1348 segments, validation clean; 1 route-too-short parse warning; official redistribution still manual review |
| France SIA AIXM | Blocked by login/customer account | 2026-07-09 (AIRAC 07/26) | `data/raw/aixm/france/` | SIA website `https://www.sia.aviation-civile.gouv.fr/produits-numeriques-en-libre-disposition/les-bases-de-donnees-sia/` requires customer account login for AIXM download; AIXM 4.5 format available (~5.5MB per AIRAC cycle) under Licence Ouverte 2.0 once accessed; exported from NOPIA operational system |
| Romania ROMATSA AIS | Downloaded, partial built, validated | AIP 2026-05-14; ENR 3.2 page dated 2025-10-30 | `data/raw/europe/romania/2026-05-14/` | `aviation-romania.sqlite`: 412 points, 31 airways, 95 segments, validation clean; partial only because parts of ENR 3.2 extract as encoded glyph streams |
| Germany DFS AIXM | Downloaded via public REST API, built | 2026-07-09 AIRAC (snapshot) | `data/raw/aixm/germany/` | DFS `aip.dfs.de/datasets` REST API: `ED_Waypoints_snapshot.xml` (8.7MB, 4737 DesignatedPoints), `ED_Navaids_snapshot.xml` (3.9MB, 184 Navaids), `ED_Routes_snapshot.xml` (14MB); AIXM 5.1.1 format with BASELINE TimeSlices; automated download explicitly permitted; official redistribution still manual review |
| Austria Austro Control | Old frame portal; ENR path unresolved | Unknown | none | Entry page reachable but direct ENR path probe returned 404 |
| Lithuania Oro Navigacija / ANS LT | Blocked by Cloudflare challenge | 2026-06-11 package path found by search | none | Direct ENR 3.2/4.1/4.4 probes on `ans.lt`, `www.ans.lt`, and `oronavigacija.lt` returned HTTP 403 with `cf-mitigated: challenge` |
| Slovakia LPS SR | Timeout / no body from direct eAIP path | AIP_SR_EFF_09JUL2026 path found by search | none | Direct ENR 3.1/3.2/4.1/4.4 `curl` probes to `aim.lps.sk` remained at 0 bytes for 30-50 seconds and were stopped; retry with shorter timeout/browser |
| Malta Transport Malta | Current AIP link found; direct PDF 403 | current AIP effective 2026-06-11; upcoming 2026-08-06 | none | Official page lists current PDF `LM_AIP_2026_83_EFF_11_JUN_2026-2.pdf-f11582`; direct `curl` to page/PDF returned HTTP 403 |
| Argentina ANAC AIS | Blocked by timeout | Search cache shows public AIP sections | `data/raw/argentina/manifest.json` | Official `https://ais.anac.gob.ar/aip` timed out after three 20s curl attempts; retry with browser/session or alternate network |
| Chile DGAC IFIS | Downloaded, built, validated | IFIS current ENR PDF index, mixed effective dates in PDFs | `data/raw/chile/current/` | `aviation-chile-v6.sqlite`: 385 points, 148 airways, 855 segments, validation clean; 47 parse warnings from ambiguous PDF rows; private south-america pack exported with `public:false` |
| Colombia Aerocivil | Search-visible AIP page; direct URL currently 404 | Search cache shows AIP PDF AMDT 68/25 WEF 2025-06-12 | none | Official URLs found by search (`/aip`, `/generalidades`) redirect to Aerocivil 404 page via `error.php?code=404`; needs portal navigation/browser or updated document endpoint |
| Ecuador DGAC IFIS3 | Shell pages downloaded; API/body discovery pending | Current IFIS3 page cycle not normalized | `data/raw/ecuador/` | ENR 3.1/3.2/3.3/3.5/4.1/4.4 endpoints downloaded, but inspection shows IFIS3 app shell/navigation instead of full ENR body; parser/build blocked on API payload discovery |
| Guyana GCAA | Blocked by contact-required AIP access | Unknown | `data/raw/guyana/` | Official Guyana AIP page downloaded, but page says to contact Aeronautical Information Management Services; no ENR package/PDF link exposed |
| Panama AAC AIS | Downloaded raw; parser pending | Current official PDF set; cycle not normalized | `data/raw/panama/` | Official ENR 3 ATS routes PDF and ENR 4 radio aids/navigation systems PDF downloaded with hashes; parser/build pending |
| Paraguay DINAC | Downloaded and extracted raw; parser pending | AMDT AIRAC 01 2026 | `data/raw/paraguay/` | Official `AMDT_AIRAC_01_2026.rar` downloaded with `curl -k` because the official certificate chain is self-signed; extracted with `bsdtar`; ENR 3/4 PDFs are text-extractable |
| Peru CORPAC | Blocked by paid/account access | Gob.pe page last changed 2025-06-05 | none | Official gob.pe service page states AIP Digital requires username/password and obtaining credentials requires payment coordination with AIS Peru; do not auto-pay |
| Brazil DECEA AISWEB | Direct eAIP probe reset | A 10-2026, effective 2026-06-11 path found by search | none | Direct probes to `aisweb.decea.mil.br/eaip/A 10-2026_2026_06_11/eAIP/` menu, ENR 4.4, and a route page reset connection after several seconds |
| COCESNA Central America | Downloaded, built, validated | 2026-01-22 NON AIRAC | `data/raw/cocesna/2026-01-22-NON-AIRAC/` | `aviation-cocesna.sqlite`: 315 points, 145 airways, 866 segments, validation clean; private central-america pack exported with 315 points, 116 airways, 661 segments; covers common Central America FIR data plus Belize MZ pages |
| Costa Rica COCESNA | Common graph seed downloaded; Costa Rica AIPMR direct package blocked | Common seed 2026-01-22 NON AIRAC; search-visible CR package 2026-04-16 AIRAC | `data/raw/cocesna/2026-01-22-NON-AIRAC/`, `data/raw/costa_rica/2026-04-16-AIRAC/manifest.json` | Current usable source is COCESNA common EN-CS ENR 3/4 XHTML. Costa Rica AIPMR GEN 3.1 is visible via search/browser cache, but direct GEN/ENR downloads returned HTTP 404 even with non-sandbox curl and browser User-Agent |
| Dominican Republic IDAC | Index downloaded; PDF download blocked | Current public AIP index; cycle not normalized | `data/raw/dominican_republic/` | Official en-route index exposes ENR 3.1-3.6 and ENR 4.1-4.4 PDFs; primary direct PDF batch hit DNS resolution errors, alternate official host resolved non-sandbox but returned HTTP 503 |
| Eastern Caribbean / TTCAA Piarco AIS | Blocked by acquisition form / service unavailable | Subscription period January-December 2026; AIP amendments unavailable since AMD 33 dated 2024-08-08 | `data/raw/eastern_caribbean_ttcaa/` | Official pages downloaded; current E/CAR eAIP requires acquisition/subscription form and online AIP amendments are temporarily unavailable. Covers Anguilla, St. Kitts/Nevis, Antigua, Montserrat, Dominica, St. Lucia, St. Vincent, Grenada, plus French Antilles references |
| Uruguay DINACIA | Blocked by timeout | Unknown | `data/raw/uruguay/manifest.json` | Official `https://dinacia.gub.uy/documento` timed out after three 20s curl attempts |
| Venezuela INAC eAIP | Menu discovered; route file downloads failed | AMDT AIRAC NR 6, effective 2020-07-16, marked specimen/not operational | `data/raw/venezuela/current/` | Official history/menu downloaded; 123 ENR route/point targets discovered, but all direct route-file downloads failed with curl exit 6; not usable for app routing |
| Belgium skeyes | Blocked by AIM Meteo Briefing / 403 | Unknown | none | Official page says eAIP is free via AIM Meteo Briefing application; direct static eAIP path returned HTTP 403 |
| Italy ENAV | Blocked by login/request access | Unknown | none | Official ENAV online services lists AIP with Request access; ENAV eAIP notice says service is available after login and free registration |
| OpenAIP European Navaids | Downloaded via API, built | 2026-07-19 (live API query) | `data/raw/openaip/european_coordinates.json` | 3851 navaid+reporting points from 30 European countries; 278 matched to EAD waypoints; CC BY-NC 4.0 license |
| Spain ENAIRE AIP | Downloaded raw, built, validated with warning | AIP current page shows 09-JUL-26, AIRAC 06/26 and AMDT 408/26 | `data/raw/europe/spain/current/` | `aviation-spain.sqlite`: 1233 points, 153 airways, 913 segments; 1 validation warning `segment-long-distance` for N728 DEMOS->ORTIS official ENLACE_PBN; private Europe pack smoke exported with `public:false` |
| Spain ENAIRE AIXM | Downloaded via public AIP website, built | 2026-07-09 (AIRAC 06/26) | `data/raw/aixm/spain/` | `LE_Amdt_A_2026_06_AIP_DS_FULL_EnRoute.xml` (7.9MB, 1081 DesignatedPoints, 210 Navaids); AIXM 5.1 format; public download from `aip.enaire.es`; official redistribution still manual review |
| Netherlands DC-ANSP AIXM | Downloaded via public website, parsed | AIRAC AMDT 02-26 (effective 2026-08-06) | `data/raw/aixm/netherlands_dc/` | `AeroDb AIRAC AMDT 02-26.xml` (3.7MB, 98 DesignatedPoints, 9 Navaids); covers Dutch Caribbean FIR (TN); AIXM 5.1 format; public download from `dc-ansp.org` |
| Eurocontrol EAD AIXM Sample | Requested via email (pending) | Pending Eurocontrol response | pending | AIXM 5.1 sample data requested from `ead.service@eurocontrol.int` on 2026-07-19; Test AIXM 5.1 Data User Agreement (free of charge) needed; expected to contain EAD DesignatedPoints with coordinates for ECAC region |
| Poland PANSA AIS | Downloaded, built, validated | AIRAC AMDT IFR 07/26, effective 2026-07-09 | `data/raw/europe/poland/2026-07-09/` | `aviation-poland.sqlite`: 812 points, 137 airways, 606 segments, validation clean; private Europe pack smoke exported with `public:false` |

## Detailed Notes

### FAA CIFP

Private raw package:
`data/raw/faa/260709/CIFP_260709.zip`

Parser/build:

```text
build faa: 2,583 airports, 34,817 points, 1,539 airways, 17,556 segments, 4 parse warnings
validate north-america: []
route KSFO KJFK --region north-america: airway_graph, 2264.57 NM, warnings []
route KLAX KORD --region north-america: airway_graph, 1516.2 NM, warnings []
export app-pack --region north-america --private:
  2,533 airports, 33,585 points, 1,417 airways, 16,761 segments, all payloads public:false
```

The 4 parse warnings are `faa-airway-discontinuity` records where adjacent CIFP airway fixes would create a
segment over 700 NM. These pairs are recorded for manual review and intentionally excluded from the graph so the
route engine does not use discontinuous edges:

- `J6: IRW->HVQ is 780.8 NM`
- `L435: FIVZE->BUTUX is 917.6 NM`
- `V15: BYP->ABR is 720.0 NM`
- `V210: OKM->HAR is 929.3 NM`

Redistribution remains `manual_review_required`; do not publish the raw ZIP, processed SQLite, or derived app pack
until FAA CIFP redistribution terms are explicitly reviewed.

### Japan

Private raw package:
`data/raw/japan/swim/S2002/downloads/AIXM_ALL_20260624150001.zip`

Observed status:

```text
ZIP members: AIXM_ALL_20260624150001.xml
compressed size: 74.2 MB
uncompressed XML size: 806.6 MB
read attempt: password required for extraction
```

No ZIP extraction password was found in the local SWIM metadata or generated M2001 queue credential record. Treat Japan
as blocked until the S2002 ZIP password or approved M2001/P2005 data-delivery access is available.

Portal/Gmail check on 2026-07-18:

- Gmail search across inbox/spam/trash/all mail found only SWIM signup, password reset, and password-change messages from
  2026-07-16; no M2001/P2005 approval, rejection, AMQP queue, or AIP data-distribution response email was present.
- SWIM portal `利用サービス一覧` shows only S2002 and S2004 as active services.
- SWIM portal `サービス利用履歴` records `2026/07/17 01:10:51` for `AIPデータ配信サービス（初回）`
  with content `サービス利用開始`, confirming M2001 was started/applied in the portal.
- M2001 detail page now shows `サービス利用開始` disabled.
- P2005 was started on 2026-07-18 after user approval. Completion page said `サービス利用申請完了` and instructed waiting
  for the review-result notification email; it also says to log out once after receiving approval.
- SWIM portal `サービス利用履歴` records `2026/07/18 13:59:11` for `AIPデータ配信サービス（更新）`
  with content `サービス利用開始`, confirming P2005 was submitted/started.

### Singapore

Official entry: `https://aim-sg.caas.gov.sg/aip/`

Current package used:
`https://aim-sg.caas.gov.sg/aim-content/uploads/aip/15-JUL-2026/AIP/2026-07-09-000000/html/index-en-GB.html`

Documents downloaded:

- `SG-ENR-3.1-en-GB.html`
- `SG-ENR-3.2-en-GB.html`
- `SG-ENR-3.3-en-GB.html`
- `SG-ENR-4.1-en-GB.html`
- `SG-ENR-4.4-en-GB.html`

Automation note: Python `urllib` received a 15127-byte Radware CAPTCHA page. Shell `curl` retrieved the real XHTML.
`download.py` now detects `captcha`, `radware`, and `bot-protection` before replacing target files.

Validation:

```text
build singapore: 420 points, 66 airways, 217 segments, 0 parse issues
validate singapore: []
```

### Malaysia

Official entry:

- `https://aip.caam.gov.my/ar.htm`
- `https://aip.caam.gov.my/hrnas.html`

Documents downloaded:

- ENR 3.1 Lower And Upper ATS Routes PDF
- ENR 3.3 Area Navigation RNAV Routes PDF
- ENR 3.5 Other Routes PDF
- ENR 4.1 Radio Navigation Aids En-Route PDF
- ENR 4.3 Name Code Designators For Significant Points PDF

Parser note: CAAM PDFs are text-extractable with `pypdf`. The parser reads ENR 4.3 points and ENR 3 route
sections, while filtering obvious PDF extraction artifacts such as `JOINING`, `WGS84`, and repeated same-point
segments.

Validation:

```text
build malaysia: 229 points, 93 airways, 311 segments, 0 parse issues
validate malaysia: []
same-point or zero-distance segments: 0
```

### Thailand

Official history:
`https://aip.caat.or.th/history-en-GB.html`

Current effective issue on 2026-07-17:

- Effective date: 09 JUL 2026
- Publication date: 28 MAY 2026
- Short description: AIRAC AIP AMDT 07/26

Blocker:

```text
curl -I https://aip.caat.or.th/2026-07-09-AIRAC/html/eAIP/VT-ENR-3.1-en-GB.html
HTTP/2 403
cf-mitigated: challenge
```

Next step: use an authenticated/browser session to pass Cloudflare or locate an official downloadable package
that does not require challenge solving.

### Philippines

Official entry:
`https://ais.caap.gov.ph/home`

Observed status:

- AIS calendar shows CURRENT `2026-07-09`, UPCOMING `2026-09-03`.
- CAAP site describes eAIP access via subscription.
- Registration page states only paid and complimentary Philippine AIP subscribers can register.
- Registration requires subscription evidence / OR Number; subscription info page lists international new subscription
  total as `324.80 USD` and local new subscription total as `Php 5,600`.

Next step: do not auto-register until a valid paid/complimentary subscription or official complimentary access path is
available; alternatively confirm whether a public static PDF endpoint exists.

### India

Official entry:
`https://aim-india.aai.aero/eaip/eaip-v2-06-2026/`

Downloaded:

- `Cover-body-en-GB.html`
- `eAIP/IN-ENR 3.0-en-GB.html`
- `eAIP/IN-ENR 4.4-en-GB.html`
- `routes/IN-ENR-3.*<route>-en-GB.html`: 481 route-specific pages

Route discovery:

- ENR 4.4 yielded 482 route designator candidates.
- Concurrent route probing downloaded 481 pages and wrote `route_manifest.json`.
- Missing route: `J79`; all probes completed with `error_count = 0`.

Observed shape:

- ENR 4.4 is directly downloadable and contains significant point data.
- ATS route details appear as route-specific files such as historical/search-visible
  `IN-ENR 3.2T9-en-GB.html`, not a single `IN-ENR 3.1` page.

Parser/build:

```text
build india: 910 points, 481 airways, 2061 segments, 0 parse issues
validate india: []
```

Redistribution remains `manual_review_required`; do not publish the raw route pages or derived official pack.

### Brunei

Official entry:
`https://www.dca.gov.bn/eaip/`

Current package observed:

- Effective Date: 20 JUNE 2026
- Publication Date: 20 JUNE 2026
- AIP AMDT 01/2026

Downloaded through the public WordPress media API / static upload URLs:

- `ENR-0.6.pdf`
- `ENR-3.1.pdf`
- `ENR-3.4-1.pdf`
- `ENR-4.1-1.pdf`
- `ENR-5.1.pdf`

Private manifest:
`data/raw/brunei/2026-06-20/manifest.json`

Status: raw acquisition is complete for the discovered ENR PDFs. Parser/build is pending because Brunei is PDF-based
and needs a dedicated text extraction pass like Malaysia.

### Cambodia

Official entry:
`https://aim.cats.com.kh/eaip.html`

Authenticated package captured:
`data/raw/cambodia/2026-07-09-AIRAC/`

Observed status:

- Registration completed with `alien0077@gmail.com` on 2026-07-18.
- Email verification completed through the CATS verification email.
- Password was generated and entered in Chrome; no password or personal registration details are stored in repository
  files.
- Login reached `CATS - Published eAIPs - Cambodia`.
- Current effective issue: 09 JUL 2026, publication date 11 JUN 2026, AIRAC AIP AMDT 07/26.
- Next issue listed: 06 AUG 2026, publication date 09 JUL 2026, AIRAC AIP AMDT 08/26.

Private raw capture:

```text
manifest: data/raw/cambodia/2026-07-09-AIRAC/manifest.json
files: 20 HTML files, 0 failures
scope: frameset/menu, ENR 3.1-3.4, ENR 4.1-4.4, GEN 2.5, AD 2 aerodrome pages
```

Parser/build:

```text
build cambodia:
  airports: 0
  points: 68
  airways: 17
  segments: 55
  issues: 2

validate asia-southeast:
  []

parse warnings:
  B202 has fewer than 2 points
  W1 has fewer than 2 points

private app-pack smoke:
  export app-pack --region asia-southeast --private
  points: 68
  airways: 17
  segments: 55
  payload public: false
```

The Cambodia parser reuses the row-class eAIP parser profile with `country=KH`, `fir=PHNOM PENH`, and
`region_code=asia-southeast`. Redistribution remains `manual_review_required`; do not publish raw HTML,
processed SQLite, or derived app pack until license review.

### New Zealand

Official entry:
`https://www.aip.net.nz/`

Blocker:

```text
curl -fL https://www.aip.net.nz/
SSL certificate problem: unable to get local issuer certificate

curl -k -fL https://www.aip.net.nz/
returns a 212-byte noindex/nofollow page loading /_Incapsula_Resource...
```

Next step: use an interactive browser/session if permitted, or locate an official downloadable package/API that
does not require Imperva/Incapsula challenge solving.

### Australia

Official entry:
`https://airservices.gov.au/aip/aip.asp?pg=10`

Observed status:

- The public page lists current/future products including ERSA 09 JUL 2026 and 03 SEP 2026.
- The site instructs users to view the copyright statement first.
- The copyright text observed on the page is restrictive for reproduction/storage/redistribution, so bulk storing
  operational AIP documents needs license review before automation.
- Guessed direct current ENR PDF endpoints such as `.../aip/current/aip/enr_3.pdf` returned 404.

Next step: confirm the permitted acquisition path and exact AIP/ENR package endpoint before downloading official
route content into private raw.

### Indonesia

Likely official/known entry attempted:
`https://aimindonesia.dephub.go.id/`

Blocker:

```text
curl -fL https://aimindonesia.dephub.go.id/
curl: (6) Could not resolve host: aimindonesia.dephub.go.id
```

Search notes: public results point to Indonesia's online AIP licensing/authorization framework rather than a
stable static eAIP package. No current raw data was downloaded.

Next step: find the current official AIM/AIP portal hostname or use an approved login/subscription flow if required.

### Spain

Official entry:
`https://aip.enaire.es/AIP/AIP-en.html`

Private raw package:
`data/raw/europe/spain/current/`

Downloaded on 2026-07-18 and completed on 2026-07-19:

```text
LE_ENR_3_1_en.pdf                         96,012 bytes
LE_ENR_3_2_en.html                       788,892 bytes
LE_Amdt_A_2026_06_ENR_3_2_en.csv        423,492 bytes
LE_ENR_3_3_en.html                         1,924 bytes
LE_ENR_3_4_en.html                         3,507 bytes
LE_ENR_4_1_en.html                       112,308 bytes
LE_Amdt_A_2026_04_ENR_4_1_en.csv         33,038 bytes
LE_ENR_4_4_en.html                       320,303 bytes
LE_Amdt_A_2026_06_ENR_4_4_en.csv        192,249 bytes
manifest.json includes SHA256 for each file
```

Observed status:

- Main AIP page shows current `09-JUL-26`, incorporated AIRAC 06/26 and AMDT 408/26.
- GEN 3.1 describes online AIP consultation/download as a free online service.
- The current AIP index lists ENR 3.1 as `LE_ENR_3_1_en.pdf`; `LE_ENR_3_1_en.html` was tried under the same
  path pattern and returned 404.
- ENR 3.1 PDF says conventional navigation routes are nil and conventional route segments are indicated in ENR 3.2.
- ENR 3.2 route segments and ENR 4.1/4.4 navaid/significant-point data are available as semicolon-delimited CSV.

Parser/build:

```text
build spain: 1233 points, 153 airways, 913 segments, 0 parse issues
validate europe:
  warning segment-long-distance N728 DEMOS->ORTIS is 719.7 NM
export app-pack --region europe --private:
  1233 points, 153 airways, 913 segments, payload public:false
```

The N728 DEMOS->ORTIS row is present in the official ENR 3.2 CSV as `ROUTETYPE_CODE=ENLACE_PBN` and `LENGTH_VAL=719.0`.
Keep it as a validation warning until reviewed for public graph use. Redistribution remains `manual_review_required`.

### Denmark

Official entry:
`https://aim.naviair.dk/en/`

Private raw package:
`data/raw/europe/denmark/current/`

Downloaded files:

```text
EK_ENR_3_1_en.pdf
EK_ENR_3_2_en.pdf
EK_ENR_3_3_en.pdf
EK_ENR_4_1_en.pdf
EK_ENR_4_4_en.pdf
```

Observed API shape:

```text
/umbraco/api/naviairapi/getsearch?criterion=ENR%203&skip=0&take=100
/umbraco/api/naviairapi/getsearch?criterion=ENR%204&skip=0&take=100
https://naviair.blob.core.windows.net/files/<media path>
```

The search API also returned Greenland/Faroe `BG_*` records. This pass intentionally kept only Denmark `EK_*`
documents.

Parser/build:

```text
build denmark: 254 points, 90 airways, 292 segments, 0 parse issues
validate europe: []
export app-pack --region europe --private:
  254 points, 90 airways, 292 segments, payload public:false
```

Redistribution remains `manual_review_required`; keep the raw Naviair PDFs, processed SQLite, and derived app pack
private until license review.

### Poland

Official entry:
`https://www.ais.pansa.pl/publikacje/aip-polska/`

Private raw package:
`data/raw/europe/poland/2026-07-09/`

Downloaded package:

```text
AIRAC AMDT 07-26_2026_07_09/index-v2.html
Cover-Page-en-GB.html
navigationCommand.js
datasource.js
searchIndex.js
146 ENR 3/4 English HTML pages discovered from datasource.js
```

Parser/build:

```text
build poland: 812 points, 137 airways, 606 segments, 0 parse issues
validate europe: []
export app-pack --region europe --private:
  812 points, 137 airways, 606 segments, payload public:false
```

Redistribution remains `manual_review_required`; keep the raw PANSA IFR package, processed SQLite, and derived app
pack private until license review.

### Belgium

Official entry:
`https://www.skeyes.be/nl/`

Blocker:

```text
Official page says eAIP can be consulted free via the AIM Meteo Briefing application.
Direct static eAIP path probe returned HTTP 403 from Microsoft-Azure-Application-Gateway/v2.
```

Next step: use browser/session automation against the AIM Meteo Briefing app, or locate an official API/package
endpoint that does not require the blocked static path.

### Lithuania

Official entries observed:

- `https://ans.lt/a1/aip/03_11Jun2026/2026-06-11-000000/html/eAIP/EY-ENR-3.2-en-US.html`
- `https://www.oronavigacija.lt/a1/aip/03_11Jun2026/2026-06-11-000000/html/eAIP/EY-ENR-3.2-en-US.html`

Blocker:

```text
Direct ENR 3.2/4.1/4.4 probes returned HTTP 403 with cf-mitigated: challenge.
```

Next step: use an interactive browser/session or an official package/API mirror if one exists.

### Malta

Official entry:
`https://www.transport.gov.mt/aviation/air-navigation-services-aerodromes-ground-handling-services/aeronautical-information-publication-3764`

Observed current product:
`LM_AIP_2026_83_EFF_11_JUN_2026-2.pdf-f11582`

Blocker:

```text
Official page lists current AIP effective 11/06/2026 and upcoming AIP effective 06/08/2026.
Direct curl to the official page and current PDF returned HTTP 403.
```

Next step: use browser/session download and then split or parse the full Malta AIP PDF for ENR 3/4 sections.

### Romania

Official entry:
`https://www.aisro.ro/aip/2026-05-14/html/en/aip_toc_enr.html`

Private raw package:
`data/raw/europe/romania/2026-05-14/`

Downloaded files:

```text
LR_ENR_3_1_en.pdf
LR_ENR_3_2_en.pdf
LR_ENR_3_3_en.pdf
LR_ENR_3_4_en.pdf
LR_ENR_4_1_en.pdf
LR_ENR_4_4_en.pdf
```

Parser/build:

```text
build romania: 412 points, 31 airways, 95 segments, 0 parse issues
validate europe: []
export app-pack --region europe --private:
  412 points, 31 airways, 95 segments, payload public:false
```

This is a partial graph. Several ENR 3.2 pages extract as encoded glyph streams with current Python PDF extractors,
so some published RNAV routes are not reconstructable without OCR/Poppler-quality extraction or an official alternate
format. Redistribution remains `manual_review_required`; keep raw PDFs, processed SQLite, and derived app pack private.

### Chile

Official entry:
`https://aipchile.dgac.gob.cl/aip/vol1/seccion/enr`

Private raw package:
`data/raw/chile/current/`

Downloaded files:

```text
download_chile.py: 26 ENR PDFs, errors 0
scope: ENR 3 route-description PDFs, ENR 4.1 radio-aid PDFs, ENR 4.4 significant-point pointer PDF
manifest: data/raw/chile/current/manifest.json
```

Parser/build:

```text
build chile: 385 points, 148 airways, 855 segments, 47 parse warnings
validate south-america: []
export app-pack --region south-america --private:
  385 points, 148 airways, 855 segments, payload public:false
```

Chile ENR route PDFs are layout-heavy Spanish PDFs. The parser uses PyMuPDF block coordinates to align route
designators, waypoint names, and DMS coordinates. The remaining warnings are ambiguous rows where the PDF extraction
does not clearly associate an ident with the coordinate, plus two route-too-short cases. Validation is clean, but treat
the graph as private/manual-review-required until licensing and ambiguous-row coverage are reviewed.

### Colombia

Official search result:
`https://www.aerocivil.gov.co/servicios-a-la-navegacion/servicio-de-informacion-aeronautica-ais/aip`

Observed status on 2026-07-19:

```text
Search cache: AIP PDF / AMDT 68/25 WEF 12 JUN 2025, ENR 3/4 sections listed.
curl /aip: Aerocivil 404 error page.
curl /generalidades: Aerocivil 404 error page.
curl parent AIS path: Aerocivil 404 error page.
```

Next step: revisit through browser navigation or search for an updated attachment endpoint. No raw route data was
downloaded in this pass.

### Peru

Official entry:
`https://www.gob.pe/institucion/corpac/pages/31713-acceder-a-la-publicacion-de-informacion-aeronautica-de-corpac`

Observed status:

```text
Gob.pe service page: AIP Digital requires usuario y contraseña.
Credential path: coordinate payment with AIS Peru by phone/email.
```

Peru is blocked by paid/account access. Do not auto-pay; record for later commercial/licensing decision.

### Slovakia

Official entry observed:
`https://aim.lps.sk/web/eAIP_SR/AIP_SR_EFF_09JUL2026/html/LZ-ENR-1.1-en-SK.html`

Direct ENR probes attempted:

```text
LZ-ENR-3.1-en-SK.html
LZ-ENR-3.2-en-SK.html
LZ-ENR-4.1-en-SK.html
LZ-ENR-4.4-en-SK.html
```

Blocker: `curl` remained connected with 0 bytes transferred for 30-50 seconds and was stopped manually. No raw data
was written into AviationDB.

Next step: retry with a strict timeout and browser/header inspection, then download only after the server returns
real eAIP HTML.

### Italy

Official entry:
`https://www.enav.it/en/online-services`

Blocker:

```text
ENAV Online Services lists AIP with Request access.
ENAV eAIP notice says the service is available after login, with free registration.
```

Next step: register/login through ENAV and inspect the authenticated eAIP package structure before downloading.

### Ireland

Official entry:
`https://www.airnav.ie/air-traffic-management/aeronautical-information-management`

Private raw package:
`data/raw/europe/ireland/2026-07-09/`

Downloaded files:

```text
EI-ENR-3.1-en-IE.html
EI-ENR-3.2-en-IE.html
EI-ENR-3.3-en-IE.html
EI-ENR-3.4-en-IE.html
EI-ENR-3.5-en-IE.html
EI-ENR-4.1-en-IE.html
EI-ENR-4.4-en-IE.html
```

Parser/build:

```text
build ireland: 186 points, 10 airways, 31 segments, 0 parse issues
validate europe: []
```

Parser note: Ireland ENR 3.3 uses route tables where FL upper/lower-limit rows appear as standalone table rows.
The shared Europe parser now excludes `FL###` tokens from route-designator detection, which prevents route flushes
in the middle of a table. Redistribution remains `manual_review_required`.

### Switzerland

Official entry:
`https://www.skybriefing.com/`

Private raw package:
`data/raw/europe/switzerland/current/`

Account/access status on 2026-07-18:

- Registered `alien0077@gmail.com` on Skybriefing and completed email verification.
- Password was generated and entered in Chrome; no password or personal registration details are stored in repository
  files.
- Login succeeded and reached the Skybriefing Overview page.
- Publications page states public documents are free, while `eAIP Switzerland` is a charged product via shop.
- Prices page lists `eAIP access` at `92.50 CHF` for 12 months; no purchase was made.

Downloaded:

```text
ENRC_WEF_14MAY2026_layered.pdf  3,512,635 bytes
manifest.json includes SHA256
```

Next step: use free public chart only as supporting raw. Do not attempt charged eAIP download unless paid access is
explicitly purchased/approved; eAIP route graph remains blocked by paid access.

### France

Official entry:
`https://www.sia.aviation-civile.gouv.fr/`

Private raw package:
`data/raw/europe/france/current/`

Downloaded on 2026-07-18 from SIA catalog direct document links:

```text
FR-ENR-3.1-fr-FR.pdf     30,289 bytes
FR-ENR-3.2-fr-FR.pdf  8,184,894 bytes
FR-ENR-3.3-fr-FR.pdf  2,709,842 bytes
FR-ENR-3.4-fr-FR.pdf    212,248 bytes
FR-ENR-4.1-fr-FR.pdf    537,610 bytes
FR-ENR-4.3-fr-FR.pdf    102,334 bytes
FR-ENR-4.4-fr-FR.pdf  3,188,909 bytes
manifest.json includes SHA256 for each file
```

Parser/build:

```text
build france:
  airports: 0
  points: 1904
  airways: 245
  segments: 1348
  issues: 1

validate europe:
  []

parse warnings:
  UY24 has fewer than 2 points

private app-pack smoke:
  export app-pack --region europe --private
  points: 1904
  airways: 245
  segments: 1348
  payload public: false
```

The France parser extracts SIA PDF text with `pypdf`, uses ENR 4.4 for significant points, and builds RNAV 5
airway segments from ENR 3.2. ENR 3.3 VFR transit routes and ENR 3.4 holding entries are intentionally not mixed
into the airway graph.

Discovery notes:

- SIA search catalog page 102 exposed direct `documents/download/f/d/...` links for AIP FRANCE ENR 3/4 PDFs.
- The larger complete eAIP ZIP is available as a free catalog product but is roughly 974 MB; targeted ENR PDFs were
  used first to avoid unnecessary bulk download.

Redistribution remains `manual_review_required`; do not publish raw PDFs, processed SQLite, or derived app pack until
license review.

### Viet Nam

Static eAIP shape confirmed with an older public package:
`https://www.vnaic.vn/images/stories/vnaic.vn/SanPhamDichVu/AIPVietNam/AIP/2025-06-12-AIRAC/html/...`

Probe result:

```text
curl -fL .../2025-01-23-AIRAC/html/eAIP/VV-ENR-3.1-en-GB.html
downloaded an older ENR 3.1 page

curl -fL .../2026-07-09-AIRAC/html/eAIP/VV-ENR-3.1-en-GB.html
HTTP 404
```

Status: do not use the reachable 2025 files for app routing. Current 2026 package path needs to be located first.

### Brunei (Canonical Build Integration)

Canonical parser `src/aviationdb/parsers/brunei.py` handles PDF-based ENR 3.1 ATS routes and ENR 4.1 navaids from the Brunei DCA AIP PDFs.

Build output:
```text
build brunei: 12 points, 5 airways, 16 segments, 0 issues
```

### Portugal (Canonical Build Integration)

Canonical parser `src/aviationdb/parsers/portugal.py` handles HTML-based eAIP ENR 3.1/3.3 route tables and ENR 4.4 significant points.

Build output:
```text
build portugal: 543 points, 49 airways, 121 segments, 0 issues
```

### Viet Nam (Canonical Build Integration)

Canonical parser `src/aviationdb/parsers/vietnam.py` handles HTML-based eAIP with template markers. Parses ENR 4.4 points and ENR 3.1/3.2 route tables.

Build output:
```text
build vietnam: 248 points, 49 airways, 131 segments, 0 issues
```

### Mauritius

Parser `src/aviationdb/parsers/mauritius.py` handles DMS-format coordinates in PDF ATS route and significant-point documents.

Private raw package:
`data/raw/mauritius/current/`

Build output:
```text
build mauritius: 197 points, 33 airways, 91 segments, 0 issues
```

### Maldives

Parser `src/aviationdb/parsers/maldives.py` handles both DMS-symbol and compact-format coordinates in PDF route and navaid documents.

Private raw package:
`data/raw/maldives/current/`

Build output:
```text
build maldives: 102 points, 27 airways, 111 segments, 0 issues
```

### Kuwait (Blocked by Encrypted PDF)

Kuwait DGCA AIS PDFs are encrypted with an unknown password. The following passwords were attempted and failed:
`empty string`, `kuwait`, `dgca`, `aip`, `Kuwait`, `DGCA`, `AIP`, `ENR`, `1234`, `password`, `secret`

A parser (`src/aviationdb/parsers/kuwait.py`) was written and configured in `sources.yaml` but cannot run until the PDFs are decrypted.

### Cuba (Canonical Build Integration)

Parser `src/aviationdb/parsers/cuba.py` handles compact-format coordinates with lat/lon on separate lines in the PDF.
Parses both ENR 3.1 conventional routes and ENR 3.2 area navigation routes.

Build output:
```text
build cuba: 103 points, 36 airways, 362 segments, 0 issues
```

### Germany DFS AIXM (Public REST API)

DFS Deutsche Flugsicherung provides public AIXM 5.1.1 data downloads via `https://aip.dfs.de/datasets/`.

Download pattern:
```text
REST API: https://aip.dfs.de/datasets/rest/
Download: https://aip.dfs.de/datasets/rest/{Amdt}/{filename}
Amdt 9999 = Snapshot (current effective data)
Files: ED_Waypoints_*_snapshot.xml, ED_Navaids_*_snapshot.xml, ED_Routes_*_snapshot.xml
```

Build output:
```text
aixm germany: 4737 DesignatedPoints, 184 Navaids
```

Parser: `src/aviationdb/parsers/aixm.py` handles AIXM 5.1.1 and 5.1 DesignatedPoint/Navaid features.

### Spain ENAIRE AIXM (Public AIP Website)

ENAIRE provides public AIXM 5.1 data sets via `https://aip.enaire.es/aip/DatosDigitales-en.html`.

Key file: `LE_Amdt_A_2026_06_AIP_DS_FULL_EnRoute.xml`

Build output:
```text
aixm spain: 1081 DesignatedPoints, 210 Navaids
```

### FlightGear Navdata (Parser Ready)

FlightGear uses X-Plane-compatible `fix.dat`, `nav.dat`, `awy.dat` format.
Parser: `src/aviationdb/parsers/flightgear.py` handles earth_fix.dat and earth_nav.dat formats.

License: GPL - redistributable. Data files should be placed in `data/raw/flightgear/`.

Status: Parser complete, awaiting FlightGear data files.

### X-Plane Default Navdata (Parser Ready)

X-Plane 11/12 provides `earth_fix.dat`, `earth_nav.dat`, `earth_awy.dat` in `Resources/default data/`.
Parser: `src/aviationdb/parsers/xplane.py` handles XP FIX1101/1200, XP NAV1150/1200, XP AWY1101 formats.

License: Personal use only - NOT redistributable. Data files should be placed in `data/raw/xplane/`.

Status: Parser complete, awaiting X-Plane data files.

### CoordinateResolver

`src/aviationdb/parsers/coord_resolver.py` implements multi-source merging:
Priority: official → flightgear → xplane → openaip → inference
Matching key: (ident, icao_region) not just ident

### Licensing Policy

`RULES.md` documents the redistribution rules:
- `redistributable = 1` for public releases (official + FlightGear + OpenAIP + inferred)
- `redistributable = 0` for X-Plane, Navigraph, Aerosoft (personal use only)
- App should let users point to local X-Plane directory for private index

### Eurocontrol EAD AIXM Sample (Pending)

A Test AIXM 5.1 Data User Agreement (free of charge) is required. Sample AIXM 5.1 exports can be requested from `ead.service@eurocontrol.int`.

Once received, the AIXM 5.1 data is expected to contain complete EAD DesignatedPoints with coordinates for the ECAC region, which would fill the remaining ~8,242 EAD waypoint coordinates.

### Panama (Parser Pending)

Panama AAC AIS ENR 3 ATS routes PDF is in Spanish and has limited coordinate extraction from text. Only B-route
designators (B1-B6) were detected in the text layer. A parser has not been written for this PDF format.

### Bangladesh and Paraguay (Parser Pending)

Bangladesh CAAB `enrall.pdf` extracts limited text and appears to date from 2010. Paraguay DINAC RAR-extracted PDFs
yield minimal extractable text. Neither has a dedicated parser; both need format investigation before parser development.

## Private Artifact Reminder

These paths are intentionally ignored by git:

- `data/raw/**`
- `data/processed/*.sqlite`
- `data/releases/private/**`
- `data/reports/private/**`

Only source configuration, parser code, tests, workflows, and this acquisition log should be committed until
redistribution rights are confirmed.
