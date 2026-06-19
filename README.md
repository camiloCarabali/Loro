# Loro

Traductor en vivo para entrevistas por videollamada.

Herramienta de escritorio (Windows) que traduce una entrevista en tiempo real
en las dos direcciones usando el modelo `gemini-3.5-live-translate-preview`.
Como un loro, repite lo que oye — pero traducido.

- **Entender:** la voz del entrevistador (inglés) llega a tus audífonos en español.
- **Hablar:** tu voz (español) entra a la llamada traducida a inglés.

## 1. Cables de audio virtuales

Necesitas DOS dispositivos virtuales para evitar el feedback. Lo más simple:

- **VB-CABLE** (gratis): instala el paquete normal -> aparece "CABLE Input/Output".
- **VB-CABLE A+B** (donación): añade un segundo cable -> "CABLE-A" y "CABLE-B".

Quedan así dos cables: úsalos como Cable 1 y Cable 2 del paso 4.

## 2. Configurar Zoom / Meet / Teams

- **Micrófono** de la llamada  -> `CABLE Input` (Cable 1). Aquí entra tu inglés.
- **Altavoz / salida** de la llamada -> `CABLE-A Input` (Cable 2). Por aquí
  sacamos la voz del entrevistador hacia la app.

> Usa AUDÍFONOS. Si la salida va a parlantes, tu micro la recaptura y se arma bucle.

## 3. Instalar

```bash
pip install -r requirements.txt
setx GEMINI_API_KEY tu_api_key       # Windows; reabre la terminal después
```

API key gratis en https://aistudio.google.com/apikey

## 4. Correr

```bash
python main.py --list     # ver los índices de tus dispositivos
python main.py            # te pide los 4 y arranca
```

Te preguntará por:

1. Tu micrófono real
2. Cable 1 INPUT (lo que Zoom usará como tu micro)
3. Cable 2 OUTPUT (la voz del entrevistador que sale de Zoom)
4. Tus audífonos

## Cómo encaja

```
Tu micro --> [Sesión B: ES->EN] --> Cable 1 --> micro de Zoom
Zoom --> Cable 2 --> [Sesión A: EN->ES] --> tus audífonos
```

## Límites conocidos (de la doc de Google)

- Solo entra audio, no texto.
- La voz sintetizada puede cambiar de timbre tras pausas largas o con varios
  hablantes a la vez.
- La detección de idioma sufre con acentos fuertes o cambios rápidos de idioma;
  afecta sobre todo al transcript, no tanto a la traducción.
- Va ~2-3 s detrás del hablante. Es normal en traducción continua.

## Costo

API: ~$0.023 por minuto y por sesión. Dos sesiones activas = ~$0.046/min.
Una entrevista de 45 min ≈ 2 USD.

## Notas técnicas

- Entrada a Gemini: PCM 16-bit, 16 kHz, mono. La app remuestrea tu micro
  (que suele ir a 48 kHz) automáticamente con `scipy`.
- Salida de Gemini: PCM 16-bit, 24 kHz, mono.
- En producción cliente-servidor usa *ephemeral tokens* en vez de la API key
  directa; aquí, al ser una app local que corres tú, la key por entorno basta.
