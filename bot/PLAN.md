# Plan de Implementación: Nuevas Funcionalidades del Bot Librarian

## Visión General

Este documento detalla la implementación de 4 nuevas funcionalidades para el bot de Telegram:

1. **Comando `/search`** — Búsqueda en el vault
2. **Comando `/reading`** — Dashboard de lectura
3. **Resumen automático al terminar libro** — Mejora del comando `/done`
4. **Comando `/orphan`** — Reconexión de Cards huérfanas

---

## 1. Comando `/search`

### Descripción
Permite buscar en el vault (Cards y Encounters) mencionando un concepto.

### Uso
```
/search productividad           # Búsqueda simple por palabra clave
/search --ai productividad      # Búsqueda semántica con LLM
/search -a productividad       # Alias para búsqueda semántica
```

### Implementación

#### vault.py — Nuevas funciones
```python
def search_vault(query: str, use_llm: bool = False) -> dict:
    """
    Busca en Cards y Encounters.
    
    Args:
        query: Término de búsqueda
        use_llm: Si True, usa búsqueda semántica con LLM
    
    Returns:
        dict con 'cards' y 'encounters' como listas de resultados
    """
    pass

def search_simple(query: str) -> tuple[list[dict], list[dict]]:
    """Búsqueda simple por palabras clave en contenido y títulos."""
    pass

def search_semantic(query: str) -> tuple[list[dict], list[dict]]:
    """Búsqueda semántica usando LLM para entender el contexto."""
    pass
```

#### handlers.py — Nuevo handler
```python
async def search_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Maneja /search [flags] <query>
    
    Flags:
        --ai, -a: Usar búsqueda semántica con LLM
    """
    pass
```

#### Formato de resultado
```
🔍 Búsqueda: "productividad"

📚 ENCOUNTERS (2)
━━━━━━━━━━━━━━━━━━━━━━
• The Manager's Path (p.47, 156)
• Deep Work (p.23, 89)

🗂️ CARDS (5)
━━━━━━━━━━━━━━━━━━━━━━
• Deep Work Concept
• Time Blocking Method
• Focus Traps
• Productivity Metrics
• Energy Management

💡 Usa /search --ai para búsqueda semántica más inteligente
```

---

## 2. Comando `/reading`

### Descripción
Dashboard de lectura que muestra libros en progreso con número de entradas y última actualización.

### Uso
```
/reading
```

### Implementación

#### vault.py — Nuevas funciones
```python
def get_reading_dashboard() -> list[dict]:
    """
    Obtiene lista de libros en progreso.
    
    Returns:
        Lista de dicts con:
        - title: título del libro
        - author: autor
        - status: estado (in-progress, done)
        - rating: valoración (1-5)
        - entries_count: número de entradas en Bookmarks
        - updated: última fecha de actualización
    """
    pass

def count_bookmarks(book_title: str) -> int:
    """Cuenta las entradas en la sección Bookmarks de un Encounter."""
    pass

def get_encounter_metadata(title: str) -> dict:
    """Extrae metadatos del frontmatter y secciones del Encounter."""
    pass
```

#### handlers.py — Nuevo handler
```python
async def reading_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra el dashboard de lectura."""
    pass
```

#### Formato de resultado
```
📚 TUS LIBROS EN LECTURA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📖 The Manager's Path
   Autor: Camille Fournier
   Estado: 📖 En progreso
   Entradas: 23 bookmarks
   Última actualización: 2024-01-15
   Valoración: ⭐⭐⭐ (3)

📖 Deep Work
   Autor: Cal Newport
   Estado: 📖 En progreso
   Entradas: 15 bookmarks
   Última actualización: 2024-01-10
   Valoración: —

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 Total: 2 libros en progreso
📊 Total de entradas capturadas: 38
```

---

## 3. Resumen Automático al Terminar Libro

### Descripción
Cuando el usuario hace `/done` y valora el libro, el LLM genera automáticamente:
- **## Summary**: Resumen de una-paragraph del libro
- **## Key Ideas**: Ideas clave extraídas de todos los bookmarks

### Flujo
1. Usuario ejecuta `/done`
2. Bot pregunta valoración (rating 1-5)
3. Usuario selecciona valoración
4. Bot:
   - Marca libro como "done" con rating
   - Extrae todos los bookmarks del libro
   - Envía contenido a LLM para generar summary e ideas clave
   - Actualiza el Encounter con el resumen generado

### Implementación

#### vault.py — Nuevas funciones
```python
def get_all_bookmarks(book_title: str) -> str:
    """
    Extrae toda la sección Bookmarks de un Encounter.
    
    Returns:
        Texto completo de las secciones de bookmarks
    """
    pass

def update_encounter_summary(book_title: str, summary: str, key_ideas: list[str]) -> bool:
    """
    Actualiza las secciones Summary y Key Ideas del Encounter.
    
    Args:
        book_title: Título del libro
        summary: Resumen generado
        key_ideas: Lista de ideas clave
    
    Returns:
        True si se actualizó correctamente
    """
    pass
```

#### llm.py — Nueva función
```python
def generate_book_summary(book_title: str, bookmarks_content: str) -> dict:
    """
    Usa LLM para generar resumen e ideas clave.
    
    Args:
        book_title: Título del libro
        bookmarks_content: Contenido de todos los bookmarks
    
    Returns:
        dict con 'summary' y 'key_ideas' (lista)
    """
    pass
```

#### handlers.py — Modificaciones
- En `callback_handler`, cuando se procesa `rate:1` a `rate:5`:
  - Después de `vault.update_encounter_status(...)`
  - Llamar a función de generación de resumen
  - Enviar resumen generado al usuario
  - Actualizar el Encounter

#### Prompt para LLM
```
Eres un asistente de lectura experto. Genera un resumen y las ideas clave de este libro basándote en los bookmarks capturados.

Título del libro: {book_title}

BOOKMARKS CAPTURADOS:
{bookmarks_content}

Genera:
1. ## Summary: Un párrafo resumiendo el libro (2-4 oraciones)
2. ## Key Ideas: Lista de 5-10 ideas clave numeradas

Responde en JSON:
{{
  "summary": "...",
  "key_ideas": ["idea 1", "idea 2", ...]
}}
```

---

## 4. Comando `/orphan` — Reconexión de Cards Huérfanas

### Descripción
Analiza las Cards que no están enlazadas a ningún MOC y sugiere conexiones basándose en el contenido.

### Uso
```
/orphan            # Busca Cards huérfanas y sugiere conexiones
/orphan --link    # Aplica los enlaces sugeridos automáticamente
/orphan --list    # Solo lista Cards huérfanas sin sugerir
```

### Implementación

#### vault.py — Nuevas funciones
```python
def find_orphan_cards() -> list[dict]:
    """
    Encuentra Cards que no están enlazadas a ningún MOC.
    
    Returns:
        Lista de dicts con:
        - title: título de la Card
        - content: contenido (primeras líneas)
        - file_path: ruta del archivo
    """
    pass

def get_moc_contents() -> dict[str, str]:
    """
    Obtiene contenido de todos los MOCs.
    
    Returns:
        Dict con nombre MOC -> contenido
    """
    pass

def suggest_moc_connections(card_title: str, card_content: str, mocs: dict) -> list[str]:
    """
    Sugiere MOCs relacionados para una Card.
    
    Args:
        card_title: Título de la Card
        card_content: Contenido de la Card
        mocs: Dict de MOCs disponibles
    
    Returns:
        Lista de MOCs sugeridos
    """
    pass

def link_card_to_moc(card_title: str, moc_names: list[str]) -> bool:
    """
    Añade enlaces a MOCs en una Card.
    
    Args:
        card_title: Título de la Card
        moc_names: Lista de nombres de MOCs a enlazar
    
    Returns:
        True si se actualizó correctamente
    """
    pass
```

#### handlers.py — Nuevo handler
```python
async def orphan_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Maneja /orphan [flags]
    
    Flags:
        --link, -l: Aplicar sugerencias automáticamente
        --list, -s: Solo listar sin sugerir
    """
    pass
```

#### Formato de resultado (listado)
```
🗂️ CARDS HUÉRFANAS (sin enlazar a MOCs)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Deep Work Concept
   📝 "La capacidad de trabajar sin distracción..."
   
2. Time Blocking Method  
   📝 "Técnica de planificación que divide el día..."

3. Focus Traps
   📝 "Situaciones que destruyen la concentración..."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 3 Cards sin enlazar

Usa /orphan --link para conectar automáticamente
```

#### Formato de resultado (con sugerencias)
```
🗂️ RECONEXIÓN DE CARDS HUÉRFANAS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Deep Work Concept
   💡 Sugerencias: Productivity, Development
   [Conectar a Productivity] [Conectar a Development] [Ignorar]

2. Time Blocking Method
   💡 Sugerencias: Productivity
   [Conectar a Productivity] [Ignorar]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 Total: 2 conexiones sugeridas
```

---

## Archivos a Modificar

1. **bot/src/vault.py**
   - Añadir funciones de búsqueda
   - Añadir funciones de dashboard
   - Añadir funciones de resumen de libro
   - Añadir funciones de Cards huérfanas

2. **bot/src/llm.py**
   - Añadir función `generate_book_summary()`
   - Añadir función para sugerir conexiones de MOCs

3. **bot/src/handlers.py**
   - Añadir `search_handler()`
   - Añadir `reading_handler()`
   - Añadir `orphan_handler()`
   - Modificar `callback_handler` para generación automática de resumen

4. **bot/src/main.py**
   - Registrar nuevos CommandHandlers

---

## Pruebas

### Test /search
```bash
/search productividad
/search --ai leadership
```

### Test /reading
```bash
/reading
```

### Test /done (resumen automático)
```bash
/done
# Seleccionar rating
# Verificar que se genera el resumen
```

### Test /orphan
```bash
/orphan
/orphan --list
/orphan --link
```

---

## Consideraciones

- **Rate limiting**: El LLM tiene límites de uso. Implementar cacheo o límites en búsquedas semánticas.
- **Tiempo de respuesta**: Búsquedas semánticas con LLM pueden tardar más. Mostrar indicador de "escribiendo...".
- **Duplicados**: Al buscar, filtrar resultados duplicados o muy similares.
- **Tags y metadatos**: Usar el frontmatter de Obsidian para filtrar por tags, fecha, etc.
