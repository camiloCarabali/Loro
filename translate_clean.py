"""Traducción con limpieza de disfluencias para el lado "hablar".

Recibe audio del usuario (que puede tener tartamudeo, repeticiones y titubeos)
y devuelve la traducción al idioma destino, FLUIDA y bien formada, como si se
hubiera dicho de corrido. Es el corazón de Loro: tú tartamudeas, tu voz clonada
sale limpia al otro lado.

Usa Gemini en streaming para que el texto empiece a llegar cuanto antes.
"""

import os

from google import genai
from google.genai import types

# Modelo rápido; suficiente para traducir+limpiar frases de conversación.
MODEL = "gemini-2.5-flash"

_LANG_NAMES = {
    "en": "inglés", "es": "español", "fr": "francés", "de": "alemán",
    "pt": "portugués", "it": "italiano", "ja": "japonés", "ko": "coreano",
    "zh": "chino", "ar": "árabe", "ru": "ruso", "hi": "hindi",
}

_MIME = {".wav": "audio/wav", ".m4a": "audio/mp4", ".mp3": "audio/mp3",
         ".ogg": "audio/ogg", ".flac": "audio/flac"}


def _prompt(target_lang: str) -> str:
    lang = _LANG_NAMES.get(target_lang, target_lang)
    return (
        f"Traduce al {lang} lo que se dice en este audio.\n"
        "El hablante puede tener disfluencias: tartamudeo, sílabas o palabras "
        "repetidas, titubeos ('eh', 'este', 'um') y frases reiniciadas. "
        "Produce una traducción FLUIDA y bien formada, como si la frase se "
        "hubiera dicho de corrido y con seguridad.\n"
        "Reglas estrictas:\n"
        "- Traduce SOLO lo que realmente se dice. NUNCA inventes, completes ni "
        "adivines palabras que no están en el audio.\n"
        "- Si el audio está vacío, es ruido, o no se entiende ninguna palabra, "
        "responde EXACTAMENTE: (nada)\n"
        "- Si solo se oye una palabra suelta, traduce solo esa palabra.\n"
        "- NO cambies el significado ni agregues información que no se dijo.\n"
        "- NO respondas ni comentes; solo traduce.\n"
        "- Elimina repeticiones y muletillas propias del tartamudeo.\n"
        "- Responde únicamente con la traducción, sin comillas ni etiquetas."
    )


class CleanTranslator:
    def __init__(self, target_lang: str, client: genai.Client | None = None):
        self.target = target_lang
        self.client = client or genai.Client()

    def translate_audio_stream(self, audio_bytes: bytes, mime: str = "audio/wav"):
        """Generador: va entregando el texto traducido+limpio en trozos."""
        stream = self.client.models.generate_content_stream(
            model=MODEL,
            contents=[
                _prompt(self.target),
                types.Part.from_bytes(data=audio_bytes, mime_type=mime),
            ],
        )
        for chunk in stream:
            if chunk.text:
                yield chunk.text

    def translate_audio(self, audio_bytes: bytes, mime: str = "audio/wav") -> str:
        """Devuelve la traducción completa, o "" si no había nada que traducir."""
        texto = "".join(self.translate_audio_stream(audio_bytes, mime)).strip()
        # El prompt pide "(nada)" cuando el audio es ruido/silencio: no lo
        # sintetizamos ni lo mostramos.
        if texto.lower().strip(".!¡ ") in ("(nada)", "nada", "(none)", ""):
            return ""
        return texto


def mime_for(path: str) -> str:
    return _MIME.get(os.path.splitext(path)[1].lower(), "audio/wav")
