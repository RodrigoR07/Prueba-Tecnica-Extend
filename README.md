# Legislative Records Pipeline

1. Pipeline de normalización y deduplicación de registros legislativos.
2. Pipeline del Web Scraping fuente oficial Cámara de Diputadas y Diputados de Chile

## 1. Como correr la soluccion:

# Requisitos
- **Python 3.11+**
- Librerías (todas disponibles en PyPI):

| Librería | Uso |
|---|---|
| `pandas` | Carga y manipulación de CSV |
| `python-dateutil` | Parseo flexible de fechas | 
| `beautifulsoup4` | Extracción de texto de HTML / decodificación de snippets | 
| ``lxml`` | |Procesamiento de HTML y XML de forma  rápida.| 
| `solenium` | |Herramienta para automatizar un navegador real|

> **Nota:** `beautifulsoup4` se usa para limpiar campos `title_raw` y `summary_raw` que pueden
> contener HTML embebido (etiquetas, entidades). 

# Instalación

```bash
# Crear entorno virtual (recomendado)
python -m venv venv
source venv/bin/activate        # Linux/macOS
# venv\Scripts\activate.bat     # Windows desde CMD
# source venv/Scripts/activate  # Windows desde bash

# Instalar dependencias
pip install -r requirements.txt
```

## Uso

```bash
# Desde el directorio /legislative_pipeline acceder a src
cd src

# Luego para correr part1.py (dentro de la carpeta /src):
python part1.py ../legislative_records.csv

# Para correr part2.py (dentro de la carpeta /src):
python part2.py
```
# Tests
```bash
# Para correr los test unitarios de part1.py, se debe salir de /src e ir al directorio /legislative_pipeline:
cd ..

# Luego para ejecutar los tests unitarios:
pytest tests/ -v
```


## 2. Supuesto tomados
# Normalizacion y deduplicacion CSV
- El CSV de entrada usa utf-8. Cualquier otra codificación se rechaza con error explícito.
- Los campos status, initiative, source, source_type, content_hash_hint y html_snippet se traspasan sin normalizar (se asumen limpios en origen).
# Web Scraping
- Se asume que la tabla de tramitación contiene al menos una columna con fechas que permiten identificar filas válidas.
- Se asume que una tasa de 1 request por segundo es suficiente para no afectar al servidor ni ser bloqueado.
- Las páginas con contenido dinámico requieren JavaScript, por lo que se usa Selenium en modo headless para esos casos.
## 3. Reglas de normalización implementadas
| Campo | Regla |
|---|---|
| `title, summary`,`summary` | Strip, decode de entidades HTML, eliminación de tags HTML (BeautifulSoup), colapso de espacios internos a un solo espacio |
| `bulletin_number` | Canonización a NNNNN-DD; acepta sin guion, con /, con espacios; rechaza si el sufijo no es numérico o si tiene mas de 5 digitos el prefijo |
| `published_at`,` event_date` | Parsing flexible con dateutil; salida YYYY-MM-DD si solo hay fecha, YYYY-MM-DDTHH:MM:SS si hay hora |
| `authors` | |Se normaliza a una única cadena usando el separador ' | ', sin duplicados  y sin espacios|
| `canonical_url`,` canonical_document_url` | Lowercase del host, eliminación de tracking params (utm_*, gclid, fbclid), se elimina el '/' final de la ruta |
## 4. Criterio usado para elegir el registro canónico en duplicados
Los duplicados se detectan por tres llaves, aplicadas en orden de prioridad:
- Misma URL normalizada
- Mismo bulletin_number + mismo título  (cuando no hay URL)
- Mismo content_hash_hint + mismo título  (cuando no hay bulletin_number)

Dentro de cada grupo de duplicados, el canónico se elige ordenando por:

Riqueza DESC – mayor cantidad de campos relevantes no vacíos (url, document_url,
    title, bulletin_number, summary, etc.)
source_type ASC – jerarquía detail > table > api > news > misc > otros
Fecha más reciente DESC – se toma el máximo entre published_at y event_date

## 5. Edge cases considerados
# Normalizacion y deduplicacion CSV
- Boletines sin guion o con separadores inusuales (11422/07, 1142207, 11422 - 07): normalizados correctamente. Sufijos no numéricos (17000-XX) devuelven vacío.
- Fechas con y sin hora: se detecta la presencia de HH:MM antes del parsing para elegir el formato de salida correcto.
- Authors en múltiples formatos: JSON array, JSON de objetos, pipe-separated, semicolon, CSV, o string simple.
- URLs con tracking params: se filtran utm_*, gclid y fbclid.
- Registros unicos: cada registro sin par recibe su propio duplicate_group_id derivado de su record_id, y se marca automáticamente como canónico.
# Web Scraping
- Variaciones en el formato de fechas, se controlan correctamente(por ejemplo: 20/11/2019, 2019-11-20, 20 Nov. 2019).
- URLs que retornan errores HTTP (404, 500, etc.).
- Paginación dinámica (contenido cargado mediante JavaScript), resuelto mediante Selenium.
## 6. Limitaciones actuales
# Normalizacion y deduplicacion CSV
- Sin soporte multi-encoding: el CSV de entrada debe estar en UTF-8; otros tipos de encodings fallan en la carga.
- La normalizacion de fechas, se encuentra incompleta para que sirva para la mayoria de casos
# Web Scraping
- El uso de Selenium incrementa el tiempo de ejecución y el consumo de recursos.
- No se implementa paralelización del scraping, lo que puede hacer el proceso lento para grandes volúmenes de URLs.
- No hay mecanismo de reanudación en caso de falla.
## 7. Qué harías para llevar esta solución a producción
# Normalizacion y deduplicacion CSV
- Intentar optimizar el proceso de carga, normalizacion y deduplicacion del CSV, como por ejemplo reduciendo loops inncesarios, obteniendo asi una solucion escalable
# Web Scraping
- Reemplazar Selenium por otra alternativa para mejorar eficiencia.
- Implementar reintentos más robustos y persistencia intermedia para poder reanudar procesos fallidos.
- Agregar tests unitarios y de integración para asegurar estabilidad ante cambios.
- Implementar paralelización controlada.
- Containerizar la solución usando Docker.
## 8. Tiempo invertido
El tiempo invertido en el desarrollo del proyecto fue aproximadamente de 10 a 12 horas. Donde se revisó cada detalle de manera cuidadosa, para asegurar todo estuviera correctamente implementado y que el resultado final tuviera la calidad necesaria.
## 9. Herramientas externas usadas (incluyendo IA, si aplica)
Se utilizó inteligencia artificial como apoyo durante el desarrollo del proyecto, principalmente el modelo Claude Sonnet 4.6 y tambien GPT. Estas herramientas se emplearon para asistir en tareas de generación de código y resolución de dudas técnicas.
