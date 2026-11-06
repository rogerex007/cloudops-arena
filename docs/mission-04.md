# Misión 04 — evaluación de resiliencia

La misión usa `aws-event-driven-resilience-v1` y solicita entregas exclusivamente
con OIDC desde `.github/workflows/lab-integration-tests.yml`. Conserva autorización
GitHub App, verificación de blobs del commit, lease, digest, resultado protegido
y transacción de puntos de las misiones anteriores. Una aprobación concede
30 puntos por equipo/misión una sola vez. El kit agrega guía y workflow; no
reemplaza los handlers del participante.

## Contrato del participante

Consulta [la guía descargable](../game-packs/aws-event-driven/starter/mission-04.md).
Orders conserva el contrato de misión 03. Payments e Inventory deben:

- Aceptar una orden nueva usando su clave de negocio `(orderId, service)`.
- Registrar la operación simulada con POST JSON `{service, orderId}` a la variable
  `OPERATIONS_URL`, solo una vez, en el camino que acepta una orden nueva.
- Reconocer duplicados como éxito, sin repetir el POST.
- Reportar únicamente mensajes fallidos mediante `batchItemFailures`.
- En Payments, respetar `FAIL_PAYMENTS=true` antes de escribir o ejecutar la
  operación, para permitir recuperación posterior.

La URL se entrega solo dentro de la VM para misión 04. No es una variable del
operador ni un secreto de GitHub; no la fijes en código. En misión 03 se omite y
los handlers pueden saltarse el POST cuando no esté definida. Los handlers de
referencia incorporan esta llamada opcional; las soluciones antiguas que solo
registran una fila deben adaptarse para demostrar una operación observable.

## Escenarios del juez

1. Repite el flujo funcional de misión 03 con dos órdenes y ambas colas.
2. Comprueba en un registro propio que hubo una operación por servicio/orden.
3. Entrega dos duplicados de la misma orden con nuevos IDs de transporte, en un
   lote SQS. Deben ser éxitos sin incrementar las operaciones.
4. Invoca Payments con un registro válido nuevo y otro inválido. Debe procesar
   el válido y reportar solo el `messageId` inválido.
5. Publica una nueva orden. Inventory debe continuar procesándola.
6. Invoca Payments con el fallo activo. No debe confirmar el mensaje ni registrar
   idempotencia ni operar. El juez no elimina ni copia ese mensaje a la DLQ.
7. Recibe de nuevo el mensaje tras la visibilidad y registra el incremento del
   `ApproximateReceiveCount`. La política nativa SQS de Floci lo traslada a la DLQ.
8. Lee el mensaje de la DLQ, desactiva el incidente y lo vuelve a entregar a la
   cola principal. Payments debe operar una vez; otra copia no debe repetirlo.

La visibilidad es de 1 segundo y `maxReceiveCount=2` para acortar la prueba. No son
valores de producción ni sustituyen la configuración de Terraform del participante.
Si no hay evidencia de redrive nativo, el juez bloquea la evaluación; no fabrica
una aprobación copiando manualmente el mensaje a la DLQ.

## Integridad del registro de operaciones

El juez root inicia un receptor HTTP en loopback con puerto efímero. Solo admite
POST acotados, con service y orderId válidos. El registro vive en memoria root,
no ofrece lectura, borrado ni reset. El juez vincula las operaciones al servicio
que está invocando: Inventory no puede registrar un pago y Orders no puede
adelantar las operaciones de sus consumidores. Los intentos de atribución
incorrecta impiden aprobar aunque el handler ignore el error HTTP.

El receptor cuenta todas las operaciones aceptadas, incluso duplicadas. El juez
compara el contador completo con las operaciones esperadas, cierra el receptor,
espera los requests pendientes acotados y vuelve a comprobarlo antes de emitir
el resultado. No se usa stdout del participante ni una sola fila DynamoDB como
prueba de unicidad. El módulo de pruebas es root-only, igual que los canales de
evidencia/progreso. Los handlers siguen ejecutándose como UID 2000, con límites
y eliminación del grupo de procesos tras cada invocación.

## Límites

Es una prueba de integración con operaciones de negocio simuladas y Floci en
KVM sin red externa. El juez implementa un adaptador de invocación/acuse que
respeta excepciones y `batchItemFailures`; no ejecuta Lambda ni prueba su backoff
o event source mapping gestionado. No aplica Terraform del participante, no cobra
pagos reales ni despliega recursos AWS.

Los duplicados se prueban de forma secuencial y en lote. No demuestra seguridad
ante todas las carreras concurrentes ni exactamente-una-vez en producción. Una
caída entre marcar idempotencia y efectuar un pago externo requiere un protocolo
adicional (outbox, estados, reconciliación); el fallo de este reto ocurre antes
de ambos. La VM y todos los datos emulados se eliminan al terminar.

## Validación local

La VM de prueba aprobó duplicados, lotes parciales, continuidad de Inventory,
recepciones SQS `[1, 2]`, DLQ nativa y recuperación. Rechazó una escritura sin
condición que repetía operaciones, un Payments que ignoraba FAIL_PAYMENTS y una
solución que solo escribía idempotencia sin realizar la operación simulada.

La imagen final también verificó el resultado real, progreso persistido y 30 puntos
atómicos en una tabla temporal; repetir el resultado no duplicó puntos. La tabla
se eliminó al terminar. Las regresiones reales de misiones 02 y 03 aprobaron;
la suite de API pasó 157 pruebas.

El worker espera hasta 60 segundos ante un 409 del runner ocupado antes de bloquear
una entrega, dentro de su lease de ejecución. El workflow de misión 04 habilita
retry al usar Re-run jobs; el backend sigue limitando cada entrega a cinco intentos.
Se agregaron workflow y guía a `rogerex007/gameday-roger-mesa`, conservando sus
handlers. El primer disparo coincidió con una prueba interna y quedó bloqueado;
se corrigieron la espera y el reintento antes de lanzar una nueva ejecución.

La nueva ejecución real de Actions llegó al juez y aprobó el flujo funcional de
misión 03; fue rechazada en operaciones únicas porque los consumidores actuales
solo registran idempotencia y aún no incorporan OPERATIONS_URL. No se copiaron
soluciones ni se alteraron sus puntos para aprobar la prueba.
