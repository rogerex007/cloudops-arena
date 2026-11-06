# Portal público y consola del instructor

El participante entra en `https://arena.costacorp.net/`; el instructor entra en
`https://arena.costacorp.net/instructor`. La portada no incluye acceso al panel.
La misma SPA reconoce `/instructor` y sus hijos sin introducir otro framework de
rutas. La API conserva la comprobación del JWT/rol de instructor en todas las
operaciones administrativas; conocer la URL no concede permisos.

## Sesiones del navegador

El participante conserva su sesión en las claves locales existentes. El token
de instructor se guarda aparte en sessionStorage, por pestaña; cerrar sesión en
uno no borra al otro. Una sesión antigua de administrador en localStorage se
migra únicamente al abrir `/instructor`, nunca se usa desde la portada pública.
Si ya venció, se limpia y aparece el formulario de instructor. Las credenciales
ADMIN_USERNAME/ADMIN_PASSWORD existentes siguen siendo válidas. No cambies el
.env para separar estas rutas.

Esto separa el estado del navegador, no crea una frontera de seguridad entre
orígenes: ambas páginas comparten hostname y bundle. La autorización real sigue
en la API y en la política de Cloudflare Access.

## Cambiar la aplicación de Cloudflare Access

Hazlo después de desplegar el frontend. Conserva el túnel y el published hostname
`arena.costacorp.net → http://web:80`; no se modifica DNS ni su token.

1. En Zero Trust → Access → Applications, edita la aplicación que actualmente
   protege **todo** `arena.costacorp.net`. Puedes llamarla **Arena Instructor**.
2. En Public hostnames, sustituye la entrada cuyo Path está vacío por las cuatro
   entradas siguientes, todas con Subdomain `arena` y Domain `costacorp.net`:

   | Path (sin barra inicial) | Qué protege |
   |---|---|
   | `instructor` | La entrada exacta del panel |
   | `instructor/*` | Las rutas hijas del panel |
   | `api/v1/admin*` | Las operaciones administrativas, incluyendo el prefijo base |
   | `api/v1/auth/admin*` | El login y las rutas de autenticación de instructor |

3. Mantén una política **Allow → Include → Emails → tu correo** y el método de
   autenticación que ya utilizas. Esa aplicación no debe tener una política
   Bypass/Everyone. Guarda todos los cambios juntos; no elimines antes la
   protección general dejando sin definir las rutas del instructor.
4. Conserva la aplicación **Arena Actions**, cuyo Bypass se limita a
   `api/v1/actions/*`: Arena exige OIDC firmado por GitHub en esa ruta.
5. Si hay otras aplicaciones que protegen el hostname completo, también deberán
   dejar de abarcar la portada. No añadas un Bypass general para `/api/*`: abriría
   además las rutas administrativas en la capa Access.

Los patrones `admin*` cubren también el prefijo base; no son el comodín de toda
la API. Los assets `/assets/*`, el registro de participantes, sus APIs y el callback
GitHub quedan fuera de la aplicación del instructor. Estos últimos conservan
sus comprobaciones de sesión, estado OAuth o firma OIDC según corresponda.

Referencia: [rutas y precedencia de Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/app-paths/).

## Verificación sin sesión Cloudflare

Desde la raíz del proyecto:

```bash
python scripts/check-access-routes.py
```

Se espera 200 HTML en `/`, redirección al login de Cloudflare en `/instructor`,
`/instructor/`, `/api/v1/admin/dashboard` y `/api/v1/auth/admin/login`, y 401 JSON
de Arena en la ruta de prueba Actions. El script no inicia sesión, no sigue las
redirecciones ni imprime cookies/tokens. Usa un User-Agent descriptivo para no
activar el bloqueo 1010 del cliente Python genérico.

Después verifica en el navegador: un participante puede registrarse sin el login
de Cloudflare; abrir `/instructor` solicita Access y luego las credenciales Arena.
Un JWT de participante sigue recibiendo 403 en la API administrativa, incluso si
el navegador ya tiene una sesión válida de Cloudflare del instructor.

## Alcance de los cambios locales

Nginx sirve explícitamente la entrada y sus hijos sin cache y limita los intentos
del login de instructor a 5/min con ráfaga 5, separados del registro masivo de
participantes. Esto no configura por sí mismo la cuenta Cloudflare: las políticas
remotas deben modificarse en el dashboard. Hasta entonces puede seguir apareciendo
el login adicional en la portada.

## Verificación del despliegue local

Pasaron 6 pruebas web de rutas/sesiones, TypeScript y Vite, además de 177 pruebas
de API. En el origen Nginx, `/`, `/instructor` y sus hijos sirvieron HTML; las
rutas de instructor conservaron no-store/nosniff. Una petición administrativa
anónima devolvió 401, un token de participante 403 y un login real de instructor
pudo leer su dashboard (sin modificar datos). El token del participante siguió
recibiendo 403 después del login del instructor.

La primera comprobación pública encontró `/` accesible y la API de dashboard
protegida, pero `/instructor` y el login administrativo todavía sin Access.
Ejecuta el script de nuevo tras guardar las cuatro rutas en Cloudflare; el
código local no puede aplicar esa política de cuenta.
