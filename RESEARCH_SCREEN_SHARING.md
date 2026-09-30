# Reto universal: screen sharing sin app

**Pedido:** enviar a un cliente un enlace que abra desde su teléfono sin instalar
nada; tras dar permiso, poder ver su pantalla **mientras navega por otros sitios
o aplicaciones**, para guiarlo remotamente.

**Respuesta corta:** en iPhone eso no es posible hoy, y no por una limitación de
producto sino de plataforma. En Android tampoco desde un navegador. En desktop sí,
con matices. La parte que rompe el requisito no es "ver la pantalla" sino **"mientras
navega por otras aplicaciones"**: ningún navegador móvil expone la captura de
pantalla del sistema a una página web.

Abajo, el detalle, y una propuesta de arquitectura que cubre el ~90 % del valor
real del caso de uso.

---

## 1. ¿Qué es técnicamente posible?

### En desktop: sí, y es la única plataforma donde el requisito se cumple casi literal

La API estándar es `navigator.mediaDevices.getDisplayMedia()`, de la
[Screen Capture API del W3C](https://www.w3.org/TR/screen-capture/). Desde una
página web, sin instalar nada:

- El usuario elige qué compartir en un selector **del navegador**, no de la
  página: una pestaña, una ventana de aplicación concreta, o la pantalla completa.
- Si elige pantalla completa, el stream **sigue mostrando lo que haga en otras
  aplicaciones**, incluso fuera del navegador. Aquí sí se cumple el "mientras
  navega por otros sitios".
- El `MediaStream` resultante se envía por WebRTC a un agente que lo ve en vivo.

Dos condiciones que la especificación impone y que conviene conocer antes de
diseñar el flujo:

- **Contexto seguro (HTTPS).** La API no existe en HTTP.
- **Activación transitoria.** La llamada tiene que originarse en un gesto real
  del usuario (un clic). Si no, lanza `InvalidStateError`. No se puede pedir la
  pantalla al cargar la página, ni "reanudar" la captura automáticamente después.
  Esto es deliberado y tiene consecuencias de producto: **cada** sesión necesita
  un clic, y si el stream se corta hay que pedir otro.

Soporte en desktop: Chrome 72+, Firefox 66+, Safari 13+. Es estable desde hace
años.

### En móvil: no

Ni iOS ni Android exponen `getDisplayMedia` a páginas web. No es que funcione
peor: **la API no está**, así que `navigator.mediaDevices.getDisplayMedia` es
`undefined` y no hay permiso que el usuario pueda conceder.

---

## 2. ¿Qué no es posible?

Conviene separar tres cosas que se confunden, porque solo la tercera es la que
pide el reto:

| | desde una web en móvil | desde una app nativa |
|---|---|---|
| Ver la **cámara** del cliente | ✅ `getUserMedia` | ✅ |
| Ver **una página de nuestro sitio** que el cliente tiene abierta | ✅ co-browsing (ver §4) | ✅ |
| Ver **la pantalla del sistema**, incluidas otras apps | ❌ **imposible** | ✅ con trabajo |

Lo que **no** es posible, y no tiene workaround:

1. **Captura de pantalla del sistema desde un navegador móvil.** Ni iOS ni
   Android. No hay flag, ni permiso, ni truco.
2. **Captura persistente sin gesto por sesión.** Incluso en desktop, la
   activación transitoria impide iniciar o reanudar la captura sin un clic.
3. **Ver otras apps desde una web, en cualquier plataforma móvil.** Es una
   frontera del modelo de seguridad del sistema operativo, no del navegador: una
   página web es contenido no confiable y el sandbox de la app del navegador no
   puede ver fuera de sí misma.
4. **Control remoto del teléfono** (no lo pide el reto, pero suele pedirse
   después): tampoco desde web. Requiere MDM, o accesibilidad concedida a una app
   nativa.

Y una advertencia de producto sobre el propio requisito: "ver su pantalla
mientras navega por otras aplicaciones" significa poder ver su banca, su
WhatsApp y sus notificaciones. Aun si fuera técnicamente posible, es un alcance
que conviene no querer: aumenta el riesgo de capturar datos que no deberíamos
tener y, en un contexto de seguros, probablemente entra en conflicto con las
obligaciones de tratamiento de datos. La restricción de la plataforma empuja
hacia un diseño mejor.

---

## 3. Diferencias entre iPhone, Android y desktop

### iPhone / iPad — el caso más cerrado

`getDisplayMedia` no está implementada en WebKit, y en iOS **todos** los
navegadores usan WebKit por obligación: "Chrome en iPhone" es Safari con otra
interfaz, así que hereda exactamente la misma limitación. Cambiar de navegador no
cambia nada.

La única vía para captura de pantalla a nivel de sistema es **ReplayKit** con una
*Broadcast Upload Extension*, y eso exige:

- una **app nativa** publicada en la App Store (una extensión de broadcast solo
  se distribuye dentro de una app contenedora),
- que el usuario la instale, y
- que inicie el broadcast desde el Centro de Control de iOS.

O sea, lo contrario de "un enlace sin instalar nada". Además la extensión corre
en un proceso aparte con un **límite duro de 50 MB de memoria**: si se pasa, el
sistema la mata. Es una restricción real de ingeniería, no un detalle.

### Android — cerrado en web, viable en nativo

Chrome para Android **no** implementa `getDisplayMedia`. La captura de pantalla
existe a nivel de sistema vía **`MediaProjection`**, pero solo para apps nativas,
y con requisitos que se han endurecido:

- desde Android 10, hay que tener un **foreground service** corriendo y haber
  llamado a `startForeground` con su notificación antes de obtener la
  `MediaProjection`; si no, `SecurityException`;
- apuntando a Android 14+, hay que declarar el tipo de foreground service
  `mediaProjection` en el manifiesto y **obtener consentimiento en cada sesión**,
  con un diálogo que ofrece compartir una sola app o la pantalla completa.

Android es menos hostil que iOS (se puede distribuir fuera de la tienda, hay APK
directo), pero sigue necesitando **una app instalada**.

### Desktop — donde sí funciona

`getDisplayMedia` con las tres opciones de alcance (pestaña, ventana, pantalla).
Diferencias operativas que afectan al soporte:

- **macOS** exige además permiso de *Grabación de pantalla* al navegador en
  Ajustes del Sistema, y la primera vez suele requerir **reiniciar el navegador**.
  Es la causa más común de "le di permiso y no funciona".
- **Chrome/Edge** ofrecen la mejor experiencia y permiten compartir audio de
  pestaña; **Safari** es el más restrictivo; **Firefox** va bien.
- **Wayland en Linux** enruta la captura por el portal de xdg-desktop-portal, lo
  que cambia el selector y puede fallar en configuraciones antiguas.

---

## 4. Si lo exacto no es posible, ¿qué construiría?

Un **enlace único que se adapta a la plataforma**, con tres niveles de
degradación. La clave del diseño: no hay una solución, hay una escalera, y el
enlace elige el escalón más alto disponible sin que el cliente tenga que entender
por qué.

```
                    El cliente abre el enlace
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
          DESKTOP          MÓVIL            MÓVIL
                        (nuestro sitio)   (necesita ver otra app)
              │               │                │
     getDisplayMedia     Co-browsing      Cámara + guía
      (pantalla real)   (DOM mirroring)   (apunta el teléfono)
              │               │                │
              └───────────────┴────────────────┘
                              ▼
                   Misma sesión, mismo agente,
                    misma grabación auditable
```

### Nivel 1 — Desktop: `getDisplayMedia` + WebRTC

Lo que el reto pide, literal. Un clic, el selector del navegador, y el agente ve
la pantalla por WebRTC. Se le pide explícitamente "compartir pantalla completa"
cuando el problema está fuera del navegador.

### Nivel 2 — Móvil, y el problema está en *nuestro* sitio: co-browsing

Este es el nivel que resuelve la mayoría de los casos reales, y el que yo
priorizaría construir primero.

En vez de capturar píxeles, se **replica el DOM**: un SDK JavaScript en nuestra
página serializa el estado del DOM y lo transmite; el agente ve una réplica fiel
en su navegador, en vivo, con scroll y clics del cliente. Sin instalar nada, en
cualquier móvil, iPhone incluido.

Tres ventajas sobre el screen sharing que lo hacen mejor, no solo posible:

- **Funciona en iPhone**, porque es solo JavaScript en nuestra propia página.
- **Enmascara PII selectivamente.** Se pueden marcar campos (número de póliza,
  documento de identidad, tarjeta) para que lleguen ofuscados al agente. Con
  captura de píxeles esto no se puede hacer: el agente ve lo que hay.
- **Permite interacción, no solo observación.** El agente puede señalar un campo
  o, con permiso, rellenarlo. Para "guiarlo remotamente" esto es *más* útil que
  mirar.

Su límite es claro y hay que decirlo: **solo ve nuestro sitio**. Si el cliente se
va a su correo a buscar un código, desaparece de la vista.

### Nivel 3 — Móvil, y el problema está fuera de nuestro sitio: la cámara

Cuando el cliente necesita mostrar algo que no está en nuestra web (un SMS con un
código, un error de su banca, un documento en papel), el sustituto que sí
funciona en todo teléfono es **`getUserMedia` con la cámara trasera**: el cliente
apunta el teléfono a lo que sea y el agente lo ve por WebRTC.

Es menos elegante que capturar la pantalla, pero resuelve el caso de uso
subyacente — *"no entiendo qué estoy viendo, mírame esto"* — y funciona hoy, sin
instalar nada, en iPhone y Android.

### Lo que tendría en común toda la escalera

- **Un solo enlace** con token de un uso y caducidad corta. El cliente no elige
  modo: la página detecta capacidades (`typeof navigator.mediaDevices?.getDisplayMedia === 'function'`)
  y ofrece el mejor disponible.
- **Consentimiento explícito y visible**, con un indicador permanente de "estás
  compartiendo" y un botón de cortar siempre a la vista.
- **WebRTC** para el transporte, con SFU para poder grabar y para que entre más
  de un agente.
- **Auditoría**: quién vio qué, cuándo, con qué consentimiento. En seguros esto
  no es opcional.
- **Honestidad en la UI sobre iPhone.** No prometer captura de pantalla y fallar:
  ofrecer directamente co-browsing o cámara, explicando en una línea por qué.

### Lo que NO construiría

- **Una app nativa solo para esto.** Técnicamente resuelve el requisito literal
  (ReplayKit / MediaProjection), pero el requisito real era "sin instalar nada".
  Pedirle a un cliente que instale una app para una llamada de soporte destruye
  la tasa de conversión que justificaba el enlace. Solo tendría sentido si ya
  existe una app propia con adopción alta — y en ese caso, se añade ahí.
- **Soluciones que piden desactivar protecciones** del navegador o del sistema.

---

## Resumen ejecutivo

| Requisito | ¿Posible? | Cómo |
|---|---|---|
| Enlace sin instalar app | ✅ | web + WebRTC |
| Ver pantalla en **desktop**, incluidas otras apps | ✅ | `getDisplayMedia` |
| Ver pantalla en **móvil**, incluidas otras apps | ❌ | imposible desde web; requiere app nativa |
| Ver **nuestro sitio** en móvil, en vivo | ✅ | co-browsing (DOM mirroring) |
| Ver **algo físico o de otra app** en móvil | ⚠️ parcial | cámara trasera vía `getUserMedia` |
| Controlar el dispositivo remotamente | ❌ | requiere MDM o app con accesibilidad |

La recomendación: **construir la escalera de tres niveles**, priorizando el
co-browsing, que es el que cubre la mayor parte del valor en móvil y además
aporta enmascarado de PII e interacción — dos cosas que el screen sharing de
píxeles no puede dar.

---

## Fuentes

Especificaciones y documentación de plataforma:

- [W3C — Screen Capture API](https://www.w3.org/TR/screen-capture/) — la especificación de `getDisplayMedia`.
- [MDN — `MediaDevices.getDisplayMedia()`](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getDisplayMedia) — requisito de contexto seguro y de activación transitoria (`InvalidStateError`).
- [MDN — Using the Screen Capture API](https://developer.mozilla.org/en-US/docs/Web/API/Screen_Capture_API/Using_Screen_Capture) — guía de uso y opciones de alcance.
- [caniuse — `getDisplayMedia`](https://caniuse.com/?search=getDisplayMedia) — tabla de soporte por navegador y plataforma.
- [Android Developers — Media projection](https://developer.android.com/media/grow/media-projection) — `MediaProjection`, foreground service obligatorio desde Android 10 y consentimiento por sesión en Android 14+.
- [Microsoft Learn — `ForegroundServiceTypeMediaProjection`](https://learn.microsoft.com/en-us/dotnet/api/android.content.pm.serviceinfo.foregroundservicetypemediaprojection) — declaración del tipo de servicio en el manifiesto.

Sobre la ausencia de soporte en iOS y el camino nativo:

- [Chromium Issues — Screen Capture for iOS (getDisplayMedia)](https://issues.chromium.org/issues/40753589) — confirma que iOS no lo expone y que Chrome iOS hereda WebKit.
- [BigBlueButton #8576 — Safari and iOS Safari: implement Screen Capture API](https://github.com/bigbluebutton/bigbluebutton/issues/8576) — historial del problema en un producto real.
- [Apple Developer Forums — Broadcast Upload Extension](https://developer.apple.com/forums/thread/794009) — comportamiento y límites de la extensión de broadcast.
- [Fora Soft — iOS Screen Sharing: ReplayKit + Broadcast Extension](https://www.forasoft.com/blog/article/how-to-implement-screen-sharing-in-ios-1193) — el límite de 50 MB del proceso de la extensión y la necesidad de app contenedora.
- [WebRTC.ventures — Safari: A WebRTC Screen Sharing Story](https://webrtc.ventures/2020/01/safari-a-webrtc-screen-sharing-story/) — particularidades de Safari y macOS.

Sobre co-browsing como alternativa:

- [Cobrowse.io — Co-browsing versus screen sharing](https://cobrowse.io/articles/co-browsing-versus-screen-sharing) — diferencia técnica entre replicar DOM y transmitir píxeles.
- [Unblu — Co-browsing vs screen sharing](https://www.unblu.com/en/blog/co-browsing-vs-screen-sharing-whats-the-difference) — alcance y modelo de privacidad.
- [ScreenMeet — Cobrowsing and screen sharing](https://www.screenmeet.com/blog/cobrowsing-and-screen-sharing-the-differences-and-which-is-best) — enmascarado de PII e interacción del agente.
