"""Lado "hablar" con voz clonada: tu voz -> traducción limpia -> TU voz -> CABLE.

Reemplaza a TranslationSession para la dirección "hablar". Segmenta el micrófono
por frases (detección de silencio), traduce cada frase limpiando disfluencias
(Gemini) y la sintetiza con la voz clonada del usuario (ElevenLabs) hacia el
Player, que la manda al cable virtual que la videollamada usa como micrófono.

Diseño de segmentación (riesgo ALTO del design doc):
  - Acumula audio mientras el nivel supera un umbral (hay voz).
  - Cierra la frase tras SILENCE_HANG_MS de silencio seguido.
  - Tope MAX_SEGMENT_MS para que una frase larga no espere de más.
  - Descarta segmentos demasiado cortos (ruido, clics).
"""

import asyncio
import io
import wave

import numpy as np

from config import INPUT_RATE
from translate_clean import CleanTranslator
from voice import VoiceCloner

# Parámetros de segmentación (ajustables en pruebas reales).
SILENCE_HANG_MS = 700      # pausa que cierra una frase
MAX_SEGMENT_MS = 8000      # tope: frase larga se corta y se traduce igual
MIN_SEGMENT_MS = 400       # menos de esto = ruido, se descarta
SILENCE_LEVEL = 0.06       # nivel RMS por debajo del cual se considera silencio

_CHUNK_MS = 100            # cada MicCapture.read() ≈ 100 ms


def _pcm_to_wav(pcm: bytes, rate: int = INPUT_RATE) -> bytes:
    """Envuelve PCM 16-bit mono en un contenedor WAV en memoria."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)       # int16
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _rms(pcm: bytes) -> float:
    """Nivel RMS 0.0–1.0 de un bloque PCM int16 (igual escala que audio.py)."""
    if not pcm:
        return 0.0
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if a.size == 0:
        return 0.0
    return float((np.sqrt(np.mean(a ** 2)) / 32768.0) ** 0.5)


class SpeakPipeline:
    def __init__(self, name, mic, player, target_language, voice_id,
                 on_transcript=None, on_status=None):
        self.name = name
        self.mic = mic                     # MicCapture
        self.player = player               # Player -> CABLE
        self.target = target_language
        self.voice_id = voice_id
        self._on_transcript = on_transcript
        self._on_status = on_status
        self._translator = None            # se crea en run() (usa red)
        self._voice = None

    def _status(self, estado):
        if self._on_status:
            self._on_status(self.name, estado)

    async def run(self):
        self.mic.start()
        self.player.start()
        self._translator = CleanTranslator(self.target)
        self._voice = VoiceCloner(self.voice_id)
        self._status("connected")
        loop = asyncio.get_running_loop()

        seg = bytearray()          # audio de la frase en curso
        silence_ms = 0             # silencio acumulado tras haber voz
        has_voice = False          # ya empezó a hablar en este segmento

        try:
            while True:
                chunk = await loop.run_in_executor(None, self.mic.read)
                if chunk is None:
                    continue
                level = _rms(chunk)

                if level >= SILENCE_LEVEL:
                    seg.extend(chunk)
                    silence_ms = 0
                    has_voice = True
                elif has_voice:
                    seg.extend(chunk)          # cola de la frase
                    silence_ms += _CHUNK_MS

                seg_ms = len(seg) / 2 / INPUT_RATE * 1000
                cerrar = has_voice and (
                    silence_ms >= SILENCE_HANG_MS or seg_ms >= MAX_SEGMENT_MS
                )
                if cerrar:
                    if seg_ms >= MIN_SEGMENT_MS:
                        # Un fallo de una frase (503, timeout) NO debe tumbar la
                        # app: se registra y se sigue con la siguiente frase.
                        try:
                            await self._procesar(bytes(seg), loop)
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            print(f"[{self.name}] frase perdida: {e!r}")
                            self._status("reconnecting")
                            self._status("connected")
                    seg = bytearray()
                    silence_ms = 0
                    has_voice = False
        except asyncio.CancelledError:
            raise

    async def _procesar(self, pcm: bytes, loop):
        """Traduce+limpia el segmento y lo sintetiza con la voz clonada al Player."""
        wav = _pcm_to_wav(pcm)

        # 1) Traducir + limpiar (en executor: el SDK de Gemini es bloqueante).
        #    Reintenta un par de veces ante 503 transitorio de Gemini.
        texto = ""
        for intento in range(3):
            try:
                texto = await loop.run_in_executor(
                    None, self._translator.translate_audio, wav, "audio/wav")
                break
            except Exception as e:
                if intento == 2:
                    raise
                print(f"[{self.name}] reintentando traducción ({e.__class__.__name__})…")
                await asyncio.sleep(0.6 * (intento + 1))
        texto = (texto or "").strip()
        if not texto:
            return
        print(f"[{self.name}] -> {texto}")
        if self._on_transcript:
            self._on_transcript(self.name, "output", texto)

        # 2) Voz clonada en streaming -> Player (también en executor).
        def _synth_and_feed():
            for audio_chunk in self._voice.stream(texto):
                self.player.feed(audio_chunk)
        await loop.run_in_executor(None, _synth_and_feed)

    def close(self):
        self.mic.stop()
        self.player.stop()
