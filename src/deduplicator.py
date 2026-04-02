"""
deduplicator.py
---------------
Duplicate detection and canonical record selection.

Rules (applied in order):
  (a) Same normalized URL
  (b) Same bulletin_number + same normalized title  (when no URL)
  (c) Same content_hash_hint + same normalized title (when no bulletin)

Canonical selection priority:
  1. Most non-empty relevant fields
  2. source_type order: detail > table > api > news > misc (others last)
  3. Most recent date (published_at or event_date)
  4. record_id lexicographically smallest
"""

from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Ranking de tipos de Source Type mas relevantes, partiendo desde detail mas importante
SOURCE_TYPE_RANK: dict[str, int] = {
    "detail": 0,
    "table": 1,
    "api": 2,
    "news": 3,
    "misc": 4,
}
_DEFAULT_SOURCE_RANK = 99

# Campos que se cuenta en "richness" (contador campos no vacios)
RELEVANT_FIELDS = [
    "canonical_url", "canonical_document_url",
    "title", "bulletin_number", "summary", "authors","published_at",
    "event_date", "status", "initiative",
]

# Cuenta los campos relevantes no vacíos en una fila.
def _richness(row: pd.Series) -> int:
    return sum(1 for f in RELEVANT_FIELDS if str(row.get(f, "")).strip())

# Obtiene el ranking del tipo de source_type que existe en esta fila
def _source_rank(row: pd.Series) -> int:
    st = str(row.get("source_type", "")).strip().lower()
    return SOURCE_TYPE_RANK.get(st, _DEFAULT_SOURCE_RANK)

# Devuelve la fecha más reciente entre published_at y event_date, o devuelve''.
def _best_date(row: pd.Series) -> str:
    dates = [str(row.get("published_at", "")).strip(),
             str(row.get("event_date", "")).strip()]
    dates = [d for d in dates if d]
    return max(dates) if dates else ""

# Dado un DataFrame de grupo (duplicados), devuelve el record_id del canónico.

# Prioridad de ordenación:

# 1. Richness DESC (cuantos más campos no vacíos, mejor)
# 2. Source_type ASC (menor número de rango = mayor calidad de la fuente)
# 3. Best_date DESC (cuanto más reciente la fecha, mejor)
# 4. Record_id ASC (lexicográficamente menor como criterio de desempate final)
def _select_canonical(group: pd.DataFrame) -> str:
    # Copia el Dataframe
    scored = group.copy()
    # Calcula que tan completo es el registro (en cuanto a campos relevantes no vacios)
    scored["_richness"] = scored.apply(_richness, axis=1)
    # Calcula el ranking dependiendo del tipo de Source_type que tiene este registro
    scored["_src_rank"] = scored.apply(_source_rank, axis=1)
    # Extrae la mejor fecha disponible del registro
    scored["_best_date"] = scored.apply(_best_date, axis=1)
    # Ordena por el orden de prioridad: 
    # richness alto→bajo, src_rank bajo→alto, date alto→bajo, record_id bajo→alto
    scored = scored.sort_values(
        by=["_richness", "_src_rank", "_best_date", "record_id"],
        ascending=[False, True, False, True],
    )
    return str(scored.iloc[0]["record_id"])

# Crea un ID de grupo determinista a partir de una key de duplicacion.
def _stable_group_id(key: str) -> str:
    return "GRP-" + hashlib.md5(key.encode("utf-8")).hexdigest()[:12].upper()


# Agrupa Registros duplicados y se queda con el original:
# - duplicate_group_id: identificador de grupo de duplicados
# - is_canonical: booleano, True para el registro conservado
#   Devuelve un nuevo DataFrame con estas columnas adicionales.
#   NO modifica la entrada.
def assign_duplicate_groups(df: pd.DataFrame) -> pd.DataFrame:
    # Se copia el DataFrame
    df = df.copy()

    # Inicializacion
    n = len(df)
    # Lista con todos elementos False
    is_canonical = [False] * n

    # Aquí se agrupan posibles duplicados según:
    # URL
    # bulletin + title
    # hash + title
    url_groups: dict[str, list[int]] = {}
    bulletin_title_groups: dict[str, list[int]] = {}
    hash_title_groups: dict[str, list[int]] = {}

    # Recorre las filas del DataFrame
    for i, row in df.iterrows():
        # Se extraen los campos
        url = str(row.get("canonical_url", "")).strip()
        bulletin = str(row.get("bulletin_number", "")).strip()
        title = str(row.get("title", "")).strip().lower()
        content_hash = str(row.get("content_hash_hint", "")).strip()

        # Si existe URL:
        if url:
            # Si no existe URL en el diccionario, lo crea y agrega el indice y si
            # existe la URL, solo agrego el indice nuevo al diccionario
            if url not in url_groups:
                url_groups[url] = []
            url_groups[url].append(i)
        # En caso que no exista URL:
        # Si no existe la llave 'Bulletin Number||title' en el diccionario, lo crea y agrega
        # el indice y si ya existe, solo agrego el indice nuevo al diccionario    
        elif bulletin and title:
            key = f"{bulletin}||{title}"
            if key not in bulletin_title_groups:
                bulletin_title_groups[key] = []
            
            bulletin_title_groups[key].append(i)
        # En caso que no exista Bulletin Number:
        # Si no existe la llave 'content_hash||title' en el diccionario, lo crea y agrega
        # el indice y si ya existe, solo agrego el indice nuevo al diccionario  
        elif content_hash and title:
            key = f"{content_hash}||{title}"
            if key not in hash_title_groups:
                hash_title_groups[key] = []
            
            hash_title_groups[key].append(i)

    # Diccionario de asignación
    assigned: dict[int, str] = {}  # indice → group_id
    
    # Funcion interna que procesa cada tipo de grupo
    def process_groups(groups_dict: dict[str, list[int]], prefix: str) -> None:
        # Iteramos por el diccionario de grupo
        for key, indices in groups_dict.items():
            # Si el largo de indices es < 2, se ignora ya que es registro unico
            if len(indices) < 2:
                continue
            
            # Crea ID de grupo
            gid = _stable_group_id(f"{prefix}:{key}")
            # Obtengo las filas del grupo
            sub_df = df.loc[indices]
            # Decide cual registro se queda
            canonical_rid = _select_canonical(sub_df)

            # Marca registros, todo reciben el mismo GROUP ID
            for i in indices:
                assigned[i] = gid
                # Solo uno queda como True
                is_canonical[i] = (str(df.loc[i, "record_id"]) == canonical_rid)

    # Ejecuta lasagrupaciones
    process_groups(url_groups, "url")
    process_groups(bulletin_title_groups, "bt")
    process_groups(hash_title_groups, "ht")

    # Asignar identificadores de grupo únicos a los registros individuales 
    # (que no forman parte de ningún grupo de múltiples registros)
    for i in range(n):
        actual_i = df.index[i]
        # Si no pertence a ningun grupo
        if actual_i not in assigned:
            # Crea grupo único
            rid = str(df.iloc[i]["record_id"])
            # Se crea un GROUP ID propio para este registro
            assigned[actual_i] = _stable_group_id(f"singleton:{rid}")
            # Es automaticamente canonico
            is_canonical[i] = True

    # Se crean columnas Finales
    # Asigna GROUP ID a cada fila
    df["duplicate_group_id"] = [assigned[df.index[i]] for i in range(n)]
    # Asigna True/False dependiendo si es canonico
    df["is_canonical"] = is_canonical

    return df

# Crea el contenido de duplicate_clusters.csv a partir de un DataFrame que ya contiene las
# columnas duplicate_group_id e is_canonical.
# Devuelve un DataFrame con las columnas:
# duplicate_group_id, record_id, is_kept, duplicate_reason
def build_duplicate_clusters(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    # Se recorre el dataFrame
    for _, row in df.iterrows():

        # Extraer datos para crear el nuevo CSV
        gid = row["duplicate_group_id"]
        rid = row["record_id"]
        is_kept = bool(row["is_canonical"])

        # Extraer campos para decidir motivo de duplicado
        url = str(row.get("canonical_url", "")).strip()
        bulletin = str(row.get("bulletin_number", "")).strip()
        title = str(row.get("title", "")).strip()
        content_hash = str(row.get("content_hash_hint", "")).strip()

        # Razon de duplicado
        if url:
            reason = "same_url"
        elif bulletin and title:
            reason = "same_bulletin_and_title"
        elif content_hash and title:
            reason = "same_hash_and_title"
        else:
            reason = "unique"
        
        # Guardar la fila
        rows.append({
            "duplicate_group_id": gid,
            "record_id": rid,
            "is_kept": is_kept,
            "duplicate_reason": reason,
        })

    return pd.DataFrame(rows)
