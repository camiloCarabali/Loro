# Loro — traductor en vivo para entrevistas por videollamada

Contexto del proyecto para Claude Code. Léelo antes de proponer cambios.

## Qué es

**Loro** es una app de escritorio (Windows) que traduce una entrevista por videollamada en
tiempo real, en las dos direcciones, usando el modelo
`gemini-3.5-live-translate-preview` de la Gemini Live API.

- **Entender:** voz del entrevistador -> se muestra el transcript traducido a tu idioma.
- **Hablar:** tu voz -> entra a la llamada traducida al idioma del entrevistador.

El dueño es desarrollador fullstack con base en Python. Prefiere entregas
directas: cuando algo está suficientemente bien, dame los archivos en vez de
seguir iterando. Responde en español.

## Decisiones de arquitectura ya tomadas (no las recuestiones sin razón)

- **Escritorio Python, no web ni Electron.** Un navegador no puede inyectar
  audio en el micrófono de otra app; eso obliga a nivel de SO.
- **UI con pywebview** (HTML/CSS/JS embebido en `app.py`). El hilo principal lo
  toma pywebview; asyncio corre en un hilo daemon. La comunicación Python<->JS es
  vía `js_api` (métodos de la clase `Api`) y `window.evaluate_js(...)`.
- **Dos sesiones simultáneas**, una por dirección. El modelo tiene UN
  `target_language_code` fijo por sesión, así que no se puede hacer bidi en una
  sola conexión.
- **Captura del entrevistador = loopback WASAPI** (`PyAudioWPatch`), NO un cable
  virtual. Captura lo que SUENA en los auriculares del usuario sin instalar nada
  extra. `sounddevice`/PortAudio NO soporta loopback WASAPI — por eso PyAudioWPatch.
- **Lado "entender" es solo-texto** (`player=None`): se muestra el transcript pero
  NO se reproduce audio, para no hacer loop con lo que ya suena en los auriculares.
  Decisión del dueño: con el lag de 2-3 s, leer es más útil que escuchar.
- **Envío de tu voz a la llamada = un VB-Cable** (VB-Audio Virtual Cable, gratis).
  Loro escribe en `CABLE Input`; la app de videollamada usa `CABLE Output` como su
  micrófono. Windows PROHÍBE inyectar audio en el mic de otra app sin un driver
  virtual, así que este cable es inevitable.
- El modelo NO soporta tools, system instructions ni function calling. Es un
  pipeline de traducción puro. No intentes añadirle prompts de sistema.

Ver memoria `loro-audio-routing` para qué alternativas de audio NO funcionaron
(Mezcla estéreo con Bluetooth, mic de auriculares, VoiceMeeter, VB-Cable A+B).

## Formatos de audio (los exige la API, no cambiar)

- Entrada a Gemini: PCM 16-bit, 16 kHz, mono, en chunks de ~100 ms.
- Salida de Gemini: PCM 16-bit, 24 kHz, mono.
- El micro/loopback suele ir a 44.1/48 kHz -> se remuestrea a 16 kHz con scipy.

## Estado actual de los archivos

- `config.py` — tasas e idiomas por defecto de cada dirección.
- `audio.py` — `MicCapture` (entrada sounddevice + remuestreo), `LoopbackCapture`
  (loopback WASAPI con PyAudioWPatch), `Player` (salida con buffer no bloqueante),
  helpers `list_loopback_devices` / `default_loopback_device`. Cada captura expone
  `self.level` (0.0–1.0 RMS) para los medidores de la UI.
- `translator.py` — `TranslationSession`: conecta una captura a un Player (o None)
  vía una sesión Live. `run()` mantiene el audio abierto y reabre solo la conexión
  a Gemini si se cae (reconexión con backoff exponencial). Callbacks `on_transcript`
  y `on_status`.
- `app.py` — punto de entrada principal: UI pywebview + clase `Api` + orquestación
  de las dos sesiones. Reemplaza a `main.py`.
- `main.py` — versión vieja por consola (pide 4 dispositivos). Sigue funcionando
  pero está desactualizada respecto a la arquitectura nueva; usa `app.py`.
- `logo.png` / `logo.ico` — logo de la app (cabecera + ícono de ventana).
- Auth: `GEMINI_API_KEY` en variable de entorno o en un archivo `.env` (app.py lo
  carga automáticamente al arrancar).

## Funcionalidades ya implementadas

- UI con dos paneles de transcripts en vivo lado a lado, acumulando fragmentos en
  frases (no palabra por palabra).
- Modal de configuración simplificado: micrófono real, cable virtual (auto-detecta
  `CABLE Input`), loopback (auto = salida por defecto de Windows) e idiomas.
- Selector de 12 idiomas por dirección.
- Medidores de nivel de audio (VU) por panel.
- Reconexión automática con estados Conectando / Traduciendo / Reconectando.
- Preferencias persistidas en `loro_prefs.json` (por NOMBRE de dispositivo, los
  índices cambian). Está en .gitignore.
- Atajos: Ctrl+Enter (iniciar/detener) y Esc (detener / cerrar modal).

## Ideas pendientes (opcionales, no urgentes)

- Exportar la transcripción a `.txt` al terminar.
- Mitigar los fragmentos cortos de traducción (limitación de la API).
- Empaquetar como `.exe` (pulido prematuro hasta que se pida).

## Límites conocidos (de la doc de Google)

- Solo entra audio, no texto.
- La voz sintetizada puede cambiar de timbre tras pausas largas o con varios
  hablantes.
- La detección de idioma sufre con acentos fuertes; afecta sobre todo al
  transcript de entrada, no tanto a la traducción.
- Costo API: ~$0.023/min por sesión; dos sesiones ≈ $0.046/min.
