# Objetivo operativo: 50 participantes con evaluaciones en cola

## Alcance de esta entrega

La plataforma admite un evento de 50 participantes individuales y sus entregas
Actions en una cola persistida en DynamoDB/Floci. Ejecuta hasta dos VMs del juez
a la vez. **No crea 50 playgrounds persistentes ni implementa todavía el despliegue
Terraform/Lambda que se reutiliza entre misiones.** Ese ciclo de vida necesita
otro componente; esta entrega prepara el control de concurrencia actual.

La máquina medida es Linux x86_64, i5-11400 (6 núcleos/12 hilos), 31,2 GiB de RAM,
aproximadamente 18,8 GiB disponibles y 633 GB libres en SSD. No corresponde al
Mac M1 de 16 GB mencionado al principio. Los límites siguientes se eligieron
para esta máquina y para los jueces actuales de 1536 MiB por VM, no para asegurar
la capacidad de futuros playgrounds con Docker/Lambda completos.

## Límites desplegados

| Control | Valor inicial |
|---|---|
| Entregas pendientes + activas | 50 globales, entre todos los eventos |
| Evaluaciones simultáneas | 2 |
| VM del juez | 2 vCPU y 1536 MiB, sin NIC |
| Contenedor runner | 6 GiB de RAM, 4 CPU, 128 procesos |
| Contenedor worker | 512 MiB de RAM, 1 CPU |
| Margen de memoria del host | 6 GiB más reservas conservadoras de arranque |
| Margen de disco en `/work` | 2 GiB |
| Espera máxima antes de ejecutar | 1800 segundos |
| Lease de ejecución | 600 segundos |
| Espera del workflow | 50 minutos; job de 60 minutos |

El runner verifica memoria disponible del host, margen del cgroup y disco antes
de reservar un cupo; no admite más VMs si falta margen. Los cupos se liberan
solo después de terminar y limpiar el proceso/overlay. La memoria ya ocupada por
otras aplicaciones puede reducir la concurrencia efectiva. No se usa swap como
capacidad adicional. Cambiar el máximo a cuatro no garantiza cuatro cupos: el
límite de memoria y las reservas siguen prevaleciendo.

## Cola, fallos y visibilidad

- Cada aceptación incrementa un contador global en la misma transacción que
  inserta la entrega y el lock del equipo. Si ya hay 50, devuelve 429 sin dejar
  registros parciales. Repetir una entrega no consume otro cupo.
- Sigue existiendo una entrega en curso por equipo/participante individual,
  entre todas las misiones. Los reintentos se agregan al final mediante queued_at.
- El worker despacha FIFO global con hasta dos tareas. Los leases condicionales
  impiden que otro worker reclame la misma entrega. El límite final lo aplica
  también el proceso runner, no solo el worker.
- Cuando no hay memoria/cupos o el runner responde ocupado, conserva la entrega
  en espera sin quemar un intento. Un lease interrumpido vuelve a cola. Una
  entrega que espera más de 30 minutos termina bloqueada con queue_timeout y
  libera su cupo; puede reenviarse con retry si la misión sigue activa.
- Finalizar una entrega, liberar capacidad y conceder puntos forman parte de
  una transacción. Repetir el resultado no duplica puntos ni resta capacidad dos
  veces. Las aprobaciones exigen lease vigente y evidencia del juez oficial.
- Arena muestra posición y tamaño de cola **dentro del evento**; otros eventos
  también pueden ocupar cupos globales. El instructor ve espera y ejecución de
  su evento. No es una promesa de tiempo exacto.
- El portal consulta cada 6–9 segundos, con desfase por cliente y sin polling de
  pestañas ocultas. Solo entregas preparing/running abren SSE; 50 entregas en
  espera no abren 50 streams de un segundo.
- Actions muestra cambios de posición y renueva OIDC al consultar. Los kits se
  ampliaron a 50 minutos de espera para no abandonar la cola a los 25 minutos.
- Nginx admite una ráfaga de registro de 60 solicitudes y 30/min después de ella,
  más 40 solicitudes API/segundo con ráfaga de 150. Son límites por IP compartida
  compatibles con el escenario de universidad probado; no se eliminó el control.

## Configuración

Los valores predeterminados funcionan sin editar secretos. Variables opcionales
en `infra/edge/.env`:

```dotenv
EVALUATION_QUEUE_LIMIT=50
EVALUATION_CONCURRENCY=2
EVALUATION_QUEUE_WAIT_SECONDS=1800
```

Recrea API, worker y runner usando ambos archivos Compose cuando cambien esos
valores; el frontend usa same-origin. Al migrar desde la versión anterior,
espera a que no queden entregas antiguas en pending/preparing/running antes de
activar el contador. En este despliegue se comprobó que había cero.

La cola está en el volumen persistente `arena-data`; no uses `down -v` para
reiniciar. El worker tiene gracia de parada de diez minutos para terminar las
VMs en curso y no reclamar trabajo nuevo durante el cierre. Los pendientes
permanecen en almacenamiento, no en una lista de memoria del proceso.

## Verificación local

1. En una tabla temporal: 50 admisiones, 50 repeticiones idempotentes, rechazo
   atómico de la número 51, dos VMs reales simultáneas y rechazo de una tercera.
   Ambas VMs aprobaron misión 03, persistieron etapas y concedieron 20 puntos
   una vez. Un reintento fallido volvió al final de la cola y liberó/reservó
   capacidad correctamente. Duración del escenario: 16,63 segundos.
2. A través de Nginx: evento individual temporal con 50 registros, rechazo de
   capacidad del participante 51 y 300 lecturas autenticadas de dashboard y
   leaderboard. Fueron 352 respuestas satisfactorias, sin 429 ni errores 5xx
   inesperados. Todos usaron la misma IP de cliente simulada para probar el NAT.
   P95 de registro: 1022,8 ms; P95 de lectura: 596,7 ms; lectura máxima: 660 ms.
3. Se eliminaron la tabla, el runner de prueba, el evento y sus participantes.
   No se modificaron eventos, registros ni puntos reales.
4. La suite pasó 168 pruebas y comprueba admisión/cupos, falta de memoria/disco/cgroup, FIFO,
   recuperación, expiración y transacciones de puntuación. TypeScript/Vite pasó.

Estos resultados validan el origen local y dos VMs reales; no son una prueba de
50 VMs, 50 instalaciones OAuth simultáneas ni de la red/Cloudflare del auditorio.
Con evaluaciones de 20–40 segundos, una ráfaga de 50 puede requerir aproximadamente
8–17 minutos con dos cupos; es una estimación, no una garantía para todos los
retos o para código que agote sus timeouts. El taller de una hora debe contemplar
esa espera y permitir trabajar en el código mientras llega el turno.

Los workflows existentes del repositorio de prueba también se actualizaron para
esperar 50 minutos e imprimir cambios de posición, conservando el resto de su
contenido y los handlers del participante.
