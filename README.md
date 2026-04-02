# Legislative Records Pipeline

1. Pipeline de normalización y deduplicación de registros legislativos.
2. Pipeline de Scrapping fuente oficial Cámara de Diputadas y Diputados de Chile

## 1. Como correr la soluccion:

# Requisitos
- **Python 3.11+**
- Librerías (todas disponibles en PyPI):

| Librería | Uso | ¿Poco habitual? |
|---|---|---|
| `pandas` | Carga y manipulación de CSV | No |
| `python-dateutil` | Parseo flexible de fechas | No |
| `beautifulsoup4` | Extracción de texto de HTML / decodificación de snippets | No |
| ``lxml`` | 
| `solenium` | 

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
## 3. Reglas de normalización implementadas
## 4. Criterio usado para elegir el registro canónico en duplicados
Se implementa con una clave de ordenamiento compuesta:
1. Mayor cantidad de campos no vacíos (riqueza)
2. `source_type` en orden: `detail > table > api > news > misc`
3. Fecha más reciente entre `published_at` y `event_date`
4. `record_id` lexicográficamente menor (desempate final)

## 5. Edge cases considerados
## 6. Limitaciones actuales
## 7. Qué harías para llevar esta solución a producción
## 8. Tiempo invertido
El tiempo invertido en el desarrollo del proyecto fue de aproximadamente 10 a 12 horas. Donde se revisó cada detalle de manera cuidadosa, para asegurar que cada componente estuviera correctamente implementado y que el resultado final tuviera la calidad necesaria.
## 9. Herramientas externas usadas (incluyendo IA, si aplica)
Se utilizó inteligencia artificial como apoyo durante el desarrollo del proyecto, principalmente el modelo Claude Sonnet 4.6 y tambien GPT. Estas herramientas se emplearon para asistir en tareas de generación de código y resolución de dudas técnicas
