# Misión 02: validar y desplegar desde Actions

La misión conserva el punto por vincular el repositorio y los 14 puntos técnicos.
Las nuevas entregas tienen dos operaciones independientes: `plan` valida sin
puntuar ni crear una entrega completada; `deploy` revisa y aplica la infraestructura
y solo puede puntuar después de verificar su persistencia. Las aprobaciones
anteriores se conservan: el participante puede desplegar aunque ya tenga puntos,
pero no vuelve a recibirlos.

## Participante

1. Descarga el kit de misión 02, revisión 3. Si ya tienes código, actualiza solo
   `.github/workflows/terraform-lab.yml`; conserva Terraform y tus handlers.
2. Al final del workflow, descomenta el bloque `Desplegar la infraestructura en
   Arena` con `ARENA_OPERATION: deploy`. No cambies la indentación. El README del
   kit incluye el bloque completo. Conserva `ARENA_EVENT_ID` y la autorización App.
3. Guarda los cambios y ejecuta **Validar y desplegar laboratorio en Arena** en la
   rama predeterminada. La misión 02 debe estar activa y el evento abierto.

El primer paso escribe un cliente OIDC en el directorio temporal del runner y
valida el plan; el segundo usa ese cliente para solicitar el apply del mismo
commit. No ejecuta Terraform en GitHub ni entrega claves AWS al alumno. Un workflow
que solo valida puede aparecer verde, pero deja la misión pendiente de despliegue.
El inventario solo aparece después del apply aprobado, con repositorio y commit.

## Ejecución y procedencia

Actions envía `operation: plan|deploy` por la ruta OIDC existente. El SHA sigue
proviniendo del JWT firmado. La identidad de la evaluación incorpora la operación;
plan y deploy del mismo commit no se confunden. GitHub App verifica cada blob de
los siete archivos autorizados. En modo deploy, el worker elige el contrato
`aws-event-driven-deploy-v1`, no el juez efímero de planes.

El gestor privado recibe esos archivos y su digest, nunca comandos. Crea un disco
por evaluación/digest/intento, separado de los templates de referencia, y monta
un ISO de solo lectura. El guest verifica otra vez los hashes, copia únicamente
esa fuente y revisa HCL/plan. Terraform corre como UID 2000, con proveedores
precargados y los parámetros autorizados de Floci. La VM no tiene NIC externa,
credenciales reales ni socket Docker del host. Los runtimes Lambda y su Docker
permanecen dentro de la VM.

Después de aplicar el plan guardado, el juez consulta recursos, apaga la VM,
la reanuda y vuelve a comprobar el inventario. El host conserva el digest, commit,
evaluación y resultado. El worker valida ese vínculo y publica `DEPLOY#{teamId}`
en **la misma transacción** que el resultado, la finalización de misión y el
puntaje cuando corresponda. Revalida lease, evento abierto, miembros, repositorio
y autorización. Un fallo no publica un recibo; el API no muestra un inventario
sin recibo y metadatos coincidentes en el gestor.

El registro nuevo no exige una migración destructiva. Un retry usa una generación
nueva sin consumir otro cupo de participación. Un candidato rechazado no reemplaza
el laboratorio vigente y se limpia en cinco minutos o al reintentar. Solo después
del recibo canónico se activa un sucesor y se retiran los discos anteriores.
La reconciliación periódica recupera ese cambio si se pierde el acuse del worker.
El cupo de 50 ahora cuenta participaciones; siguen siendo dos VMs compartidas
activas. Véase [relojes, cupos y operación](workshop-experience.md).

## Validación y límites

El transporte convierte explícitamente el contador de intento leído de DynamoDB
(`Decimal`) a entero JSON antes de llamar al gestor. La regresión reproduce el
tipo real de boto3, no un contador nativo creado por una fixture. Un fallo de
serialización ocurre antes del apply y no debe interpretarse como error Terraform.

La prueba de integración usó fuentes conocidas y registros sintéticos, sin otorgar
puntos a usuarios reales. Verificó una VM positiva con apply y persistencia, una
negativa rechazada por política, recibo/inventario coincidentes, 14 puntos una sola
vez, plan con cero puntos y compatibilidad con una aprobación anterior. Véase
[el informe](validation/mission-02-deploy-2026-11-06.json).

Una solicitud real de deploy registrada con OIDC falló inicialmente por la
serialización del intento Decimal. Tras corregir el transporte se recuperó su
mismo commit por la cola normal: terminó en `terraform_deployment_passed`, publicó
recibo e inventario coincidentes y no repitió puntos de una aprobación anterior.
El job original de GitHub ya había terminado con error; su conclusión no cambia
retroactivamente. Un nuevo Run workflow permite comprobar el job completo verde.
OIDC/selección de operación y
aislamiento de procedencia tienen pruebas de API. Los despliegues no prueban la
lógica de los handlers ni completan misiones 03/04: sus evaluadores actuales
siguen usando fixtures efímeras. Actualizar Orders e incidentes sobre este mismo
playground es el siguiente trabajo. El pack de una hora continúa en borrador.
