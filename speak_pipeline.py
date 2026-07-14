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
import threading
import wave

import numpy as np

from config import INPUT_RATE
from translate_clean import CleanTranslator
from voice import VoiceCloner

# Parámetros de segmentación (ajustables en pruebas reales).
#
# Con tartamudez las pausas dentro de una frase son largas: SILENCE_HANG_MS debe
# ser generoso o una sola idea se parte en varios trozos (y se traduce a medias).
SILENCE_HANG_MS = 1100     # pausa que cierra una frase
MAX_SEGMENT_MS = 12000     # tope: frase larga se corta y se traduce igual
MIN_SEGMENT_MS = 900       # menos de esto = ruido/muletilla -> Gemini alucinaría
MIN_VOICE_MS = 500         # voz real mínima dentro del segmento
SILENCE_LEVEL = 0.06       # nivel RMS por debajo del cual se considera silencio

# Guardamos audio ANTES de detectar voz: el inicio de una palabra arranca suave
# y si no, el segmento sale decapitado y el modelo adivina lo que falta.
PREROLL_MS = 300

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
        # Al detener, los hilos del executor (mic.read, TTS) pueden seguir vivos.
        # Esta bandera les dice que paren, y _busy marca que uno está usando el
        # audio, para que close() no cierre los streams debajo de ellos.
        self._running = False
        self._busy = threading.Event()
        self._busy.set()                   # set = nadie usando el audio
        # Varias frases pueden traducirse a la vez, pero deben SONAR de una en
        # una y en orden: si no, se encimarían en el cable.
        self._speak_lock = asyncio.Lock()

    def _status(self, estado):
        if self._on_status:
            self._on_status(self.name, estado)

    async def run(self):
        self.mic.start()
        self.player.start()
        self._translator = CleanTranslator(self.target)
        self._voice = VoiceCloner(self.voice_id)
        self._running = True
        self._status("connected")
        loop = asyncio.get_running_loop()

        from collections import deque
        preroll_n = max(1, PREROLL_MS // _CHUNK_MS)
        preroll = deque(maxlen=preroll_n)  # audio justo ANTES de detectar voz

        seg = bytearray()          # audio de la frase en curso
        silence_ms = 0             # silencio acumulado tras haber voz
        voice_ms = 0               # cuánta VOZ real lleva el segmento
        has_voice = False          # ya empezó a hablar en este segmento
        tasks = set()              # procesamientos en vuelo (no bloquean el mic)

        try:
            while self._running:
                chunk = await loop.run_in_executor(None, self.mic.read)
                if not self._running:
                    break
                if chunk is None:
                    continue
                level = _rms(chunk)

                if level >= SILENCE_LEVEL:
                    if not has_voice:
                        # Arranque de frase: recuperamos el pre-roll para no
                        # perder el ataque de la primera palabra.
                        for prev in preroll:
                            seg.extend(prev)
                        preroll.clear()
                        has_voice = True
                    seg.extend(chunk)
                    silence_ms = 0
                    voice_ms += _CHUNK_MS
                elif has_voice:
                    seg.extend(chunk)          # cola de la frase
                    silence_ms += _CHUNK_MS
                else:
                    preroll.append(chunk)      # todavía en silencio: solo pre-roll

                seg_ms = len(seg) / 2 / INPUT_RATE * 1000
                cerrar = has_voice and (
                    silence_ms >= SILENCE_HANG_MS or seg_ms >= MAX_SEGMENT_MS
                )
                if cerrar:
                    # Solo mandamos si hay suficiente audio Y suficiente voz real:
                    # un ruido corto haría que el modelo invente una frase entera.
                    if seg_ms >= MIN_SEGMENT_MS and voice_ms >= MIN_VOICE_MS:
                        # En background: si esperáramos aquí, el micrófono dejaría
                        # de consumirse y la cola acumularía audio viejo, que luego
                        # se traduce desfasado (de ahí las repeticiones).
                        t = asyncio.create_task(self._procesar_seguro(bytes(seg), loop))
                        tasks.add(t)
                        t.add_done_callback(tasks.discard)
                    seg = bytearray()
                    silence_ms = 0
                    voice_ms = 0
                    has_voice = False
        except asyncio.CancelledError:
            self._running = False   # que los hilos del executor salgan
            raise
        finally:
            self._running = False
            for t in tasks:
                t.cancel()

    async def _procesar_seguro(self, pcm: bytes, loop):
        """_procesar pero sin tumbar la app si una frase falla (503, timeout…)."""
        try:
            await self._procesar(pcm, loop)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[{self.name}] frase perdida: {e!r}")

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
        if not texto or not self._running:
            return
        print(f"[{self.name}] -> {texto}")
        if self._on_transcript:
            self._on_transcript(self.name, "output", texto)

        # 2) Voz clonada en streaming -> Player (también en executor).
        #    _busy avisa a close() que el Player está en uso: no debe cerrarlo
        #    debajo de este hilo (eso reventaba el driver de audio al detener).
        #    El lock serializa la reproducción: dos frases traducidas en paralelo
        #    no deben sonar encimadas en el cable.
        def _synth_and_feed():
            self._busy.clear()
            try:
                for audio_chunk in self._voice.stream(texto):
                    if not self._running:
                        break   # detenido: no sigas alimentando el Player
                    self.player.feed(audio_chunk)
            finally:
                self._busy.set()

        async with self._speak_lock:
            if not self._running:
                return
            await loop.run_in_executor(None, _synth_and_feed)

    def close(self):
        # Señal a los hilos del executor de que paren.
        self._running = False
        # Esperar (con tope) a que el hilo de TTS suelte el Player antes de
        # cerrar los streams; si no, sounddevice puede tumbar el proceso.
        self._busy.wait(timeout=3.0)
        try:
            self.mic.stop()
        except Exception as e:
            print(f"[{self.name}] error cerrando mic: {e!r}")
        try:
            self.player.stop()
        except Exception as e:
            print(f"[{self.name}] error cerrando player: {e!r}")
