# Misión 03 — evaluación funcional desde GitHub Actions

Las entregas técnicas se solicitan exclusivamente mediante OIDC desde GitHub
Actions. El POST de SHA del portal devuelve 410 y el portal solo muestra etapas,
resultado y enlace a la ejecución. El scoring legacy por webhook está desactivado
por defecto. Los quizzes y la vinculación del repositorio conservan su interfaz.
No se borran aprobaciones ni puntos anteriores.

## Participante

1. Con la misión 03 activa, descarga **Guía y workflow de la misión 03**.
2. Agrega `.github/workflows/app-integration-tests.yml`; el ZIP no reemplaza tus
   handlers ni Terraform. Consulta `MISSION-03.md` para los contratos completos.
3. Implementa Orders, Payments e Inventory en los tres `handler.py` del kit inicial.
4. Conserva `ARENA_EVENT_ID` y la autorización de la GitHub App. Ejecuta **Actions
   → Evaluar misión 03 en Arena → Run workflow**, o guarda cambios en la rama
   predeterminada para dispararlo por push.
5. Reintenta el mismo commit fallido con `retry` en Run workflow; los nuevos
   commits generan entregas nuevas. Hay una evaluación en curso por equipo y un
   máximo de cinco intentos por entrega. Aprobar concede 20 puntos una sola vez.

El workflow de misión 02 sigue ligado a esa misión: un push puede disparar ambos,
y el que no corresponda a la misión activa será rechazado sin conceder puntos.

## Qué ejecuta el juez

`aws-event-driven-runtime-v1` recibe únicamente los tres archivos Python del
commit verificado. Arranca una VM desechable sin NIC y Floci en loopback. El juez
root prepara una tabla de órdenes, una tabla con clave compuesta `eventId/service`,
un bus y regla EventBridge y dos colas SQS con políticas restringidas a esa regla.
Los nombres y datos de las órdenes se generan por ejecución.

Orders se invoca dos veces, con JSON normal y base64, como UID 2000 en procesos
con límites de tiempo, CPU, archivos y procesos. El juez comprueba la respuesta
201 y los datos persistidos en DynamoDB. Lee los mensajes entregados por
EventBridge a ambas colas y verifica source, detail-type y datos de cada orden.
Luego entrega lotes SQS a Payments e Inventory y comprueba sus registros de
procesamiento y `batchItemFailures=[]`. Una respuesta de éxito sin esos efectos
no aprueba. Los procesos descendientes se eliminan después de cada invocación.

No se instala código ni dependencias del repositorio. El juez incorpora boto3
1.38.18 en la imagen. El módulo de pruebas es root-only y no se incluye en los
kits. Los canales virtio de resultado/progreso siguen root-only. La API recibe
un resultado con run_id, digest del código y validador; el worker solo acepta la
pareja misión/validador/código oficial. La transacción condicional registra SUB,
20 puntos y libera el slot sin duplicados. Se conserva la autorización App y el
control de membresía al conceder puntos.

## Alcance de la evidencia

Se comprueba integración de handlers con DynamoDB, EventBridge y SQS de Floci.
El juez invoca handlers como procesos Python: **no utiliza el servicio Lambda,
API Gateway ni event source mappings**, no aplica el Terraform del participante
y no demuestra un despliegue AWS. Esas capacidades requieren validación adicional.
La infraestructura de prueba es controlada por el juez, separada del plan de
misión 02. Duplicados, reintentos, fallos inyectados y DLQ siguen pendientes para
misión 04. La VM, sus datos y los recursos emulados desaparecen al finalizar.

## Verificación

Una VM real aprobó los handlers de referencia con dos órdenes y rechazó una
respuesta 201 sin persistencia y un consumidor que solo devolvía éxito. Las pruebas
unitarias comprueban contratos, números malformados, correspondencia de validador,
puntos de misión 03 y contenido del ZIP. El workflow y la guía se añadieron a `rogerex007/gameday-roger-mesa`. Su primera
ejecución real por GitHub/Cloudflare/OIDC alcanzó el juez y rechazó correctamente
Orders, que aún contiene `raise NotImplementedError`. Los handlers se mantienen
como ejercicios; no se copiaron soluciones oficiales. La imagen final también
aprobó la regresión de misión 02. La suite pasó 142 pruebas y el portal pasó
TypeScript/Vite. Una tabla temporal verificó un resultado real de VM, progreso,
20 puntos atómicos y rechazo de repetición; se eliminó al terminar.
