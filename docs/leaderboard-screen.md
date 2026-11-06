# Clasificación para proyectar

En `/instructor`, abre **Clasificación → Abrir marcador**. El botón genera o
recupera un enlace del evento con formato `/clasificacion/<identificador>` y lo
abre en otra pestaña. Compártelo con la pantalla del auditorio. Esa pantalla no
requiere sesión; usa **Pantalla completa** para proyectarla.

El enlace permite ver los nombres de clasificación y puntos, el título del
evento y la misión activa. No expone correos, repositorios, IDs internos, entregas,
claves ni sesiones. Generarlo no cambia puntos ni el estado del evento.
**Desactivar enlace público** invalida el enlace; al abrir de nuevo se genera otro.
Los enlaces son por evento, no una selección automática del último evento.

La pantalla consulta el marcador cada 3 segundos, sin solapar peticiones. Muestra
la hora de la última lectura y avisa si se pierde conexión; un enlace revocado
oculta la clasificación. A igual puntaje, gana la posición quien alcanzó ese puntaje primero según sus
respuestas aprobadas. Todos los marcadores usan el mismo criterio. Si el evento
termina, conserva el resultado final. No se trata de una transmisión por WebSocket:
el cambio se refleja en la siguiente consulta correcta.

## Implementación

- `POST /api/v1/admin/events/{event_id}/leaderboard-screen`: solo instructor;
  token aleatorio de 192 bits y actualización `if_not_exists` para aperturas
  concurrentes. Guarda `leaderboard_token` en META y un índice `SCREEN#token`.
- `DELETE` en la misma ruta: revoca el token y elimina su índice.
- `GET /api/v1/screens/{token}`: lectura pública, consulta directa del índice y
  partición del evento, comprobación de vigencia y campos expresamente permitidos.
- Respuestas y HTML de proyección con `no-store`; la ruta HTML también usa
  `no-referrer` y `noindex`. No hay nuevas variables ni secretos de configuración.
- La política de Cloudflare debe conservar públicas las rutas de participante;
  el marcador no necesita un Bypass adicional si solo `/instructor` y las APIs
  admin están protegidas como en la configuración actual.

## Arquitectura y diseño

El portal recupera el estilo oscuro y las tarjetas de Arena. Los cuatro textos
de misión se conservan. El pack de una hora incluye un diagrama declarativo
`architecture`, presentado por un componente SVG interactivo: Orders, EventBridge,
dos colas y DLQ, Payments/Inventory y **una tabla compartida de idempotencia**,
además de Orders. API Gateway, notificaciones y CloudWatch no se dibujan como
recursos implementados porque no pertenecen al alcance verificado actual.
La pestaña Infraestructura conserva el inventario de la entrega; el diagrama es
una explicación del ejercicio. Las misiones 03/04 todavía usan recursos efímeros.

Validado con pruebas de publicación/revocación, privacidad, empates y cambios de
puntos, además de Firefox a 1440×1000 y 390×844. Se verificó una actualización real
sin recargar usando únicamente un evento sintético, eliminado al terminar.

## Desempate por tiempo de respuesta

La clave es puntos descendentes y hora de la última respuesta que aportó puntos
ascendente. Quiz y vínculo de repositorio usan sus recibos de puntos del servidor;
las nuevas aprobaciones técnicas guardan `answered_at` con la hora original de
recepción de la entrega, junto al recibo atómico. No cuenta el tiempo en cola ni
la fecha del commit del participante. Los reintentos sin puntos no alteran la
prioridad. No es un bono de velocidad ni cambia los puntos existentes.

Para aprobaciones históricas sin `answered_at` se usa `created_at` del recibo de
puntos; por tanto, aquellas sí pueden incluir espera del evaluador. Si falta
historial fiable, se coloca después de quienes tienen tiempo verificable a igual
puntaje. Coincidencias exactas se ordenan por ID estable, sin usar la fecha de
registro. El saldo de cero puntos no otorga prioridad por registrarse primero.
