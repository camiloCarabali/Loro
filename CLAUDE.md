# Loro — traductor en vivo para entrevistas por videollamada

Contexto del proyecto para Claude Code. Léelo antes de proponer cambios.

## Qué es

**Loro** es una app de escritorio (Windows) que traduce una entrevista por videollamada en
tiempo real, en las dos direcciones, usando el modelo
`gemini-3.5-live-translate-preview` de la Gemini Live API.

- **Entender:** voz del entrevistador (inglés) -> mis audífonos en español.
- **Hablar:** mi voz (español) -> entra a la llamada traducida a inglés.

El dueño es desarrollador fullstack con base en Python. Prefiere entregas
directas: cuando algo está suficientemente bien, dame los archivos en vez de
seguir iterando. Responde en español.

## Decisiones de arquitectura ya tomadas (no las recuestiones sin razón)

- **Escritorio Python, no web ni Electron.** Un navegador no puede inyectar
  audio en el micrófono de otra app; eso obliga a nivel de SO. `sounddevice`
  (PortAudio) permite elegir el dispositivo de salida exacto, que es lo clave.
- **Dos sesiones simultáneas**, una por dirección. El modelo tiene UN
  `target_language_code` fijo por sesión, así que no se puede hacer bidi en una
  sola conexión.
- **Dos cables de audio virtuales (VB-Cable)** para evitar feedback:
  - Cable 1: app escribe inglés -> es el micrófono que usa Zoom.
  - Cable 2: salida de Zoom (voz del entrevistador) -> la captura la app.
- El modelo NO soporta tools, system instructions ni function calling. Es un
  pipeline de traducción puro. No intentes añadirle prompts de sistema.

## Formatos de audio (los exige la API, no cambiar)

- Entrada a Gemini: PCM 16-bit, 16 kHz, mono, en chunks de ~100 ms.
- Salida de Gemini: PCM 16-bit, 24 kHz, mono.
- El micro real suele ir a 48 kHz -> se remuestrea a 16 kHz con scipy.

## Estado actual de los archivos

- `config.py` — tasas e idiomas de cada dirección.
- `audio.py` — `MicCapture` (captura + remuestreo) y `Player` (salida a un
  dispositivo concreto con buffer no bloqueante).
- `translator.py` — `TranslationSession`: conecta un MicCapture a un Player a
  través de una sesión Live; maneja send_loop y receive_loop con asyncio.
- `main.py` — pide los 4 dispositivos por consola y corre las dos sesiones.
- Auth: variable de entorno `GEMINI_API_KEY`.

## Próximo paso pedido

Construir una UI mínima que reemplace la consola y muestre los DOS transcripts
en vivo lado a lado (lo que escucho traducido + lo que digo traducido), porque
el lag de 2-3 s hace que leer sea más útil que esperar el audio.
Opciones en orden de preferencia: pywebview o FastAPI local + front simple.
Mantener TODA la lógica de audio en Python; la UI solo muestra estado y
transcripts y permite start/stop y elegir dispositivos.

## Límites conocidos (de la doc de Google)

- Solo entra audio, no texto.
- La voz sintetizada puede cambiar de timbre tras pausas largas o con varios
  hablantes.
- La detección de idioma sufre con acentos fuertes; afecta sobre todo al
  transcript de entrada, no tanto a la traducción.
- Costo API: ~$0.023/min por sesión; dos sesiones ≈ $0.046/min.
