# Laboratorio: reloj, monedas y pistas

La entrada del portal ya no muestra «Local demo» ni ofrece el botón demo de
puntuación. El participante ve su misión activa, tiempo restante, progreso,
saldo, una ruta de trabajo y acceso directo a sus instrucciones. La consola de
infraestructura sigue mostrando exclusivamente capturas con procedencia de un
commit desplegado; actualizar la vista no crea recursos.

## Operación del instructor

1. Abre `/instructor` y crea o selecciona tu partida. En una partida nueva la
   primera misión inicia con la duración del Game Pack.
2. En **Control de partida**, puedes indicar una duración de 1 a 240 minutos.
   Dejarla vacía usa `duration_minutes` del manifiesto.
3. **Activar** abre esa misión e inicia el reloj. **Reiniciar** la misión actual
   comienza un reloj nuevo con la duración elegida; no borra aprobaciones, saldo
   ni compras. **Pausar** congela los segundos restantes; **Abrir** los reanuda.
4. Al llegar a cero, la misión aparece cerrada y el servidor rechaza respuestas,
   compras, vinculaciones nuevas y entregas técnicas nuevas. No avanza a la
   siguiente automáticamente: el instructor la activa cuando corresponda.

Los eventos antiguos sin fecha límite siguen sin reloj hasta activar/reiniciar;
el despliegue de esta función no consume retroactivamente su tiempo. La duración
de cada misión del pack actual sigue siendo la de su manifiesto; para una hora,
el instructor debe elegir tiempos apropiados. El pack específico de una hora
continúa como borrador mientras se completa su flujo técnico.

El reloj es común por evento, no individual. Un alumno que entra tarde ve el
tiempo restante real. El navegador solo anima el contador; cambiar su reloj o
modificar la UI no extiende el plazo del servidor. Las entregas **ya registradas
antes del cierre** pueden terminar en la cola y recibir su resultado/puntos; la
espera por una VM no penaliza una entrega enviada a tiempo. Finalizar el evento
mantiene las restricciones de autorización y limpieza existentes.

## Monedas y compra de pistas

- Cada misión completada aporta **10 monedas** por defecto (`coin_reward` en el
  manifiesto). Las aprobaciones existentes cuentan sin migrar ni modificar puntos.
- El saldo se deriva de las finalizaciones únicas `SUB` y del gasto confirmado.
  Repetir un workflow, cambiar de commit o revincular el repositorio no genera
  monedas adicionales. El punto de vinculación y las aprobaciones demo no cuentan.
- Las pistas iniciales cuestan **3 o 6 monedas**. No descuentan puntos del ranking.
  La primera misión es el checkpoint de entrada; permite obtener las primeras
  monedas antes de las pistas de las misiones técnicas.
- En modo individual saldo y compras son privados; en modo equipo se comparten
  entre miembros vigentes. El texto comprado sigue disponible al volver a entrar.
- Solo se compran pistas de la misión activa, con evento abierto y tiempo válido.
  Las pistas ya compradas se pueden consultar después del cierre.

Cada pista declara `id`, `title`, `cost` y `content` dentro de `missions[].hints`.
El API público de misiones excluye `hints`; el dashboard publica el catálogo y
solo añade contenido a las compras del equipo autenticado. Un débito y su recibo
son una transacción condicional: compra única, saldo esperado, pertenencia,
equipo existente, misión activa y plazo vigente. Compras simultáneas de una misma
pista cobran una sola vez; otras carreras devuelven 409 para actualizar/reintentar.
El cliente no decide el precio ni puede concederse monedas. No cambies recompensas
o precios de una versión en curso sin planificar su efecto sobre saldos existentes.

## Laboratorios y generaciones

El cupo ahora cuenta **participaciones únicas** (individual o equipo), no discos
de cada intento. El máximo global sigue siendo 50; evaluador y playgrounds comparten
dos locks de VM. Las VMs se apagan entre operaciones; consultar una captura no
ocupa un turno.

Cada participante mantiene un laboratorio vigente y puede preparar un candidato:

1. Un fallo conserva la VM y el recibo vigentes. El candidato fallido no consume
   otro cupo; sus archivos expiran en cinco minutos o se retiran al reintentar.
2. Un sucesor válido aún no destruye nada. El worker debe confirmar atómicamente
   su recibo de despliegue y los puntos correspondientes.
3. El gestor consulta ese recibo en el API privado. Solo si coincide en laboratorio,
   evaluación, commit y digest cambia el laboratorio vigente y retira generaciones
   anteriores. Nunca confía en un acuse enviado por el navegador.
4. Una reconciliación periódica completa ese paso si el worker se interrumpe tras
   confirmar el recibo. La limpieza no depende de que haya memoria para otra VM.

El último despliegue confirmado da dos horas de vigencia al laboratorio. Un trabajo
en curso reserva margen para terminar; leer o actualizar la vista no prolonga la
vigencia. Finalizar el evento revoca el acceso y limpia cuando las VMs se detienen.
Los laboratorios anteriores se asocian de forma perezosa al dueño desde su recibo
canónico cuando este vuelve a desplegar. El gestor continúa siendo de una sola
réplica y los discos son locales; esto no constituye alta disponibilidad.

## Esquema y despliegue

No hay nuevos secretos ni variables de entorno. `./scripts/deploy-edge.sh` sigue
combinando los tres Compose de edge. La API/worker y web deben reconstruirse para
incorporar los contratos y contenidos nuevos; la base de VM no cambia.

Datos adicionales, creados sin resetear eventos:

| Almacenamiento | Datos |
|---|---|
| Evento `META` | `mission_deadline` (epoch UTC), `mission_remaining` al pausar |
| `WALLET#{team}` | Gasto acumulado; créditos derivados de finalizaciones únicas |
| `HINT#{team}#{mission}#{hint}` | Recibo único, costo, fecha y versión del pack |
| SQLite privado `owners` | Dueño, evento/equipo, laboratorio vigente/candidato, vigencia |
| SQLite privado `labs.owner` | Asociación de generaciones para retirar las anteriores |

Rutas nuevas: `POST /api/v1/participant/missions/{mission}/hints/{hint}` y consulta
interna autenticada `/internal/playgrounds/owners/{event}/{team}`. El dashboard
añade `wallet`, `hints` y `mission_clock`. Activar misión acepta opcionalmente
`duration_minutes`. Las rutas antiguas y sesiones siguen siendo compatibles.

## Evidencia y límites

[Informe de validación](validation/lab-experience-2026-11-06.json): 213 pruebas de
API, 8 pruebas web y TS/Vite; doce compras duplicadas concurrentes; congelación y
cierre del reloj; tres intentos reales de VM (válido, rechazado y reemplazo válido)
sin duplicar puntos/monedas; revisión de escritorio 1440×1000 y móvil 390×844 sin
desbordamiento horizontal. Se borraron solo los datos sintéticos y su perfil de
navegador temporal.

También se probaron 50 sesiones autenticadas y 450 lecturas a través del Nginx
local, con P95 de 59,8 ms. Es carga de portal en el origen, **no** 50 VMs activas,
ni una medición de Internet/Cloudflare ni del taller completo con todos desplegando.
La concurrencia de VMs permanece en dos. Las misiones 03/04 conservan sus jueces
actuales de fixtures efímeras; su conexión al playground persistente es trabajo
independiente. No se presenta esta entrega como producción certificada ni como
un taller completo ya validado bajo carga.

## Avance automático de misiones

El servidor comprueba cada dos segundos los eventos abiertos con reloj vencido.
Cierra la misión anterior y activa la siguiente según el orden del Game Pack,
con su duración completa desde la transición. No depende de visitas al portal.
Después de una interrupción no salta todas las misiones atrasadas: concede el
tiempo completo a la siguiente. Eventos sin reloj y eventos pausados no avanzan.

La actualización condiciona estado, pack, misión y deadline originales: dos APIs
concurrentes, una pausa o un reinicio del instructor no pueden sobrescribirse con
una transición calculada sobre datos anteriores. No modifica puntuaciones,
compras ni aprobaciones. El cierre existente del servidor impide entregas nuevas
de una misión vencida aunque el navegador tarde en actualizarse.

Al vencer la última se marca `mission_sequence_complete=true` en META, sin
finalizar el evento. El reloj queda vencido: se pueden consultar recursos y las
entregas aceptadas a tiempo pueden finalizar. El instructor decide cuándo cerrar
la partida y limpiar los laboratorios. Activar/reiniciar una misión elimina esa
marca. `auto_advance_missions=false` en META desactiva el avance para operación
manual; por defecto los eventos con reloj participan en el avance automático.

El portal de participante selecciona la nueva misión en su siguiente consulta
(6–9 segundos); instructor se actualiza cada 5 segundos. La pantalla pública
conserva su consulta cada 3 segundos. No hay nuevos secretos ni variables de
entorno. El proceso usa el lifespan de la API y consulta eventos mediante scan;
antes de ampliar a muchos eventos simultáneos conviene un índice de vencimientos.

## Apertura e inicio separados

Los eventos nuevos se crean abiertos para registro, con `missions_started=false`,
`active_mission_id` vacío y sin `mission_deadline`. Se pueden registrar alumnos y
equipos sin consumir tiempo. El portal muestra «Esperando al instructor» y el
reloj «Por iniciar»; no hay misión activa ni entregas habilitadas.

En instructor, abre la partida para que entren los asistentes y pulsa **Iniciar
misión 1** cuando estén listos. Esa acción usa el endpoint de activación existente,
marca `missions_started=true` y comienza la duración completa de la primera misión.
El avance automático toma el control a partir de ese momento. Abrir o reanudar
un evento que todavía espera no comienza la primera misión. Si se inicia mientras
está pausado, el reloj permanece congelado hasta reabrir la partida.

La API rechaza iniciar otra misión antes de la primera y el planificador ignora
la sala de espera incluso si tuviera un deadline residual. Los eventos antiguos
sin la nueva marca conservan su comportamiento y progreso; este despliegue no
reinicia partidas existentes.
