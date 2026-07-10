"""Voz clonada con ElevenLabs para el lado "hablar" de Loro.

Recibe texto (ya traducido al idioma del entrevistador) y produce audio con la
voz clonada del usuario, en streaming, listo para el `Player` de audio.py.

Formato de salida: PCM 16-bit, 24 kHz, mono — el MISMO que devuelve Gemini,
así el `Player` existente lo reproduce sin reconvertir (ver OUTPUT_RATE).

La API key sale de ELEVENLABS_API_KEY (env o .env, que app.py ya carga).
"""

import os

from elevenlabs.client import ElevenLabs

from config import OUTPUT_RATE

# Modelo flash = el de menor latencia de ElevenLabs; multilingüe.
DEFAULT_TTS_MODEL = "eleven_flash_v2_5"
# El Player espera 24 kHz; pedimos PCM a esa tasa para no reconvertir.
_OUTPUT_FORMAT = f"pcm_{OUTPUT_RATE}"  # "pcm_24000"


class VoiceCloner:
    """Convierte texto -> audio PCM 24 kHz con la voz clonada, en streaming.

    Uso:
        vc = VoiceCloner(voice_id="...")
        for pcm_chunk in vc.stream("Hello, nice to meet you"):
            player.feed(pcm_chunk)
    """

    def __init__(self, voice_id: str, api_key: str | None = None,
                 model_id: str = DEFAULT_TTS_MODEL):
        key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            raise RuntimeError("Falta ELEVENLABS_API_KEY (env o .env).")
        if not voice_id:
            raise RuntimeError("Falta el voice_id de la voz clonada.")
        self._client = ElevenLabs(api_key=key)
        self.voice_id = voice_id
        self.model_id = model_id

    def stream(self, text: str):
        """Genera el audio de `text` y va entregando chunks PCM 24 kHz mono.

        Es un generador: el primer chunk llega en ~0.5 s (medido en el
        prototipo), así el Player empieza a reproducir casi de inmediato.
        """
        text = (text or "").strip()
        if not text:
            return
        for chunk in self._client.text_to_speech.stream(
            voice_id=self.voice_id,
            model_id=self.model_id,
            text=text,
            output_format=_OUTPUT_FORMAT,
        ):
            if chunk:
                yield chunk

    def synth(self, text: str) -> bytes:
        """Igual que stream() pero devuelve todo el audio junto (para pruebas)."""
        return b"".join(self.stream(text))
