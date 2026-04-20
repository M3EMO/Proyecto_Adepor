# INSTRUCTIVO — CLAUDE CODE AGENT TEAMS
# Proyecto Adepor | Referencia técnica interna
# Fuente: https://code.claude.com/docs/en/agent-teams
# Fecha: 2026-04-11

---

## 1. QUE SON LOS AGENT TEAMS

Agent Teams permite coordinar múltiples instancias de Claude Code trabajando en paralelo.

- **Team lead**: sesión principal. Crea el equipo, asigna tareas, coordina.
- **Teammates**: instancias independientes con su propio contexto. NO heredan el historial del lead.
- Cada teammate consume tokens de forma independiente.

---

## 2. HABILITACION

### Variable de entorno requerida (ya activa en este proyecto):
```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```
Requiere Claude Code v2.1.32 o superior.

---

## 3. ARQUITECTURA INTERNA

| Componente    | Ubicación                                   | Descripción                                       |
|---------------|---------------------------------------------|---------------------------------------------------|
| Task list     | `~/.claude/tasks/{team-name}/`              | Lista compartida de trabajos con estados          |
| Mailbox       | Interno                                     | Sistema de mensajería entre agentes               |
| Team config   | `~/.claude/teams/{team-name}/config.json`   | Metadatos del equipo (teammates disponibles)      |

### Estados de tareas:
`pending` → `in progress` → `completed`

- Las dependencias entre tareas se resuelven automáticamente.
- File locking previene condiciones de carrera (race conditions).
- Auto-claim o asignación explícita de tareas.

---

## 4. MODOS DE VISUALIZACION

### In-process (recomendado para este proyecto):
Todos los teammates en la terminal principal.
Navegar entre ellos: **Shift + Down**

### Split panes:
Cada teammate en su propio panel. Requiere tmux o iTerm2.

### Configurar en `~/.claude.json`:
```json
{
  "teammateMode": "in-process"
}
```

---

## 5. COMUNICACION ENTRE AGENTES

### Herramientas disponibles en el lead:
- `SendMessage`: enviar mensaje a un teammate específico por nombre
- `broadcast`: enviar mensaje a todos los teammates simultáneamente

### Restricciones:
- Los teammates pueden leer el team config para descubrir a otros miembros.
- Los teammates NO reciben el historial conversacional del lead.
- Los teammates NO pueden crear sub-equipos (sin equipos anidados).

---

## 6. CREAR UN EQUIPO

### Comando natural desde el lead:
```
Create an agent team to [descripcion de la tarea].
Spawn [N] teammates named [nombre1], [nombre2], [nombre3]...
```

### Buenas practicas al crear:
- Asignar nombres predecibles para referencias posteriores (SendMessage por nombre).
- Incluir detalles específicos en el prompt de spawn de cada teammate.
- Dividir archivos entre teammates para evitar conflictos de escritura.

---

## 7. USAR SUBAGENTES COMO TEAMMATES

Si hay definiciones de subagentes (.md en `.claude/agents/`), se pueden referenciar:
```
Spawn a teammate using the [nombre-agente] agent type...
```

### Importante:
- Las definiciones de subagente proveen: `tools` (allowlist) y `model`.
- Las definiciones de subagente NO aplican: `skills` ni `mcpServers`.

---

## 8. HOOKS DE CONTROL DE CALIDAD

Tres puntos de intervencion para validacion automatica:

| Hook             | Codigo de salida 2 | Efecto                                      |
|------------------|--------------------|---------------------------------------------|
| `TeammateIdle`   | 2                  | Mantiene al teammate trabajando (no lo cierra) |
| `TaskCreated`    | 2                  | Previene la creacion de esa tarea           |
| `TaskCompleted`  | 2                  | Bloquea marcar la tarea como completada     |

---

## 9. TAMANO OPTIMO DEL EQUIPO

| Parametro              | Valor recomendado          |
|------------------------|----------------------------|
| Teammates              | 3 a 5 (optimo)             |
| Tareas por teammate    | 5 a 6                      |
| Costo de tokens        | Escala lineal con teammates|

**Mas efectivo para:** investigacion, revision de codigo, analisis paralelo.
**Menos efectivo para:** tareas rutinarias o secuenciales simples.

---

## 10. LIMPIEZA DEL EQUIPO

Siempre ejecutar desde el lead (NUNCA desde un teammate):
```
Clean up the team
```

---

## 11. LIMITACIONES CONOCIDAS

- Sin reanudacion de sesiones con teammates in-process.
- El estado de tareas puede atrasarse levemente.
- Shutdown puede ser lento.
- Un solo equipo activo por sesion.
- Sin equipos anidados: los teammates no pueden crear sub-equipos.
- Split panes solo disponible en tmux o iTerm2.

---

## 12. APLICACION EN PROYECTO ADEPOR

### Casos de uso validados para este proyecto:

#### A) Backtest paralelo por liga
```
Spawn 5 teammates: uno por liga (Argentina, Brasil, Inglaterra, Noruega, Turquia).
Cada uno procesa sus Liquidados y calcula yield, hit%, racha maxima.
Lead consolida y genera reporte.
```

#### B) Diagnostico multi-motor
```
Spawn 4 teammates: motor_calculadora, motor_cuotas, motor_data, motor_arbitro.
Cada uno audita su propio motor contra Reglas_IA.txt.
Lead consolida inconsistencias.
```

#### C) Calibracion paralela de parametros
```
Spawn 3 teammates: uno calibra FACTOR_CORR_XG_OU, otro rho por liga, otro ALFA_EMA.
Trabajan sobre distintas tablas de la DB sin conflictos.
Lead integra los nuevos valores en config_sistema.py previa confirmacion.
```

#### D) Onboarding de liga nueva
```
Spawn 3 teammates: 
- Teammate 1: busca ESPN code y The-Odds-API key.
- Teammate 2: estima parametros iniciales comparando con ligas similares.
- Teammate 3: genera checklist de validacion (30 primeros partidos).
Lead genera el bloque final para config_sistema.py.
```

### Regla de seguridad Adepor para Agent Teams:
**Ningun teammate escribe en la DB ni modifica codigo sin confirmacion explícita del lead.**
El lead siempre toma un snapshot con adepor_guard.py antes de aplicar cambios propuestos por teammates.

---

## 13. REFERENCIA RAPIDA DE COMANDOS

```
# Crear equipo
"Create an agent team. Spawn 3 teammates named auditor, calibrador, reportero."

# Enviar mensaje a teammate especifico
SendMessage → "auditor" → "Procesa los Liquidados de Argentina de los ultimos 30 dias."

# Broadcast a todos
broadcast → "Detengan el proceso y reporten estado actual."

# Navegar entre teammates (in-process)
Shift + Down

# Limpiar equipo
"Clean up the team"
```

---

*Instructivo generado para uso interno de Claude en sesiones de Proyecto Adepor.*
*Actualizar si cambia la version de Claude Code o la documentacion oficial.*
