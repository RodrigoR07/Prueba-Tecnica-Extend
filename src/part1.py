"""
pipeline.py
-----------
Main al flujo de registros legislativos.

Uso:
    python run_pipeline.py legislative_records.csv [--output-dir ./output]

Columnas esperadas en CSV (scheme):
    record_id, source, source_type, bulletin_number, title_raw, summary_raw,
    published_at_raw, event_date_raw, status_raw, initiative_raw, authors_raw,
    url_raw, document_url_raw, scraped_at, html_snippet, content_hash_hint

Produce:
    normalized_records.csv
    rejected_records.csv
    duplicate_clusters.csv
    quality_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

try:
    from src.deduplicator import assign_duplicate_groups, build_duplicate_clusters
    from src.normalizers import (
        normalize_authors,
        normalize_bulletin_number,
        normalize_date,
        normalize_text,
        normalize_url,
    )
except ModuleNotFoundError:
    from deduplicator import assign_duplicate_groups, build_duplicate_clusters
    from normalizers import (
        normalize_authors,
        normalize_bulletin_number,
        normalize_date,
        normalize_text,
        normalize_url,
    )


# Columns that must exist in the CSV. If any are missing, fill them with empty space.
EXPECTED_COLUMNS = [
    "record_id", "source", "source_type", "bulletin_number",
    "title_raw", "summary_raw", "published_at_raw", "event_date_raw",
    "status_raw", "initiative_raw", "authors_raw",
    "url_raw", "document_url_raw", "scraped_at",
    "html_snippet", "content_hash_hint",
]

# Load the CSV.
def load_csv(path: Path) -> pd.DataFrame:
        try:
            df = pd.read_csv(path, dtype=str, encoding="utf-8", keep_default_na=False)
            for col in EXPECTED_COLUMNS:
                if col not in df.columns:
                    df[col] = ""
                else:
                    df[col] = df[col].fillna("").astype(str)
            return df
        
        except UnicodeDecodeError:
            raise ValueError(f"It could not be decoded {path}.")
    

# Aplica todas las normalizaciones y devuelve un diccionario limpio
def normalize_row(row: pd.Series) -> dict:
    return {
        "record_id":              row["record_id"],
        "source":                 row["source"],
        "source_type":            row["source_type"],
        "bulletin_number":        normalize_bulletin_number(row["bulletin_number"]),
        "title":                  normalize_text(row["title_raw"]),
        "summary":                normalize_text(row["summary_raw"]),
        "published_at":           normalize_date(row["published_at_raw"]),
        "event_date":             normalize_date(row["event_date_raw"]),
        "status":                 row["status_raw"],
        "initiative":             row["initiative_raw"],
        "authors":                normalize_authors(row["authors_raw"]),
        "canonical_url":          normalize_url(row["url_raw"]),
        "canonical_document_url": normalize_url(row["document_url_raw"]),
        "content_hash_hint":      row["content_hash_hint"],
        "html_snippet":           row["html_snippet"],
    }

# Retorna (es_valido, motivo_rechazo).
# Se rechaza si no tiene título utilizable O no tiene ningún identificador.
def validate_normalized(record: dict) -> tuple[bool, str]:
    # Verifica si hay titulo, si no hay devuelve False
    has_title    = bool(record.get("title", "").strip())
    # Verifica si hay URL, si no hay devuelve False
    has_url      = bool(record.get("canonical_url", "").strip())
    # Verifica si hay Bulletin Number, si no hay devuelve False
    has_bulletin = bool(record.get("bulletin_number", "").strip())
    # Verifica si hay Content_Hash_Hint, si no hay devuelve False
    has_hash     = bool(record.get("content_hash_hint", "").strip())
    
    # Debe tener titulo
    if not has_title:
        return False, "missing_title"
    # Debe tener al menos un identificador
    if not (has_url or has_bulletin or has_hash):
        return False, "missing_all_identifiers"
    return True, ""


def _raw_identifier_hint(record: dict) -> str:
    return (record.get("canonical_url")
            or record.get("bulletin_number")
            or record.get("content_hash_hint")
            or "")

# Funcion Principal que realiza la normalizacion y deduplicacion
def run_pipeline(input_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Cargar el CSV
    raw_df = load_csv(input_path)
    input_rows = len(raw_df)
    print(f"[pipeline] Cargadas {input_rows} filas desde {input_path.name}")

    # 2. Normalizar

    # Contador de errores de parseo, guarda cuántos campos fallaron al normalizar
    parse_errors: dict[str, int] = {
        "bulletin_number": 0,
        "published_at": 0,
        "event_date": 0,
        "url_raw": 0,
        "document_url_raw": 0,
    }

    # Lista de salida 

    # Registros normalizados correctamente
    normalized_records: list[dict] = []
    # Registros rechazados
    rejected_records: list[dict] = []

    for _, row in raw_df.iterrows():
        try:
            # Normalizacion por cada fila del DataFrame
            norm = normalize_row(row)
        except Exception as exc:
            # Si es que hubo Error, lo guarda con contexto:
            rejected_records.append({
                "record_id": row.get("record_id", ""),
                "rejection_reason": f"normalization_error: {exc}",
                "raw_identifier_hint": row.get("url_raw", "") or row.get("bulletin_number", ""),
            })
            # Salta a la siguiente fila
            continue
        # Cuenta errores de parseo
        # Si el valor original tenía datos pero el normalizado quedó vacío → hubo error
        if row["bulletin_number"].strip() and not norm["bulletin_number"]:
            parse_errors["bulletin_number"] += 1
        if row["published_at_raw"].strip() and not norm["published_at"]:
            parse_errors["published_at"] += 1
        if row["event_date_raw"].strip() and not norm["event_date"]:
            parse_errors["event_date"] += 1
        if row["url_raw"].strip() and not norm["canonical_url"]:
            parse_errors["url_raw"] += 1
        if row["document_url_raw"].strip() and not norm["canonical_document_url"]:
            parse_errors["document_url_raw"] += 1

        # Detecta y rechaza registros inválidos
        valid, reason = validate_normalized(norm)
        # Si no es valido se agrega a la lista de registros rechazados
        if not valid:
            rejected_records.append({
                "record_id": norm["record_id"],
                "rejection_reason": reason,
                "raw_identifier_hint": _raw_identifier_hint(norm),
            })
        else:
            # Si no se agregan a la lista de registros normalizados
            normalized_records.append(norm)

    print(f"[pipeline] Válidos: {len(normalized_records)}, Rechazados: {len(rejected_records)}")

    # 3. Deduplicar
    
    # Convierte la lista en DataFrame
    norm_df = pd.DataFrame(normalized_records)
    # Agrupa registros duplicados
    norm_df = assign_duplicate_groups(norm_df)

    # Se queda solo con los registros canonicos
    canonical_df = norm_df[norm_df["is_canonical"]].copy()
    # Cuenta, de cuantos duplicados se eliminaron
    duplicate_count = len(norm_df) - len(canonical_df)

    # Cuenta grupos que tienen duplicados, (Tamaño de grupo > 1)
    group_sizes = norm_df.groupby("duplicate_group_id").size()
    duplicate_groups = int((group_sizes > 1).sum())

    print(f"[pipeline] Grupos duplicados: {duplicate_groups}, Registros eliminados: {duplicate_count}")

    # 4. Trazabilidad
    # Construye tabla de duplicados
    clusters_df = build_duplicate_clusters(norm_df)

    # 5. Construir salida principal

    # Ordena y reinicia índices del DataFrame con registros Canonicos
    canonical_df = canonical_df.sort_values("record_id").reset_index(drop=True)
    # Crea canonical_ids:
    canonical_df.insert(0, "canonical_id", [f"CAN-{i+1:06d}" for i in range(len(canonical_df))])
    # Guarda ID original
    canonical_df["kept_record_id"] = canonical_df["record_id"]

    # Columnas a exportar 
    out_columns = [
        "canonical_id", "kept_record_id", "source", "source_type",
        "bulletin_number", "title", "summary", "published_at", "event_date",
        "status", "initiative", "authors", "canonical_url",
        "canonical_document_url", "duplicate_group_id",
    ]
    # Reordena columnas y rellena vacíos
    canonical_df = canonical_df.reindex(columns=out_columns, fill_value="")

    # 6. Escribir
    # Archivo registros normalizados
    canonical_df.to_csv(output_dir / "normalized_records.csv", index=False)
    print(f"[pipeline] normalized_records.csv ({len(canonical_df)} filas)")
    
    # Archivo registros rechazados
    pd.DataFrame(rejected_records).to_csv(output_dir / "rejected_records.csv", index=False)
    print(f"[pipeline] rejected_records.csv ({len(rejected_records)} filas)")

    # Archivo registros duplicados
    clusters_df.to_csv(output_dir / "duplicate_clusters.csv", index=False)
    print(f"[pipeline] duplicate_clusters.csv ({len(clusters_df)} filas)")

    # Reporte de calidad
    quality_report = {
        "input_rows": input_rows,
        "normalized_rows": len(canonical_df),
        "rejected_rows": len(rejected_records),
        "duplicate_groups": duplicate_groups,
        "duplicates_removed": duplicate_count,
        "parse_errors_by_field": parse_errors,
    }
    # Guarda JSON legible
    with open(output_dir / "quality_report.json", "w", encoding="utf-8") as f:
        json.dump(quality_report, f, indent=2, ensure_ascii=False)
    print(f"[pipeline] quality_report.json")
    print(f"[pipeline] Listo. Salidas en: {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normaliza y deduplica registros legislativos."
    )
    parser.add_argument("input", type=Path, help="Ruta a legislative_records.csv")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs/part1"),
        help="Directorio de salida (default: ./output)"
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: Archivo no encontrado: {args.input}", file=sys.stderr)
        sys.exit(1)

    run_pipeline(args.input, args.output_dir)


if __name__ == "__main__":
    main()
