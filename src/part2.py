"""
Part 2 – Scraping de fuente oficial
Cámara de Diputadas y Diputados de Chile
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import time

from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
SEED_FILE = ROOT / "seed_urls.txt"
OUT_DIR = ROOT / "outputs" / "part2"
RAW_DIR = OUT_DIR / "raw"

OUT_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)

PROJECTS_JSONL = OUT_DIR / "projects.jsonl"
EVENTS_JSONL = OUT_DIR / "events.jsonl"
REPORT_JSON = OUT_DIR / "scrape_report.json"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RATE_LIMIT_SECONDS = 1.0   # mínimo 1 req/s
TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0        # multiplicador exponencial

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; CamaraChileScraper/1.0; "
        "+https://github.com/academic-research)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.5",
}

BASE_URL = "https://www.camara.cl"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _build_request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers=HEADERS)


def fetch_html(url: str) -> tuple[str, int]:
    """
    Descarga el HTML de *url* con reintentos y backoff exponencial.
    Retorna (html_text, http_status_code).
    Lanza excepción si todos los intentos fallan.
    """
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = _build_request(url)
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                html = resp.read().decode("utf-8", errors="replace")
                return html, resp.status
        except urllib.error.HTTPError as exc:
            last_exc = exc
            log.warning("Intento %d/%d – HTTP %s para %s", attempt, MAX_RETRIES, exc.code, url)
            if exc.code in (404, 410):
                raise  # no tiene sentido reintentar
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            log.warning("Intento %d/%d – Error de red para %s: %s", attempt, MAX_RETRIES, url, exc)

        if attempt < MAX_RETRIES:
            sleep_time = RETRY_BACKOFF ** attempt
            log.info("Esperando %.1f s antes de reintentar…", sleep_time)
            time.sleep(sleep_time)

    raise RuntimeError(f"Fallaron {MAX_RETRIES} intentos para {url}") from last_exc


# ---------------------------------------------------------------------------
# URL / bulletin helpers
# ---------------------------------------------------------------------------

def extract_bulletin(url: str) -> str:
    """Extrae el número de boletín desde los query params de la URL."""
    qs = parse_qs(urlparse(url).query)
    for key in qs:
        if key.lower() == "prmboletin":
            return qs[key][0].strip()
    return ""


def safe_filename(url: str) -> str:
    """Genera un nombre de archivo seguro a partir de la URL."""
    bulletin = extract_bulletin(url)
    if bulletin:
        return re.sub(r"[^\w\-]", "_", bulletin) + ".html"
    # fallback: usar la query string completa
    safe = re.sub(r"[^\w\-]", "_", urlparse(url).query)
    return safe[:80] + ".html"


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _text(tag: Any) -> str:
    """Devuelve texto limpio de un tag BeautifulSoup o '' si es None."""
    if tag is None:
        return ""
    return " ".join(tag.get_text(" ", strip=True).split())


def _find_meta(soup: BeautifulSoup, label_re: str) -> str:
    """
    Busca en la página un texto que coincida con *label_re* y devuelve
    el texto del siguiente elemento hermano o td/span adyacente.
    """
    pattern = re.compile(label_re, re.IGNORECASE)
    el = soup.find(string=pattern)
    if el is None:
        return ""
    parent = el.parent
    # buscar el siguiente sibling con contenido
    for sib in parent.next_siblings:
        txt = _text(sib) if hasattr(sib, "get_text") else str(sib).strip()
        if txt:
            return txt
    # a veces el valor está en el padre siguiente
    next_p = parent.find_next_sibling()
    return _text(next_p) if next_p else ""


def _find_label_value(soup: BeautifulSoup, label_text: str) -> str:
    """
    Busca etiquetas <td>, <th>, <span>, <label>, <strong> que contengan
    *label_text* y retorna el texto del siguiente elemento.
    """
    for tag in soup.find_all(["td", "th", "span", "label", "strong", "b", "dt"]):
        txt = tag.get_text(strip=True)
        if label_text.lower() in txt.lower():
            # siguiente td hermano
            nxt = tag.find_next_sibling(["td", "dd", "span"])
            if nxt:
                return _text(nxt)
            # o el padre siguiente
            nxt2 = tag.parent.find_next_sibling()
            if nxt2:
                return _text(nxt2)
    return ""


def scrape_all_events_with_selenium(url: str):
    options = Options()
    options.add_argument("--headless=new")  # modo invisible (nuevo Chrome)
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")

    driver = webdriver.Chrome(options=options)
    driver.get(url)

    all_events = []
    page = 1

    while True:
        time.sleep(2)

        html = driver.page_source
        soup = BeautifulSoup(html, "lxml")

        events = parse_events(soup, url)
        all_events.extend(events)

        print(f"Página {page} → {len(events)} eventos")

        try:
            next_btn = driver.find_element(By.LINK_TEXT, str(page + 1))
            next_btn.click()
            page += 1
        except:
            break

    driver.quit()
    return all_events
# ---------------------------------------------------------------------------
# Main parsers
# ---------------------------------------------------------------------------

def parse_project(soup: BeautifulSoup, seed_url: str) -> dict[str, Any]:
    """
    Extrae metadata del proyecto desde el HTML de la página de tramitación.
    Intenta múltiples estrategias de extracción para cubrir variaciones del sitio.
    """
    bulletin = extract_bulletin(seed_url)

    # --- título ---
    title = ""
    for selector in [
        "h1", "h2", "h3",
        "#ContentPlaceHolder1_lbTitulo",
        ".titulo-proyecto", ".proyecto-titulo",
    ]:
        el = soup.select_one(selector)
        if el:
            title = _text(el)
            if title:
                break
    if not title:
        title = _find_label_value(soup, "Título")

    # --- detail_url: la URL canónica de la página (puede diferir del seed por case) ---
    detail_url = seed_url
    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        detail_url = urljoin(BASE_URL, canonical["href"])

    # --- campos estructurados ---
    def get(label: str) -> str:
        return _find_label_value(soup, label)

    # Intentar leer tabla de ficha resumen
    legislature = get("Legislatura") or get("Período")
    entry_date = get("Ingreso") or get("Fecha de ingreso") or get("Fecha Ingreso")
    status = get("Estado") or get("Situación")
    initiative = get("Iniciativa") or get("Tipo de Iniciativa") or get("Tipo iniciativa")
    origin_chamber = get("Origen") or get("Cámara de Origen") or get("Cámara origen")

    # --- autores ---
    authors: list[str] = []
    # Buscar por id/clase conocidos
    for sel in [
        "#ContentPlaceHolder1_lbAutores",
        ".autores", ".proyecto-autores",
        "#autores",
    ]:
        el = soup.select_one(sel)
        if el:
            authors = [a.strip() for a in re.split(r"[;,\n]", _text(el)) if a.strip()]
            break
    if not authors:
        raw = get("Autor") or get("Autores")
        if raw:
            authors = [a.strip() for a in re.split(r"[;,\n]", raw) if a.strip()]

    return {
        "seed_url": seed_url,
        "detail_url": detail_url,
        "bulletin_number": bulletin,
        "title": title,
        "legislature": legislature,
        "entry_date": entry_date,
        "status": status,
        "initiative": initiative,
        "origin_chamber": origin_chamber,
        "authors": authors,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def parse_events(soup: BeautifulSoup, seed_url: str) -> list[dict[str, Any]]:
    """
    Extrae la tabla de tramitación (historial de eventos) del HTML.
    Devuelve lista de dicts ordenados por row_order.
    """
    bulletin = extract_bulletin(seed_url)
    events: list[dict[str, Any]] = []

    # Buscar todas las tablas y elegir la que tiene más filas con datos de tramitación
    tables = soup.find_all("table")
    best_table = None
    best_score = 0

    date_re = re.compile(
    r"\d{1,2}/\d{1,2}/\d{4}|"          # 20/11/2019
    r"\d{4}-\d{2}-\d{2}|"              # 2019-11-20
    r"\d{1,2}\s+[A-Za-zÁÉÍÓÚáéíóú\.]+\s+\d{4}"  # 20 Nov. 2019
)

    for tbl in tables:
        rows = tbl.find_all("tr")
        score = sum(1 for r in rows if date_re.search(r.get_text()))
        if score > best_score:
            best_score = score
            best_table = tbl

    if best_table is None or best_score == 0:
        log.warning("No se encontró tabla de tramitación para %s", seed_url)
        return events

    rows = best_table.find_all("tr")
    row_order = 0

    for tr in rows:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        texts = [_text(c) for c in cells]

        # Heurística: la fila tiene datos útiles si hay al menos una fecha
        has_date = any(date_re.search(t) for t in texts)
        is_header = all(c.name == "th" for c in cells)
        if is_header:
            continue
        if not has_date and row_order == 0:
            continue  # primera fila sin fecha → posible cabecera disfrazada

        # Mapeo flexible de columnas (los índices varían entre páginas)
        # Buscamos fecha, sesión, tramitación/etapa, descripción, documento
        def col(idx: int) -> str:
            return texts[idx] if idx < len(texts) else ""

        # Detectar columna de fecha (primera celda con patrón de fecha)
        date_idx = next(
            (i for i, t in enumerate(texts) if date_re.search(t)), 0
        )

        event_date = col(date_idx)
        # Resto de columnas en orden relativo
        remaining = [t for i, t in enumerate(texts) if i != date_idx]

        session = remaining[0] if len(remaining) > 0 else ""
        stage = remaining[1] if len(remaining) > 1 else ""
        substage = remaining[2] if len(remaining) > 2 else ""
        description = remaining[3] if len(remaining) > 3 else ""

        # Buscar URL de documento en la fila
        doc_url = ""
        for a in tr.find_all("a", href=True):
            href = a["href"].strip()
            if href and href != "#":
                doc_url = urljoin(BASE_URL, href)
                break

        if not event_date:
            continue

        events.append({
            "seed_url": seed_url,
            "bulletin_number": bulletin,
            "row_order": row_order,
            "event_date": event_date,
            "session": session,
            "stage": stage,
            "substage": substage,
            "description": description,
            "document_url": doc_url,
        })
        row_order += 1

    return events


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def scrape_url(seed_url: str) -> dict[str, Any]:
    """
    Procesa una URL semilla completa: descarga, guarda, parsea.
    Retorna el reporte de esta URL.
    """
    report: dict[str, Any] = {
        "seed_url": seed_url,
        "fetch_ok": False,
        "parse_ok": False,
        "http_status": None,
        "row_count": 0,
        "error_message": None,
    }

    # ---- Fetch ----
    html = ""
    try:
        html, status = fetch_html(seed_url)
        report["http_status"] = status
        report["fetch_ok"] = True
        log.info("✓ Descargado %s (HTTP %s)", seed_url, status)
    except urllib.error.HTTPError as exc:
        report["http_status"] = exc.code
        report["error_message"] = f"HTTPError {exc.code}: {exc.reason}"
        log.error("✗ %s → %s", seed_url, report["error_message"])
        return report
    except Exception as exc:
        report["error_message"] = str(exc)
        log.error("✗ %s → %s", seed_url, exc)
        return report

    # ---- Guardar HTML crudo ----
    fname = safe_filename(seed_url)
    raw_path = RAW_DIR / fname
    raw_path.write_text(html, encoding="utf-8")
    log.info("  HTML guardado → %s", raw_path.name)

    # ---- Parse ----
    try:
        soup = BeautifulSoup(html, "lxml")

        project = parse_project(soup, seed_url)
        events = scrape_all_events_with_selenium(seed_url)

        # Escribir projects.jsonl (append)
        with PROJECTS_JSONL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(project, ensure_ascii=False) + "\n")

        # Escribir events.jsonl (append)
        with EVENTS_JSONL.open("a", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")

        report["parse_ok"] = True
        report["row_count"] = len(events)
        log.info(
            "  Proyecto: '%s…' | Eventos extraídos: %d",
            (project["title"] or "sin título")[:60],
            len(events),
        )
    except Exception as exc:
        report["error_message"] = f"Parse error: {exc}"
        log.error("  Error al parsear %s: %s", seed_url, exc)

    return report


def main() -> None:
    # Limpiar salidas previas
    for f in [PROJECTS_JSONL, EVENTS_JSONL]:
        f.unlink(missing_ok=True)

    # Leer URLs
    urls = [
        line.strip()
        for line in SEED_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    log.info("=== Parte 2: scraping %d URLs ===", len(urls))

    reports: list[dict[str, Any]] = []
    last_request_time = 0.0

    for i, url in enumerate(urls, 1):
        log.info("--- [%d/%d] %s", i, len(urls), url)

        # Rate limiting: esperar si la última request fue hace menos de RATE_LIMIT_SECONDS
        elapsed = time.monotonic() - last_request_time
        if elapsed < RATE_LIMIT_SECONDS:
            time.sleep(RATE_LIMIT_SECONDS - elapsed)

        last_request_time = time.monotonic()

        report = scrape_url(url)
        reports.append(report)

        # Respetar rate limit también después de procesar
        # (ya controlado arriba, pero dejamos un mínimo entre iteraciones)

    # Escribir reporte
    REPORT_JSON.write_text(
        json.dumps(reports, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Resumen
    ok = sum(1 for r in reports if r["fetch_ok"] and r["parse_ok"])
    total_events = sum(r["row_count"] for r in reports)
    log.info(
        "=== Finalizado: %d/%d URLs OK | %d eventos totales ===",
        ok, len(urls), total_events,
    )
    log.info("Salidas:")
    log.info("  %s", PROJECTS_JSONL)
    log.info("  %s", EVENTS_JSONL)
    log.info("  %s", REPORT_JSON)
    log.info("  %s/*.html", RAW_DIR)


if __name__ == "__main__":
    main()
