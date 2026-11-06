# Playgrounds persistentes: consola y gestor

El objetivo es ofrecer 50 sesiones individuales y una consola de recursos dentro
de Arena, con dos VMs activas inicialmente y el resto en cola o conservadas en
disco. Una cuenta emulada es una etiqueta del laboratorio; el aislamiento lo
proporciona una VM independiente por participante. No son cuentas de AWS reales
ni un despliegue de AWS Control Tower.

## Consola desplegada

**Actualización:** misión 02 ya incorpora el flujo de commit verificado → apply
aislado → persistencia → recibo atómico → inventario. Consulta
[configuración y límites](mission-02-deploy.md). El bloque siguiente describe la
corrección previa: las capturas de referencia continúan fuera del portal; ahora
solo puede aparecer un inventario con recibo y procedencia de una entrega real.
Sin ese recibo la consola conserva «Sin despliegue del participante».

El portal muestra **Mi playground → Sin despliegue del participante**. Se retiraron
los botones de preparación/actualización y el inventario de referencia. La versión
previa permitía aplicar un template completo desde ese botón, sin una entrega del
alumno: los recursos eran reales, pero no representaban su trabajo. Ese flujo no
cumplía el objetivo del taller y ya no está disponible en el portal.

`GET /api/v1/participant/playground` no consulta ni devuelve capturas del template
de referencia. `POST` comprueba pertenencia/estado y rechaza aprovisionamiento con
409. Los discos de referencia existentes no se borran mediante esta corrección;
conservan su expiración normal y quedan fuera de la vista del participante.

La misión 02 permite revisar un plan o desplegar desde Actions. Solo el despliegue
verificado publica inventario y puede conceder puntos. El programa de una hora
ya está publicado con cuatro misiones; véase [programa y límites](short-workshop.md).
Las misiones 03/04 todavía evalúan handlers en recursos temporales, sin actualizar
las Lambdas de este despliegue persistente.

## Gestor privado de referencia

El gestor permanece disponible para pruebas del operador. La API del participante
sigue comprobando pertenencia y estado del evento en cada petición y no acepta
URLs SDK ni IDs de laboratorio seleccionados por el navegador.

El servicio privado `playgrounds` mantiene una cola FIFO en SQLite dentro del
volumen `playground-work`: hasta 50 laboratorios admitidos, con estados
`queued`, `preparing`, `parked`, `failed` y `expired`. Cada operación usa una VM
de 3 GiB; dos locks de kernel en `vm-slots` limitan conjuntamente playgrounds y
evaluaciones a **dos VMs en total**. Las posiciones mostradas son de la cola de
playgrounds, no una posición combinada con la cola de evaluaciones. El gestor
comprueba memoria host y reserva de disco antes de arrancar.

Los laboratorios expiran dos horas después de su primera solicitud; actualizar
no prolonga ese límite. El gestor consulta el estado del evento por una ruta
interna autenticada: pausa impide nuevos turnos; finalizar bloquea acceso
inmediatamente en la API y elimina discos/capturas al terminar operaciones ya
en curso. Un reinicio conserva la cola y marca operaciones interrumpidas como
fallidas; nunca anuncia una VM activa basándose en un registro antiguo.
Un apply parcialmente fallido conserva su disco para diagnóstico y puede requerir
intervención del operador; no se borra automáticamente para reintentar.

### Desplegar la integración

En este host Linux x86_64/KVM:

```bash
./scripts/deploy-edge.sh
```

El script combina `compose.yaml`, `compose.evaluator.yaml` y
`compose.playgrounds.yaml`; no requiere nuevos secretos. Añade
`PLAYGROUND_MANAGER_URL=http://playgrounds:9001` solo a la API y
`VM_SLOTS_DIR=/slots` a evaluador/gestor. La API incorpora una conexión privada a
`runner-control`. No se publica ningún puerto nuevo. No desplegar únicamente el
Compose base si se desea conservar esta integración habilitada. El gestor debe
mantenerse en una sola réplica mientras use esta cola SQLite y estos discos.

La prueba de la integración anterior verificó dos participantes temporales a través de
Nginx/API: identidad privada, apply real, captura, aparcado/reanudación, rechazo
409 de una tercera VM en el evaluador, revocación 403 y limpieza al finalizar.
Se eliminaron solo sus registros y discos. Una solicitud ajena concurrente se
conservó; el verificador no debe asumir que ambos cupos globales estén libres
al terminar si hay actividad real.
El [informe de integración](validation/playground-console-2026-11-05.json)
registra estos controles, la regresión KVM del evaluador y la comprobación del
portal público con el nuevo bundle y acceso anónimo rechazado con 401. Es evidencia
del ciclo del template de referencia, no de despliegues realizados por alumnos.

## Piloto previo de aceptación

`apps/playground` contiene una prueba de aceptación independiente. No modifica
el evaluador, no publica puertos, no otorga puntos y no se conecta a los datos de
eventos. Arranca dos VMs KVM de 3 GiB con overlays separados. Cada VM tiene su
propio Docker, Floci persistente, Terraform y runtime Python Lambda precargado.
No recibe el socket Docker del host, credenciales reales ni adaptador de red
externo. El controlador usa un canal serial privado y comandos acotados.

La prueba exige aplicar el plan revisado de 28 recursos, invocar Orders mediante
el servicio Lambda y observar las escrituras de ambos consumidores SQS. Después
apaga limpiamente cada VM, conserva su disco, vuelve a arrancarla y comprueba los
datos anteriores y una nueva orden. No basta con ejecutar handlers como
subprocesos. Se usan las implementaciones de referencia solo para esta prueba
interna; no se distribuyen como solución del taller.

El estado persistido incluye Terraform, recursos/datos de Floci y Docker en el
disco de la VM. Esto prueba apagado limpio/reinicio, no recuperación ante cortes
eléctricos. No hay pausa de RAM ni garantía de timers idénticos tras reiniciar.
La prueba se niega a reutilizar un volumen que ya contiene discos para no borrar
trabajo anterior.

## Ejecutar el piloto

Requiere Linux x86_64, KVM y al menos 13 GiB de memoria host disponible. Ejecutar
fuera de evaluaciones activas; el piloto y el evaluador todavía no comparten un
gestor global de reservas. La imagen se construye con conexión a Internet; las
VMs funcionan sin salida a Internet. El runtime Python 3.12 se descarga durante
la construcción y está fijado por digest en el Dockerfile, igual que Floci.

```bash
docker build --target guest -t cloudops-arena-judge-guest:base -f apps/runner/Dockerfile .
docker compose -f infra/edge/compose.playground-pilot.yaml build
docker compose -f infra/edge/compose.playground-pilot.yaml up --abort-on-container-exit --exit-code-from pilot
```

Un resultado válido debe terminar con `status=passed` para ambos laboratorios.
`/work/report.json` conserva el informe solo cuando ambos pasan. Los discos y
logs permanecen en el volumen exclusivo `arena-playground-pilot_playground-pilot`.
No usar `down -v` sobre los archivos Compose del evento para limpiar este piloto.

## Variante de una hora

Se incorporará como Game Pack versionado independiente; los eventos del pack
actual conservan misiones, contratos y puntos.

| Tiempo | Actividad | Evidencia requerida |
|---|---|---|
| 0–5 min | Arquitectura y entrada | Checkpoint de EventBridge |
| 5–20 min | Desplegar y explorar | Apply revisado, inventario real en consola |
| 20–40 min | Completar Orders | Orden persistida y evento procesado por consumidores preparados |
| 40–55 min | Incidente de Payments | Reintentos/DLQ y recuperación sobre los mismos recursos |
| 55–60 min | Cierre | Recorrido por evidencias y limpieza |

Actions seguirá siendo la entrada de entregas verificadas. La consola consultará
recursos solo a través del backend y de la pertenencia al evento; no aceptará
URLs SDK ni IDs de cuenta elegidos por el navegador. Las vistas de laboratorios
inactivos indicarán «Última captura» con fecha, nunca «En vivo».

## Pendientes para el nuevo taller y su evaluación

- Extender la prueba aprobada de dos VMs a entrada HTTP, incidentes sobre las
  Lambdas desplegadas, límites de código no confiable y recuperación ante fallos.
- Medir una carga de 50 sesiones, equidad entre las dos colas y latencia de
  reanudación; automatizar la preparación anticipada de los laboratorios.
- Integrar solicitudes Actions, commits verificados, reanudación y actualización
  de código, sin ejecutar código en API/worker.
- Añadir operaciones didácticas autenticadas y evaluadores para los mismos
  recursos persistentes, con evidencia y puntuación atómicas.
- Publicar el Game Pack nuevo solo tras esas pruebas; dos VMs no garantizan
  esperas compatibles con una hora.

## Resultado registrado · 2026-11-05

El [informe de aceptación](validation/playgrounds-2026-11-05.json) registra dos
VMs simultáneas aprobadas: apply revisado, Orders vía Lambda, consumidores SQS,
estado conservado al apagar/arrancar y una nueva orden tras reanudar. Los ciclos
completos tardaron 115,1 y 114,2 segundos. El pico del contenedor conjunto fue
6.706.163.712 bytes (6,25 GiB), bajo su límite de 8 GiB. El evaluador del evento
continuó saludable y no se modificaron eventos ni puntuaciones.

Esto verifica el flujo Lambda → EventBridge → SQS → Lambda → DynamoDB con el
template de referencia. API Gateway se creó con Terraform, pero su entrada HTTP
no se probó en este piloto. Tampoco se probaron todavía incidentes sobre Lambdas
desplegadas, código no confiable, pérdida abrupta del host o 50 participantes.

Para el taller de una hora, preparar y conservar los 50 discos antes de abrirlo
evita que todos esperen el aprovisionamiento inicial. La sesión debe usar colas
para reanudar, actualizar Orders y ejecutar operaciones breves; la lectura de una
captura no debe ocupar una VM. La duración observada es del ciclo completo de
aceptación, no una medida aislada de latencia de despliegue ni un SLA de cola.

El informe anterior corresponde al piloto interno. La consola integrada añade
el ciclo de asignación y consulta descrito arriba; no prueba aún el taller completo.
