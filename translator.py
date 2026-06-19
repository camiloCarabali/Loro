"""Una sesión de traducción = un MicCapture -> Gemini -> un Player.

Cada instancia es una dirección del flujo. Para una entrevista corres dos:
  - "entender": entra audio del entrevistador, sale español a tus audífonos
  - "hablar":   entra tu voz, sale inglés al cable virtual (micro de Zoom)
"""

import asyncio
import base64

from google.genai import types

from config import MODEL
from audio import Player


class TranslationSession:
    def __init__(self, name, client, mic, player: Player | None,
                 target_language: str, echo: bool = False,
                 on_transcript=None, monitor_player: Player | None = None,
                 on_status=None):
        self.name = name
        self.client = client
        self.mic = mic                       # MicCapture o LoopbackCapture
        self.player = player                 # None = modo solo-texto (no reproduce audio)
        self.target = target_language
        self.echo = echo
        self._on_transcript = on_transcript  # callable(name, kind, text) | None
        self._monitor = monitor_player       # player extra para escuchar la propia traducción
        self._on_status = on_status          # callable(name, estado) | None

    def _config(self):
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            translation_config=types.TranslationConfig(
                target_language_code=self.target,
                echo_target_language=self.echo,
            ),
        )

    def _status(self, estado):
        if self._on_status:
            self._on_status(self.name, estado)

    async def run(self):
        # El audio (mic/player) se abre UNA sola vez; solo la conexión a
        # Gemini se reabre si se cae. Así una caída de red no pierde el audio.
        self.mic.start()
        if self.player:
            self.player.start()
        if self._monitor:
            self._monitor.start()

        backoff = 1.0  # segundos; crece hasta un tope con cada fallo seguido
        while True:
            try:
                async with self.client.aio.live.connect(
                        model=MODEL, config=self._config()) as session:
                    print(f"[{self.name}] sesión abierta -> {self.target}")
                    self._status("connected")
                    backoff = 1.0  # conexión exitosa: resetear backoff
                    await asyncio.gather(
                        self._send_loop(session),
                        self._receive_loop(session),
                    )
            except asyncio.CancelledError:
                raise  # stop del usuario: salir limpio
            except Exception as e:
                print(f"[{self.name}] conexión perdida: {e!r}")
                self._status("reconnecting")
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    raise
                backoff = min(backoff * 2, 15.0)  # 1,2,4,8,15,15…
                continue

    async def _send_loop(self, session):
        """Lee chunks del micro (en un thread) y los manda a Gemini."""
        loop = asyncio.get_running_loop()
        while True:
            chunk = await loop.run_in_executor(None, self.mic.read)
            if chunk is None:
                continue
            await session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
            )

    async def _receive_loop(self, session):
        """Recibe audio traducido + transcripts y los procesa."""
        async for response in session.receive():
            sc = response.server_content
            if not sc:
                continue
            if sc.input_transcription and sc.input_transcription.text:
                text = sc.input_transcription.text
                print(f"[{self.name}] escuché: {text}")
                if self._on_transcript:
                    self._on_transcript(self.name, "input", text)
            if sc.output_transcription and sc.output_transcription.text:
                text = sc.output_transcription.text
                print(f"[{self.name}] traduje: {text}")
                if self._on_transcript:
                    self._on_transcript(self.name, "output", text)
            if sc.model_turn:
                for part in sc.model_turn.parts:
                    if part.inline_data and part.inline_data.data:
                        data = part.inline_data.data
                        if isinstance(data, str):  # algunos SDK devuelven base64
                            data = base64.b64decode(data)
                        if self.player:
                            self.player.feed(data)
                        if self._monitor:
                            self._monitor.feed(data)

    def close(self):
        self.mic.stop()
        if self.player:
            self.player.stop()
        if self._monitor:
            self._monitor.stop()
