"""
normalizers.py
--------------
Funciones de normalización puras y sin estado.
Cada función recibe una cadena de texto sin procesar (o None) y devuelve un valor limpio.
Todas las funciones son deterministas y no producen efectos secundarios.
"""

from __future__ import annotations

import json
import re
from html import unescape
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser
from dateutil.parser import ParserError


# ---------------------------------------------------------------------------
# Campos de Texto normalización
# ---------------------------------------------------------------------------

# Normalizar campos de texto (title, summary):
#    - Elimina espacios en blanco iniciales y finales
#    - Decodifica entidades HTML (&amp; → &, etc.)
#    - Eliminar etiquetas HTML en el caso que sea necesario (mediante BeautifulSoup)
#    - Reducir los espacios en blanco internos (espacios, tabulaciones, saltos de línea) a un solo espacio
#    - Devuelve una cadena vacía cuando la entrada es nula/vacía.

def normalize_text(raw: Optional[str]) -> str:
    if not raw or not isinstance(raw, str):
        return ""
    # Elimina las etiquetas HTML en el caso que fuera necesario con BeautifulSoup (esto también decodifica las entidades
    # HTML dentro de las etiquetas),
    # Luego, descodifica las entidades HTML restantes que no estaban dentro de etiquetas
    text = unescape(BeautifulSoup(raw, "html.parser").get_text(separator=" "))
    # Colapsa cualquier secuencia de espacios en blanco (incluyendo \n \t \r) en un solo espacio y 
    # quita los espacios en blanco al final e inicio de la secuencia
    text = re.sub(r"[ \t\r\n]+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Bulletin number normalizacion
# ---------------------------------------------------------------------------

# Boletín: parte principal de 5 dígitos, separador opcional, sufijo de 2 dígitos
# Ejemplos reales: "11422-07", "1526125" (sin guion), "17000-XX" (sufijo no numérico → inválido)

# Patrón que captura 5 digitos seguidos, luego captura cualquier cosa que NO sea letra ni número
# (espacios, guiones, /, etc.) y luego captura exactamente 2 dígitos (el sufijo)
_BULLETIN_RE = re.compile(r"(^\d{5})[^0-9A-Za-z]*(\d{2})$")

# Patrón que captura 5 digitos seguidos, luego captura el guión, y finalmente captura
# otros dos digitos (el sufijo)
_BULLETIN_CANONICAL_RE = re.compile(r"^\d{5}-\d{2}$")

# Normaliza bulletin_number al formato canónico NNNNNN-## (5 dígitos, guion, 2 dígitos).
# Acepta variaciones como "11422-07", "1142207", "11422/07", " 11422 - 07 ".
# Si el sufijo no es numérico (ej: "17000-XX") o no puede extraerse, retorna vacío.
def normalize_bulletin_number(raw: Optional[str]) -> str:
    if not raw or not isinstance(raw, str):
        return ""
    raw = raw.strip()
    if _BULLETIN_CANONICAL_RE.match(raw):
        return raw
    m = _BULLETIN_RE.search(raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return ""


# ---------------------------------------------------------------------------
# URL normalización
# ---------------------------------------------------------------------------

# Lista de Parametros de la URL que se van a Eliminar
_TRACKING_PARAMS = frozenset({"utm_source", "utm_medium", "utm_campaign",
                               "utm_term", "utm_content", "gclid", "fbclid"})

# Normaliza una URL
# - Elimina espacios en blanco
# - Convierte el nombre del host a minúsculas
# - Elimina parámetros de consulta de seguimiento (utm_*, gclid, fbclid)
# - Elimina '/' final de la ruta
#   (p. ej., /docs/ → /docs, pero https://example.com/ → https://example.com)
#   Devuelve una cadena vacía si la entrada no se puede analizar.
def normalize_url(raw: Optional[str]) -> str:
    if not raw or not isinstance(raw, str):
        return ""
    # Elimina espacios en blanco al principio y al final
    raw = raw.strip()
    if not raw:
        return ""
    try:
        # Parsea la URL, la divide en partes como scheme → https, netloc → example.com, query → a=1 etc
        parsed = urlparse(raw)
    except Exception:
        return ""

    # Debe tener un scheme y netloc para ser una URL válida.
    if not parsed.scheme or not parsed.netloc:
        return ""
 
    # Convierte el nombre del host a minúsculas
    netloc = parsed.netloc.lower()

    # Filtra los tracking parameters
    if parsed.query:
        # Convierte la query de la URL en diccionario
        qs = parse_qs(parsed.query, keep_blank_values=True)
        # Recorre todos los parámetros y elimina los que están en _TRACKING_PARAMS
        filtered = {}
        for k, v in qs.items():
            if k.lower() not in _TRACKING_PARAMS:
                filtered[k] = v
        # Reconstruye la query string conservando el orden de valores original; ordenando las claves por inicial.
        new_query = urlencode(sorted(filtered.items()), doseq=True)
    else:
        new_query = ""

    # Elimina '/' final de la ruta.
    if parsed.path != "/":
        path = parsed.path.rstrip("/")
    else:
        path = ""
    # Se reconstruye la URL
    normalized = urlunparse((
        parsed.scheme,
        netloc,
        path,
        parsed.params,
        new_query,
        parsed.fragment
    ))
    return normalized


# ---------------------------------------------------------------------------
# Date normalización
# ---------------------------------------------------------------------------

# Patrón que evalua dos formatos distintos de fechas (sin hora), separados por '|' (OR)
# El primer formato busca patrones: YYYY-MM-DD o YYYY/MM/DD
# El segundo formato busca patrones: DD-MM-YYYY o DD/MM/YYYY
_DATE_ONLY_RE = re.compile(
    r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$"   
    r"|^\d{1,2}[-/]\d{1,2}[-/]\d{4}$"
)

# Patrón que evalua si el str contiene hora, exige que coexistan año (4 dígitos) y hora
# (HH:MM) en el mismo string
_DATETIME_RE = re.compile(r"\d{4}.*\d{1,2}:\d{2}|\d{1,2}:\d{2}.*\d{4}")

# Normaliza un string de fecha/hora.
#  - Si contiene información horaria → ISO 8601 con zona horaria (si está disponible),
#    de lo contrario, ISO 8601 simple (AAAA-MM-DDTHH:MM:SS)
#  - Si solo contiene la fecha → AAAA-MM-DD
#  - Si no se puede analizar de forma fiable → cadena vacía
#    Utiliza dateutil para un parseo mas flexible; dayfirst=False para priorizar la 
#    interpretación AAAA-MM-DD cuando haya ambigüedad.
def normalize_date(raw: Optional[str]) -> str:
    if not raw or not isinstance(raw, str):
        return ""
    # Elimina espacios al inicio y final
    raw = raw.strip()
    if not raw:
        return ""

    # Detecta si el valor sin procesar contiene hora o solo es fecha
    # Verificamos ANTES del análisis para decidir el formato de salida.
    has_time_hint = bool(re.search(r"\d{1,2}:\d{2}", raw))

    try:
        # Se parsea el str a formato Fecha -> datetime(...)
        dt = dateutil_parser.parse(raw, dayfirst=False)
    except (ParserError, OverflowError, ValueError):
        return ""

    if has_time_hint:
        if dt.tzinfo is not None:
            return dt.isoformat()
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    else:
        return dt.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Authors normalización
# ---------------------------------------------------------------------------

# Normaliza `authors_raw` a una cadena separada por ' | '.
# Admite:
# - Strings simples (un solo autor o CSV: "Alice, Bob")
# - JSON: '["Alice", "Bob"]'
# - Objetos JSON con una clave de nombre: '[{"name": "Alice"}, {"name": "Bob"}]'
# - Separados por barra vertical: "Alice | Bob"
# Elimina duplicados (sin distinción de mayúsculas y minúsculas), conservando el formato de la primera aparición.
# Devuelve una cadena vacía si no se encuentran autores válidos.
def normalize_authors(raw: Optional[str]) -> str:
    if not raw or not isinstance(raw, str):
        return ""
    # Elimina Espacios en blanco al inicio y final
    raw = raw.strip()
    if not raw:
        return ""
    # Se crea una lista donde se guardarán los autores
    authors: list[str] = []

    # Se intenta parsear como JSON primero
    if raw.startswith("[") or raw.startswith("{"):
        try:
            # Convierte string → objeto Python
            parsed = json.loads(raw)
            # Si el objetvo parseado es una lista, iteramos por cada elemento
            if isinstance(parsed, list):
                for item in parsed:
                    # Caso 1: String, ejemplo "juan"
                    if isinstance(item, str):
                        authors.append(item.strip())
                    # Caso 2: diccionario, ejemplo {"name": "Juan"}
                    elif isinstance(item, dict):
                        name = item.get("name") or item.get("author") or item.get("full_name", "")
                        if name:
                            authors.append(str(name).strip())
            # Si el objetvo parseado es un diccionario y no lista:                
            elif isinstance(parsed, dict):
                name = parsed.get("name") or parsed.get("author", "")
                if name:
                    authors.append(str(name).strip())
        except (json.JSONDecodeError, ValueError):
            pass
    # Si no se encontro autores en JSON
    if not authors:
        # Se prueba primero en el caso de separador: '/'
        if "|" in raw:
            authors = [a.strip() for a in raw.split("|")]
        # En segundo caso se prueba el separador: ';'    
        elif ";" in raw:
            authors = [a.strip() for a in raw.split(";")]
        # En tercer caso se prueba el separador: ','    
        elif "," in raw:
            authors = [a.strip() for a in raw.split(",")]
        # Si no:    
        else:
            authors = [raw.strip()]

    # Elimina duplicados exactos
    seen: set[str] = set()
    unique: list[str] = []
    for a in authors:
        if a and a.lower() not in seen:
            seen.add(a.lower())
            unique.append(a)

    return " | ".join(unique)