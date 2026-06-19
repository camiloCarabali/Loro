<p align="center">
  <img src="logo.png" width="120" alt="Loro">
</p>

<h1 align="center">Loro 🦜</h1>

<p align="center">Traductor en vivo para videollamadas, en las dos direcciones.</p>

---

App de escritorio (Windows) que traduce una videollamada en tiempo real usando la
Gemini Live API. Como un loro, repite lo que oye — pero traducido.

- **Entender:** lo que dice la otra persona se muestra en pantalla traducido a tu idioma.
- **Hablar:** tu voz entra a la llamada traducida al idioma del otro, con pronunciación clara.

Nació de una necesidad personal: convivir con la tartamudez hace que el idioma —
y sobre todo la pronunciación en inglés — sea una barrera injusta en entrevistas de
trabajo. Loro busca que esa barrera pese menos.

## Cómo funciona

- **Escuchar a la otra persona** no necesita software extra: usa *loopback WASAPI*
  para capturar lo que suena en tus auriculares de forma nativa en Windows.
- **Enviar tu voz traducida** a la llamada requiere un cable de audio virtual
  ([VB-Audio Virtual Cable](https://vb-audio.com/Cable/), gratis), porque Windows no
  permite que una app inyecte audio en el micrófono de otra sin un driver virtual.
- Dos sesiones simultáneas con Gemini, una por cada dirección.

## Instalación

```bash
pip install -r requirements.txt
```

1. Instala [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) y reinicia.
2. Consigue una API key gratis en https://aistudio.google.com/apikey
3. Crea un archivo `.env` junto al proyecto:
   ```
   GEMINI_API_KEY=tu_api_key
   ```

## Uso

```bash
python app.py
```

En tu app de videollamada (Discord/Zoom/Meet/Teams), pon el **micrófono** en
`CABLE Output`. En Loro elige tu micrófono real y los idiomas; el resto se
autodetecta. Guía detallada en [MANUAL.md](MANUAL.md).

## Características

- UI con transcripts en vivo lado a lado
- 12 idiomas en ambas direcciones
- Medidores de nivel de audio
- Reconexión automática ante caídas de red
- Configuración persistente y atajos de teclado (`Ctrl+Enter` / `Esc`)

## Stack

Python · Gemini Live API (`gemini-3.5-live-translate-preview`) · pywebview ·
sounddevice · PyAudioWPatch (loopback WASAPI) · scipy

## Límites conocidos

- Va ~2-3 s detrás del hablante (normal en traducción continua; por eso se lee en pantalla).
- La voz sintetizada puede cambiar de timbre tras pausas largas.
- Acentos fuertes afectan sobre todo al transcript, no tanto a la traducción.
- Costo API: ~$0.046/min (dos sesiones). Una entrevista de 45 min ≈ 2 USD.
