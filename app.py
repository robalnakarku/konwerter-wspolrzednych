# Copyright (C) 2026  m@rio
# m@rio (OSM)   https://www.openstreetmap.org/user/m@rio
# Claude (LLM)  https://claude.ai/
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# https://www.gnu.org/licenses/gpl-3.0.html

import streamlit as st
import re
import io
from pyproj import Transformer

try:
    import mgrs as mgrs_lib
    MGRS_AVAILABLE = True
except ImportError:
    MGRS_AVAILABLE = False

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Konwerter Współrzędnych",
    page_icon="🌐",
    layout="centered",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Syne:wght@400;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Syne', sans-serif;
}

.stApp {
    background: #0f1117;
    color: #e8e8e8;
}

.main-title {
    font-family: 'Syne', sans-serif;
    font-weight: 800;
    font-size: 2.2rem;
    letter-spacing: -0.02em;
    color: #f0f0f0;
    margin-bottom: 0;
}

.subtitle {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.78rem;
    color: #5a6a7a;
    letter-spacing: 0.08em;
    margin-top: 0.2rem;
    margin-bottom: 2rem;
}

.result-table {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.82rem;
    width: 100%;
    border-collapse: collapse;
    margin-top: 1rem;
}

.result-table th {
    background: #1c2230;
    color: #6b8cba;
    font-weight: 600;
    padding: 8px 12px;
    text-align: left;
    border-bottom: 1px solid #2a3448;
    font-size: 0.72rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
}

.result-table td {
    padding: 7px 12px;
    border-bottom: 1px solid #1c2230;
    color: #d0dae8;
}

.result-table tr:hover td {
    background: #141922;
}

.result-table .ok {
    color: #7dd3a8;
}

.result-table .err {
    color: #e07070;
}

.format-badge {
    display: inline-block;
    background: #1c2a3a;
    color: #5a9fd4;
    border-radius: 3px;
    padding: 1px 6px;
    font-size: 0.72rem;
    font-family: 'JetBrains Mono', monospace;
}

.stat-box {
    background: #141922;
    border: 1px solid #1e2a3a;
    border-radius: 6px;
    padding: 12px 18px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.82rem;
    color: #8899aa;
    margin-bottom: 1rem;
}

.stat-box span {
    color: #7dd3a8;
    font-weight: 600;
}

div[data-testid="stTabs"] button {
    font-family: 'Syne', sans-serif;
    font-weight: 700;
    letter-spacing: 0.05em;
}

div.stButton > button {
    background: #1e3a5f;
    color: #a8c8e8;
    border: 1px solid #2a5080;
    font-family: 'Syne', sans-serif;
    font-weight: 700;
    letter-spacing: 0.05em;
    border-radius: 4px;
    transition: all 0.15s;
}

div.stButton > button:hover {
    background: #2a5080;
    color: #ddeeff;
    border-color: #4a80b0;
}

textarea, .stTextArea textarea {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.82rem !important;
    background: #0a0e14 !important;
    border: 1px solid #1e2a3a !important;
    color: #c8d8e8 !important;
}

.stSelectbox > div > div {
    background: #0a0e14 !important;
    border: 1px solid #1e2a3a !important;
}

hr.divider {
    border: none;
    border-top: 1px solid #1e2a3a;
    margin: 1.5rem 0;
}
</style>
""", unsafe_allow_html=True)

# ── Parsery ───────────────────────────────────────────────────────────────────

def normalize_dms(s):
    """Normalizuje warianty znaków stopni/minut/sekund do kanonicznych."""
    s = re.sub(r'[º˚∘]', '°', s)   # º ˚ ∘ → °
    s = re.sub(r'[ʹ′‘’]', "'", s) # ʹ ′ ' ' → '
    s = re.sub(r'[ʺ″“”]', '"', s) # ʺ ″ " " → "
    s = re.sub(r'  +', ' ', s)
    return s

def parse_dms(s):
    """Parsuje DMS — obsługuje º/°, spacje, etykiety dł./szer./lon/lat,
    literę kierunkową przed lub po, dowolną kolejność lat/lon."""
    s = normalize_dms(s)
    LON_LABELS = re.compile(r'dł[^°]*?:|lon(?:gitude)?\s*:', re.I)
    LAT_LABELS = re.compile(r'sz(?:er)?[^°]*?:|lat(?:itude)?\s*:', re.I)

    num_tok = re.compile(
        r'([NSEWnsew])?\s*(\d{1,3})\s*°\s*(\d{1,2})\s*\'\s*([\d.]+)\s*"?'
    )
    # Litery kierunkowe: standalone (nie część skrótu kończącego się :)
    dir_chars = [
        (m.start(), m.group().upper())
        for m in re.finditer(r'(?<![A-Za-z:])[NSEWnsew](?![A-Za-z\d])', s)
    ]

    tokens = list(num_tok.finditer(s))
    if len(tokens) < 2:
        return None

    parsed = []
    for m in tokens:
        h_inline = (m.group(1) or '').upper()
        deg, mins, secs = m.group(2), m.group(3), m.group(4)
        tok_start, tok_end = m.start(), m.end()
        h = h_inline
        if not h:
            for pos, ch in dir_chars:
                if tok_start - 2 <= pos < tok_start:
                    h = ch; break
            if not h:
                for pos, ch in dir_chars:
                    if tok_end <= pos <= tok_end + 2:
                        h = ch; break
        val = int(deg) + int(mins)/60 + float(secs)/3600
        parsed.append({'val': val, 'h': h, 'pos': tok_start})

    def label_before(pos):
        prefix = s[:pos]
        if LON_LABELS.search(prefix): return 'lon'
        if LAT_LABELS.search(prefix): return 'lat'
        return None

    t0, t1 = parsed[0], parsed[1]
    l0, l1 = label_before(t0['pos']), label_before(t1['pos'])

    if   l0 == 'lon' and l1 == 'lat': lon_t, lat_t = t0, t1
    elif l0 == 'lat' and l1 == 'lon': lat_t, lon_t = t0, t1
    elif l0 == 'lon' or  l1 == 'lat': lon_t, lat_t = t0, t1
    elif l0 == 'lat' or  l1 == 'lon': lat_t, lon_t = t0, t1
    else:
        h0_lat = t0['h'] in ('N','S'); h0_lon = t0['h'] in ('E','W')
        h1_lat = t1['h'] in ('N','S'); h1_lon = t1['h'] in ('E','W')
        if   h0_lat and h1_lon: lat_t, lon_t = t0, t1
        elif h0_lon and h1_lat: lon_t, lat_t = t0, t1
        elif h0_lat:            lat_t, lon_t = t0, t1
        elif h1_lat:            lon_t, lat_t = t0, t1
        elif h0_lon:            lon_t, lat_t = t0, t1
        elif h1_lon:            lat_t, lon_t = t0, t1
        else:                   lat_t, lon_t = t0, t1

    lat = lat_t['val'] * (-1 if lat_t['h'] == 'S' else 1)
    lon = lon_t['val'] * (-1 if lon_t['h'] == 'W' else 1)
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None
def parse_ddm(s):
    """Parsuje DDM: 52°30.258'N 18°20.456'E"""
    pat = (
        r"(\d{1,3})[°\s]"
        r"([\d.]+)[\'′\s]?"
        r"\s*([NSns])"
        r"[\s,;]+"
        r"(\d{1,3})[°\s]"
        r"([\d.]+)[\'′\s]?"
        r"\s*([EWew])"
    )
    m = re.search(pat, s)
    if not m:
        return None
    d1,m1,h1, d2,m2,h2 = m.groups()
    lat = int(d1) + float(m1)/60
    lon = int(d2) + float(m2)/60
    if h1.upper() == 'S': lat = -lat
    if h2.upper() == 'W': lon = -lon
    return lat, lon

def parse_dd(s):
    """Parsuje DD: 52.1234, 18.5678  lub z N/S/E/W"""
    # z literami kierunkowymi
    pat_dir = r"([NSns])?\s*([\d.]+)\s*[NSns]?\s*[,;\s]+\s*([EWew])?\s*([\d.]+)\s*[EWew]?"
    m = re.search(pat_dir, s)
    if m:
        h1, lat_s, h2, lon_s = m.groups()
        # wykryj litery z oryginału
        lat = float(lat_s)
        lon = float(lon_s)
        if 'S' in s.upper()[:s.upper().find(lon_s)]: lat = -lat
        if 'W' in s.upper(): lon = -lon
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon

    # czyste liczby
    nums = re.findall(r"[-+]?\d+\.?\d*", s)
    if len(nums) >= 2:
        lat, lon = float(nums[0]), float(nums[1])
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    return None

def parse_utm(s):
    """Parsuje UTM: 33U 500000 5800000 lub 33U500000 5800000"""
    pat = r"(\d{1,2})([A-Za-z])\s+(\d{5,7})\s+(\d{5,7})"
    m = re.search(pat, s.strip())
    if not m:
        return None
    zone_num, zone_let, easting, northing = m.groups()
    zone_num = int(zone_num)
    hemisphere = 'north' if zone_let.upper() >= 'N' else 'south'
    proj_str = f"+proj=utm +zone={zone_num} +{'north' if hemisphere=='north' else 'south'} +datum=WGS84"
    try:
        transformer = Transformer.from_crs(
            f"+proj=utm +zone={zone_num} +{'north' if hemisphere=='north' else 'south'} +datum=WGS84",
            "EPSG:4326",
            always_xy=True
        )
        lon, lat = transformer.transform(float(easting), float(northing))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    except Exception:
        pass
    return None

def parse_mgrs(s):
    """Parsuje MGRS: 33UXT5000080000"""
    if not MGRS_AVAILABLE:
        return None
    s_clean = re.sub(r'\s+', '', s.strip()).upper()
    # wyodrębnij potencjalny string MGRS
    pat = r"(\d{1,2}[A-Z]{3}\d{5,10})"
    m = re.search(pat, s_clean)
    if not m:
        return None
    try:
        m_obj = mgrs_lib.MGRS()
        lat, lon = m_obj.toLatLon(m.group(1))
        return float(lat), float(lon)
    except Exception:
        return None

# ── Autodetect ────────────────────────────────────────────────────────────────

FORMAT_NAMES = {
    'DMS': 'DMS',
    'DDM': 'DDM',
    'DD':  'DD',
    'UTM': 'UTM',
    'MGRS': 'MGRS',
}

def detect_and_parse(line):
    """Zwraca (lat, lon, format_name) lub (None, None, 'błąd')."""
    s = line.strip()
    if not s:
        return None, None, None  # pusta linia

    # MGRS — przed UTM (zawiera litery)
    if MGRS_AVAILABLE and re.search(r'\d{1,2}[A-Z]{3}\d{4,}', s.upper()):
        r = parse_mgrs(s)
        if r: return r[0], r[1], 'MGRS'

    # UTM
    if re.search(r'\d{1,2}[A-Za-z]\s+\d{5,7}\s+\d{5,7}', s):
        r = parse_utm(s)
        if r: return r[0], r[1], 'UTM'

    # DMS — obecność stopni i sekund
    if re.search(r'\d+[°\s]\d+[\'′]\s*[\d.]+[\"″]', s):
        r = parse_dms(s)
        if r: return r[0], r[1], 'DMS'

    # DDM — stopnie i minuty dziesiętne
    if re.search(r'\d+[°\s][\d.]+[\'′]?\s*[NSns]', s):
        r = parse_ddm(s)
        if r: return r[0], r[1], 'DDM'

    # DD — fallback
    r = parse_dd(s)
    if r: return r[0], r[1], 'DD'

    return None, None, '?'

# ── Formatowanie wyniku DD ────────────────────────────────────────────────────

def format_dd(lat, lon, precision, separator):
    fmt = f"{{:.{precision}f}}"
    lat_s = fmt.format(lat)
    lon_s = fmt.format(lon)
    return f"{lat_s}{separator}{lon_s}"

# ── Przetwarzanie listy linii ─────────────────────────────────────────────────

def process_lines(lines, precision, separator):
    results = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        lat, lon, fmt = detect_and_parse(raw)
        if lat is not None:
            dd = format_dd(lat, lon, precision, separator)
            results.append({
                'wejście': raw,
                'format': fmt,
                'wynik_dd': dd,
                'lat': lat,
                'lon': lon,
                'ok': True,
            })
        else:
            results.append({
                'wejście': raw,
                'format': '?',
                'wynik_dd': '—',
                'lat': None,
                'lon': None,
                'ok': False,
            })
    return results

# ── Renderowanie tabeli ───────────────────────────────────────────────────────

def render_table(results):
    rows = ""
    for r in results:
        badge = f'<span class="format-badge">{r["format"]}</span>'
        if r['ok']:
            rows += f"""
            <tr>
                <td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                    title="{r['wejście']}">{r['wejście']}</td>
                <td>{badge}</td>
                <td class="ok">{r['wynik_dd']}</td>
            </tr>"""
        else:
            rows += f"""
            <tr>
                <td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                    title="{r['wejście']}">{r['wejście']}</td>
                <td>{badge}</td>
                <td class="err">⚠ nierozpoznany format</td>
            </tr>"""

    html = f"""
    <table class="result-table">
        <thead>
            <tr>
                <th>Wejście</th>
                <th>Format</th>
                <th>DD (wynik)</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
    """
    st.markdown(html, unsafe_allow_html=True)

def results_to_gpx(results):
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<gpx version="1.1" creator="Konwerter Współrzędnych"')
    lines.append('  xmlns="http://www.topografix.com/GPX/1/1"')
    lines.append('  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"')
    lines.append('  xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd">')
    for r in results:
        if not r['ok']:
            continue
        lat = f"{r['lat']:.8f}"
        lon = f"{r['lon']:.8f}"
        name = (r['wejście']
            .replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))
        lines.append(f'  <wpt lat="{lat}" lon="{lon}">')
        lines.append(f'    <name>{name}</name>')
        lines.append(f'    <desc>Format: {r["format"]}</desc>')
        lines.append( '  </wpt>')
    lines.append('</gpx>')
    return '\n'.join(lines).encode('utf-8')

# ── UI ────────────────────────────────────────────────────────────────────────

st.markdown(
    '<div class="main-title" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">🌐 Konwerter Współrzędnych</div>',
    unsafe_allow_html=True
)
st.markdown('<div class="subtitle">DMS · DDM · DD · UTM · MGRS  →  DD</div>', unsafe_allow_html=True)

# Ustawienia
col1, col2 = st.columns(2)
with col1:
    precision = st.selectbox("Precyzja (miejsca po przecinku)", [4, 5, 6, 7, 8], index=2)
with col2:
    sep_label = st.selectbox("Separator", ["spacja  (   )", "przecinek  ( , )", "średnik  ( ; )"], index=0)

sep_map = {
    "spacja  (   )": " ",
    "przecinek  ( , )": ", ",
    "średnik  ( ; )": "; ",
}
separator = sep_map[sep_label]

st.markdown('<hr class="divider">', unsafe_allow_html=True)

# Zakładki
tab1, tab2 = st.tabs(["📋  Wklej tekst", "📂  Wczytaj plik"])

def show_results(results):
    only_ok = [r['wynik_dd'] for r in results if r['ok']]
    ok_count = len(only_ok)
    err_count = len(results) - ok_count

    # Wyniki DD — natychmiast do skopiowania
    if only_ok:
        st.code("\n".join(only_ok), language=None)

    # Statystyki
    st.markdown(
        f'<div class="stat-box">Przetworzono: <span>{len(results)}</span> '
        f'&nbsp;·&nbsp; OK: <span>{ok_count}</span> '
        f'&nbsp;·&nbsp; Błędy: <span style="color:{"#e07070" if err_count else "#7dd3a8"}">{err_count}</span></div>',
        unsafe_allow_html=True
    )

    # Szczegółowa tabela
    render_table(results)

    # Pobierz GPX
    gpx_data = results_to_gpx(results)
    st.download_button(
        label="⬇ Pobierz GPX",
        data=gpx_data,
        file_name="wspolrzedne.gpx",
        mime="application/gpx+xml",
        use_container_width=True,
    )

# ── Zakładka 1: wklej tekst ───────────────────────────────────────────────────
with tab1:
    example = (
        "52°30'15\"N 18°20'10\"E\n"
        "52°30.258'N 18°20.456'E\n"
        "52.504167, 18.336111\n"
        "33U 500000 5800000\n"
    )
    if MGRS_AVAILABLE:
        example += "33UXT5000080000\n"

    text_input = st.text_area(
        "Wklej współrzędne (jedna linia = jeden punkt):",
        height=145,
        placeholder=example,
        label_visibility="visible",
    )

    if st.button("Konwertuj", key="btn_text", use_container_width=True):
        if text_input.strip():
            lines = text_input.splitlines()
            results = process_lines(lines, precision, separator)
            show_results(results)
        else:
            st.warning("Wklej jakieś współrzędne.")

# ── Zakładka 2: plik ──────────────────────────────────────────────────────────
with tab2:
    uploaded = st.file_uploader(
        "Przeciągnij lub wybierz plik .txt / .csv",
        type=["txt", "csv"],
        label_visibility="visible",
    )

    if uploaded is not None:
        try:
            content = uploaded.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            content = uploaded.read().decode("latin-1")

        lines = content.splitlines()
        st.markdown(f'<div class="stat-box">Wczytano plik: <span>{uploaded.name}</span> &nbsp;·&nbsp; Linii: <span>{len([l for l in lines if l.strip()])}</span></div>', unsafe_allow_html=True)

        if st.button("Konwertuj plik", key="btn_file", use_container_width=True):
            results = process_lines(lines, precision, separator)
            show_results(results)

# ── Stopka ────────────────────────────────────────────────────────────────────
st.markdown('<hr class="divider">', unsafe_allow_html=True)
if not MGRS_AVAILABLE:
    st.caption("ℹ️ Obsługa MGRS niedostępna — zainstaluj: `pip install mgrs`")
st.caption("Konwerter Współrzędnych · pyproj + Streamlit")
