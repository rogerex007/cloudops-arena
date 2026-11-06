# Entregas con GitHub Actions y progreso en vivo

El workflow del kit revision 2 solicita una evaluación oficial de `mission-02`.
GitHub ejecuta el pequeño job de coordinación en un runner hospedado; el Terraform
se ejecuta en la VM KVM desechable de Arena, sin red. El resultado oficial del
worker concede puntos atómicamente. El éxito de un workflow del participante
nunca sirve como evidencia de aprobación.

## Preparación del operador

1. Mantén configurados la GitHub App y el runner según
   [github-app-and-runner.md](github-app-and-runner.md).
2. En Cloudflare Zero Trust → Access → Applications, añade una aplicación
   **Self-hosted** llamada `Arena Actions` con el mismo hostname
   `arena.costacorp.net` y **Path** `api/v1/actions/*`.
3. Asigna a esa aplicación una política **Bypass**, **Include → Everyone**.
   Esta excepción evita el inicio de sesión interactivo únicamente en la API de
   Actions. La API exige igualmente una identidad OIDC firmada por GitHub.
   Conserva las políticas del portal y de las otras rutas. No amplíes esta
   excepción a `/api/*`, `/internal/*` ni a todo el hostname.
4. Comprueba desde una sesión sin autenticar:
   ```bash
   curl -i https://arena.costacorp.net/api/v1/actions/evaluations/test/test
   ```
   Debe responder **401 JSON**, sin redirigir al login de Cloudflare. Este 401
   confirma que la petición alcanza la autenticación de Arena.
5. Si el túnel tiene activada la validación de JWT de Access en el origen para
   todo el hostname, esa validación también debe respetar la ruta de máquinas;
   no desactives las políticas del portal. La configuración inicial del proyecto
   deja esa opción del túnel en sus valores predeterminados.

La clave privada de la App y el token interno del runner siguen exclusivamente
en los secretos locales existentes. No crees secretos compartidos en los repos
participantes. `ACTIONS_OIDC_AUDIENCE` en la API debe coincidir con `ARENA_URL`
del workflow (por defecto `https://arena.costacorp.net`, sin barra final).

## Preparación del participante

1. Vincula el repo personal y termina **Autorizar GitHub** desde Arena.
2. Descarga el kit actualizado. Si ya tienes soluciones, reemplaza solo
   `.github/workflows/terraform-lab.yml`.
3. En GitHub → Settings → Secrets and variables → Actions → **Variables**, crea
   `ARENA_EVENT_ID` con el identificador mostrado en Arena. No uses el código de
   inscripción. No es un secreto.
4. Con el evento abierto y `mission-02` activa, ejecuta **Actions → Evaluar
   laboratorio en Arena → Run workflow** en la rama predeterminada. Los siguientes
   pushes que cambien el laboratorio o su workflow también disparan entregas.
5. Sigue las etapas en Arena o en los logs de Actions. El enlace de la entrega
   abre la ejecución de GitHub. El job espera hasta 25 minutos y refleja el
   resultado oficial; si vence la espera, consulta Arena antes de reintentar.

Una misión aprobada se omite sin puntos adicionales. Una entrega fallida o
bloqueada del mismo commit requiere `retry` en Run workflow desde Run workflow;
se permiten cinco intentos. Solo hay una entrega en curso por equipo. Un push
mientras hay otra entrega pendiente devuelve 409: espera y lanza Run workflow
para el commit más reciente. No hay cancelación automática de evaluaciones.

## Contrato y límites

- POST `/api/v1/actions/evaluations`: `event_id`, `mission_id`, `retry`.
  El commit y la procedencia se obtienen del JWT, no del JSON recibido.
- GET `/api/v1/actions/evaluations/{event_id}/{evaluation_id}`: estado público,
  limitado al equipo/repositorio autorizado, con JWT OIDC vigente.
- RS256/JWKS del emisor fijo de GitHub, audiencia, expiración, vida máxima de
  diez minutos, IDs inmutables de dueño/repositorio, autorización App vigente,
  miembro, equipo, rama predeterminada y ruta de workflow comprobados. Solo
  `push` y `workflow_dispatch`; los eventos de pull requests se rechazan.
- Un `jti` puede registrar una solicitud una vez; sus marcadores
  `OIDCREPLAY#sha256(jti)` guardan `expires_at`. Habilita TTL sobre ese atributo
  en DynamoDB para retirarlos automáticamente; sin TTL se conservan y siguen
  impidiendo reutilización. Los GET no consumen el token y se pueden repetir.
- El portal descubre nuevas entregas cada cinco segundos y abre un stream SSE
  autenticado por cabecera para la entrega activa. El stream consulta cambios
  cada segundo, emite heartbeats y se reconecta cada 55 segundos. No se ponen
  tokens en URLs. Nginx respeta `X-Accel-Buffering: no`.
- La VM emite códigos fijos de etapa por un canal root separado del resultado.
  El worker guarda mensajes definidos por el servidor, con lease vigente;
  no se retransmite stdout arbitrario. La aprobación llega después de eliminar
  la VM temporal. Las etapas representan **validación y plan**, no recursos
  desplegados: no se ejecuta `apply`, ni se prueban las funciones todavía.
- El juez actual es serial; varios participantes esperan en cola. El tiempo de
  espera y la frecuencia de consultas necesitan pruebas de carga antes del evento.

Prueba de aceptación: primero una misión aún sin aprobar en un evento de prueba,
después un segundo disparo que confirme que no duplica puntos. No borres el
historial ni los puntos reales para repetir esta comprobación.

Referencias: [claims OIDC de GitHub](https://docs.github.com/en/actions/reference/security/oidc),
[precedencia de rutas de Access](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/app-paths/).

## Verificación local (2026-11-04)

La suite de API pasó 133 pruebas, incluidas firmas RSA reales de prueba, identidad
ajena, rama/workflow, repetición de token, scoping y el contrato del stream. La
compilación TypeScript y Vite pasó en la imagen del portal. Una VM real recibió
los siete archivos de la entrega de referencia, transmitió sus etapas y aprobó
el plan en aproximadamente 23 segundos, con solo loopback. El SSE atravesó Nginx
con un estado inicial y otro final separados por dos segundos; los campos privados
no se publicaron. Una tabla temporal de Floci verificó progreso curado, transacción
de puntuación y rechazo de duplicados; se eliminó al terminar.

Estos checks no sustituyen una ejecución real desde el repositorio participante:
queda pendiente configurar la ruta de Cloudflare y disparar el workflow actualizado
con `ARENA_EVENT_ID`. No se alteraron eventos ni puntos reales para las pruebas.

Si Cloudflare devuelve 403 con `error code: 1010` para Python pero el mismo
endpoint devuelve 401 JSON con curl, revisa Browser Integrity Check. El workflow
incluye `User-Agent: CloudOps-Arena-Actions/1.0` para identificarse sin usar el
agente genérico de urllib. Actualiza también ese archivo en el repositorio
participante; reconstruir Arena no cambia los workflows ya descargados.

## Entregas técnicas exclusivamente por Actions

El POST de SHA del portal fue retirado (410); las entregas y reintentos técnicos
se solicitan desde los workflows OIDC. El portal muestra progreso y resultados.
La misión 03 añade su propio workflow y juez: [alcance y contratos](mission-03.md).
El usuario confirmó el recorrido completo de misión 02 por Actions/Cloudflare y
que una segunda ejecución omite la misión aprobada sin duplicar puntos.

## Misión 04

El kit de misión 04 incorpora `lab-integration-tests.yml`, con la misma audiencia,
variable de evento y autorización App. El juez de resiliencia concede 30 puntos
una sola vez. Los consumidores deben registrar operaciones simuladas mediante
`OPERATIONS_URL`; [guía y alcance](mission-04.md). No se usa el anterior runner
self-hosted ni se ejecuta terraform apply desde ese workflow.
