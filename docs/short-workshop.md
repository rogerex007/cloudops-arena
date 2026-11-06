# Taller de una hora

`aws-event-driven-60` v1.0.0 es el programa predeterminado para eventos nuevos.

| Misión | Duración | Puntos | Evidencia |
| --- | --- | --- | --- |
| Entiende el recorrido | 5 min | 10 | Quiz validado por API |
| Despliega la infraestructura | 15 min | 15 | Repositorio (1) y apply aislado verificado (14) |
| Implementa Orders | 20 min | 20 | Handler y recorrido básico en recursos temporales |
| Evita duplicados y recupera el flujo | 15 min | 30 | Duplicados, fallos parciales, reintentos y DLQ |

Los 5 minutos restantes son para cierre. Los relojes de las misiones son
controlados por el instructor y el servidor; cambiar el programa no reinicia
un reloj existente. Se conservan IDs y contratos de evaluación del pack anterior.
No se reescalan puntos a 100.

## Materiales y límites

Cada archivo de los ZIP está dentro del nuevo pack. Las rutas del repositorio
participante continúan siendo `game-packs/aws-event-driven/` para mantener los
workflows y validadores compatibles. Orders comienza incompleto. Payments e
Inventory están preparados para el recorrido básico, con protección contra
duplicados pendiente: completar Orders aprueba la tercera, pero requiere un
cambio real en los consumidores para aprobar la cuarta. No sobrescribas una
solución propia de consumidores al descargar el nuevo kit.

La misión 02 despliega recursos persistentes a través del gestor privado y publica
inventario únicamente tras comprobar procedencia y persistencia. Las 03/04
siguen usando handlers en recursos efímeros de prueba; no actualizan las Lambdas
persistentes ni representan incidentes sobre ese mismo despliegue. AWS Control
Tower real, terminal/editor integrado y 50 VMs simultáneas no están implementados.

## Cambio de programa sin borrar progreso

Desde instructor, selecciona el programa en «Programa del evento». La interfaz
pausa el evento, solicita `POST /api/v1/admin/events/{event_id}/game-pack` y
restaura el estado abierto. La API exige rol admin, evento pausado o terminado,
misión activa compatible, contratos de puntos/workflow iguales y ninguna entrega
en cola o en ejecución. Solo actualiza META mediante condición de concurrencia.
No modifica entregas, equipos, aprobaciones, compras ni puntos. Los créditos
históricos de misiones retiradas siguen contando para las monedas ya ganadas.

En este despliegue se migraron únicamente los dos eventos que estaban abiertos;
se compararon sus registros de progreso antes y después sin cambios. El pack de
seis misiones permanece disponible y los eventos terminados conservan su historial.

## Interfaz y comprobaciones

El espacio del participante recupera el estilo oscuro con tarjetas de Arena y
pestañas Misión, Arquitectura, Infraestructura, Actividad y Clasificación. Pistas, instrucciones de descarga y
configuración de Actions se abren bajo demanda. El inventario vacío no presenta
recursos de referencia como si fueran despliegues del alumno.

Validación: 221 pruebas API, 8 pruebas web, TypeScript/Vite, Firefox a 1440×1000 y
390×844 sin desplazamiento horizontal. En VMs reales, Orders resuelto con los
consumidores preparados aprobó runtime-v1 y falló resilience-v1 como se esperaba.
No se concedieron puntos a participantes durante esas pruebas.
