# Manual de usuario — Loro 🦜

Loro traduce tu entrevista por videollamada en vivo, en las dos direcciones:

- **Escuchas al entrevistador** traducido a tu idioma (se muestra en pantalla).
- **Hablas tú** y la llamada escucha tu voz traducida al idioma del entrevistador.

Funciona con Discord, Zoom, Google Meet, Teams o WhatsApp Desktop.

---

## 1. Requisitos (solo la primera vez)

### a) Instalar VB-Audio Virtual Cable (gratis)

Loro necesita un "cable de audio virtual" para meter tu voz traducida a la llamada.
Windows no deja hacer esto sin él.

1. Entra a **https://vb-audio.com/Cable/**
2. Descarga **VB-CABLE Driver Pack** (es gratis; puedes donar $0).
3. Descomprime el ZIP, clic derecho en `VBCABLE_Setup_x64.exe` → **Ejecutar como administrador**.
4. Reinicia el PC.

Después de esto aparecerán dos dispositivos nuevos en Windows:
`CABLE Input` y `CABLE Output`.

### b) Tener una API key de Gemini

1. Entra a **https://aistudio.google.com/apikey** y crea una API key.
2. En la carpeta de Loro, crea un archivo llamado `.env` con esta línea:

   ```
   GEMINI_API_KEY=tu_api_key_aqui
   ```

---

## 2. Configurar tu app de videollamada

Esto se hace **una sola vez** en la app que uses (ejemplo con Discord):

| Ajuste | Qué elegir |
|---|---|
| 🎙 **Micrófono** | `CABLE Output (VB-Audio Virtual Cable)` |
| 🔊 **Altavoz** | Tus auriculares de siempre (normal) |

> ¿Por qué "CABLE Output" en el micrófono? Loro escribe la traducción en
> "CABLE Input", y eso sale por "CABLE Output", que es lo que la llamada lee como
> tu micrófono. Los nombres confunden porque están al revés de lo que uno espera.

**Dónde está ese ajuste según la app:**
- **Discord:** ⚙ → Voz y vídeo → Dispositivo de entrada
- **Zoom:** Configuración → Audio → Micrófono
- **Google Meet:** ⚙ durante la llamada → Audio → Micrófono
- **Teams:** ··· → Configuración → Dispositivos → Micrófono
- **WhatsApp Desktop:** ⚙ → Audio → Micrófono

---

## 3. Usar Loro

1. Abre la app (`app.py` o el ejecutable).
2. En la ventana de configuración elige:
   - **① Tu micrófono real** — con el que hablas tú.
   - **② Micrófono virtual** — `CABLE Input` (ya viene preseleccionado).
   - **③ Audio que escuchas** — déjalo en **Automático** (capta lo que suena en
     tus auriculares).
   - **④ Idiomas** — tu idioma y el del entrevistador.
3. Pulsa **Iniciar traducción** (o `Ctrl+Enter`).
4. Verás dos paneles:
   - **Izquierda:** lo que dice el entrevistador, traducido a tu idioma.
   - **Derecha:** lo que tú dices, traducido al idioma de la llamada.
5. Las **barritas verdes** indican que Loro está captando audio.
6. Para terminar: botón **Detener** (o `Esc`).

Tu configuración se guarda sola; la próxima vez ya viene lista.

### Atajos de teclado
- `Ctrl+Enter` — iniciar / detener
- `Esc` — detener (o cerrar la ventana de configuración)

---

## 4. Solución de problemas

**No aparece "CABLE Input" en la app**
→ No instalaste VB-Cable o falta reiniciar el PC. Repite el paso 1a.

**Dice "Sin GEMINI_API_KEY"**
→ Falta el archivo `.env` o la key está mal. Revisa el paso 1b.

**No escucho al entrevistador traducido (panel izquierdo vacío)**
→ Verifica que el audio de la llamada esté saliendo por tus auriculares y que la
  barrita verde izquierda se mueva. El campo ③ debe estar en "Automático".

**El entrevistador no me escucha**
→ En tu app de videollamada el micrófono debe ser `CABLE Output`. Revisa el paso 2.

**Se escucha mi voz doble / con eco**
→ Asegúrate de que tu micrófono real (campo ①) NO sea un dispositivo CABLE.

**La traducción tarda 2-3 segundos**
→ Es normal: es la latencia del modelo de Google. Por eso es mejor leer los
  paneles que esperar el audio.

**Se cayó el internet a mitad de llamada**
→ Loro reconecta solo. Verás "Reconectando…" en naranja y vuelve a "Traduciendo…"
  cuando recupere la conexión.

---

## 5. Costo

Cada minuto de uso cuesta ~$0.046 USD en la API de Gemini (dos sesiones a la vez).
Una entrevista de 30 min ≈ $1.40 USD aproximadamente.
