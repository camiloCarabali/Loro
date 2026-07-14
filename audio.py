"""Captura, remuestreo y reproducción de audio con sounddevice.

Notas importantes de Windows:
- Tu micro normalmente corre a 44100/48000 Hz, no a 16000. Por eso capturamos
  a la tasa nativa del dispositivo y remuestreamos a 16 kHz en Python.
- Los cables virtuales (VB-Cable) aparecen como dispositivos de entrada y
  salida normales; los seleccionas por su índice igual que cualquier otro.
"""

import math
import queue
import threading

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly

from config import INPUT_RATE, OUTPUT_RATE, INPUT_CHUNK_SAMPLES


def list_devices():
    """Imprime los dispositivos disponibles con su índice."""
    print("\n=== Dispositivos de audio ===")
    for i, d in enumerate(sd.query_devices()):
        io = []
        if d["max_input_channels"] > 0:
            io.append(f"in:{d['max_input_channels']}")
        if d["max_output_channels"] > 0:
            io.append(f"out:{d['max_output_channels']}")
        print(f"  [{i:>2}] {d['name']}  ({', '.join(io)})  "
              f"{int(d['default_samplerate'])} Hz")
    print("=============================\n")


def _to_mono_int16(data: np.ndarray) -> np.ndarray:
    """Mezcla a mono si viene en estéreo y asegura int16."""
    if data.ndim == 2 and data.shape[1] > 1:
        data = data.mean(axis=1)
    return data.astype(np.int16, copy=False).reshape(-1)


def _rms_level(samples: np.ndarray) -> float:
    """Nivel de audio 0.0–1.0 a partir del RMS de muestras int16.

    Se escala con raíz para que voz normal mueva la barra de forma visible
    (el RMS lineal de la voz suele ser muy bajo frente al máximo de int16).
    """
    if samples.size == 0:
        return 0.0
    rms = np.sqrt(np.mean(samples.astype(np.float32) ** 2))
    norm = min(rms / 32768.0, 1.0)
    return float(norm ** 0.5)


class MicCapture:
    """Captura un dispositivo de entrada y entrega chunks PCM 16 kHz mono.

    Úsalo como iterador: cada `next()` (o `for`) devuelve ~100 ms de audio
    ya remuestreado a 16 kHz, listo para mandar a Gemini.
    """

    def __init__(self, device_index: int):
        self.device_index = device_index
        info = sd.query_devices(device_index)
        self.native_rate = int(info["default_samplerate"])
        self._q: "queue.Queue[bytes]" = queue.Queue()
        self._stream = None
        self.level = 0.0  # nivel de audio 0.0–1.0 del último chunk (para la UI)
        # Factor de remuestreo native_rate -> 16000 reducido por su gcd.
        g = math.gcd(INPUT_RATE, self.native_rate)
        self._up, self._down = INPUT_RATE // g, self.native_rate // g

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(f"[mic {self.device_index}] {status}")
        mono = _to_mono_int16(indata.copy())
        self.level = _rms_level(mono)
        if self.native_rate != INPUT_RATE:
            # resample_poly trabaja en float; volvemos a int16 al final.
            resampled = resample_poly(mono.astype(np.float32),
                                      self._up, self._down)
            mono = np.clip(resampled, -32768, 32767).astype(np.int16)
        self._q.put(mono.tobytes())

    def start(self):
        self._stream = sd.InputStream(
            device=self.device_index,
            channels=1,
            samplerate=self.native_rate,
            dtype="int16",
            blocksize=int(self.native_rate * 0.1),  # ~100 ms nativos
            callback=self._callback,
        )
        self._stream.start()

    def read(self, timeout=1.0) -> bytes | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        self.level = 0.0
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                print(f"[mic {self.device_index}] error al cerrar: {e!r}")
            self._stream = None


class Player:
    """Reproduce audio PCM 24 kHz mono en un dispositivo de salida concreto.

    El audio traducido que devuelve Gemini se va acumulando en un buffer;
    el callback de sounddevice lo va consumiendo sin bloquear el event loop.
    """

    # Tope del buffer. Si la red se traba, el audio llega a ráfagas y se acumula:
    # el reproductor se va quedando atrás y suena desfasado y a tirones. Cuando
    # pasa de este tope, tiramos lo viejo y saltamos a lo actual: mejor perder un
    # instante que quedar segundos atrás repitiendo audio viejo.
    MAX_BUFFER_SEC = 1.5

    def __init__(self, device_index: int):
        self.device_index = device_index
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._stream = None
        self._max_bytes = int(OUTPUT_RATE * 2 * self.MAX_BUFFER_SEC)  # int16 = 2 B

    def _callback(self, outdata, frames, time_info, status):
        if status:
            print(f"[out {self.device_index}] {status}")
        needed = frames * 2  # int16 = 2 bytes
        with self._lock:
            take = self._buf[:needed]
            del self._buf[:needed]
        if len(take) < needed:
            take += b"\x00" * (needed - len(take))  # silencio si falta
        outdata[:] = np.frombuffer(take, dtype=np.int16).reshape(-1, 1)

    def start(self):
        self._stream = sd.OutputStream(
            device=self.device_index,
            channels=1,
            samplerate=OUTPUT_RATE,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    def feed(self, pcm_bytes: bytes):
        with self._lock:
            self._buf.extend(pcm_bytes)
            # Si nos pasamos del tope, descartar lo MÁS VIEJO y quedarnos con lo
            # reciente: así el audio vuelve a estar sincronizado con lo que se dice.
            if len(self._buf) > self._max_bytes:
                exceso = len(self._buf) - self._max_bytes
                del self._buf[:exceso]
                print(f"[out {self.device_index}] buffer lleno: "
                      f"descartados {exceso/2/OUTPUT_RATE:.1f}s de audio atrasado")

    def flush(self):
        """Descarta el audio pendiente. Se usa al reconectar: lo que quedó del
        corte ya no corresponde a lo que se está diciendo ahora."""
        with self._lock:
            self._buf.clear()

    def stop(self):
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                print(f"[out {self.device_index}] error al cerrar: {e!r}")
            self._stream = None


# ── Loopback WASAPI (pyaudiowpatch) ──────────────────────────────────────────
# Captura lo que SALE por un altavoz/auriculares, sin cables virtuales.
# Es la forma nativa de Windows de "oír lo que se está reproduciendo".

def list_loopback_devices():
    """Devuelve [(index, name)] de los dispositivos loopback WASAPI."""
    import pyaudiowpatch as pyaudio
    p = pyaudio.PyAudio()
    try:
        out = []
        for lb in p.get_loopback_device_info_generator():
            out.append((lb["index"], lb["name"]))
        return out
    finally:
        p.terminate()


def default_loopback_device():
    """Devuelve (index, name) del loopback del altavoz por defecto, o None."""
    import pyaudiowpatch as pyaudio
    p = pyaudio.PyAudio()
    try:
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        spk = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
        if spk.get("isLoopbackDevice"):
            return spk["index"], spk["name"]
        for lb in p.get_loopback_device_info_generator():
            if spk["name"] in lb["name"]:
                return lb["index"], lb["name"]
        return None
    finally:
        p.terminate()


class LoopbackCapture:
    """Captura lo que se reproduce en un altavoz (loopback WASAPI) y entrega
    chunks PCM 16 kHz mono, igual que MicCapture.

    Si device_index es None, usa el altavoz por defecto de Windows.
    """

    def __init__(self, device_index: int | None = None):
        import pyaudiowpatch as pyaudio
        self._pa = pyaudio.PyAudio()
        self._paInt16 = pyaudio.paInt16

        if device_index is None:
            found = default_loopback_device()
            if found is None:
                raise RuntimeError("No se encontró loopback del altavoz por defecto.")
            device_index, _ = found

        info = self._pa.get_device_info_by_index(device_index)
        self.device_index = device_index
        self.native_rate = int(info["defaultSampleRate"])
        self.channels = int(info["maxInputChannels"]) or 2

        self._q: "queue.Queue[bytes]" = queue.Queue()
        self._stream = None
        self._running = False
        self._thread = None
        self.level = 0.0  # nivel de audio 0.0–1.0 del último chunk (para la UI)

        g = math.gcd(INPUT_RATE, self.native_rate)
        self._up, self._down = INPUT_RATE // g, self.native_rate // g

    def _loop(self):
        chunk_frames = int(self.native_rate * 0.1)  # ~100 ms
        while self._running:
            try:
                raw = self._stream.read(chunk_frames, exception_on_overflow=False)
            except Exception:
                break
            data = np.frombuffer(raw, dtype=np.int16)
            if self.channels > 1:
                data = data.reshape(-1, self.channels).mean(axis=1)
            data = data.astype(np.int16)
            self.level = _rms_level(data)
            if self.native_rate != INPUT_RATE:
                resampled = resample_poly(data.astype(np.float32),
                                          self._up, self._down)
                data = np.clip(resampled, -32768, 32767).astype(np.int16)
            self._q.put(data.tobytes())

    def start(self):
        self._stream = self._pa.open(
            format=self._paInt16,
            channels=self.channels,
            rate=self.native_rate,
            frames_per_buffer=int(self.native_rate * 0.1),
            input=True,
            input_device_index=self.device_index,
        )
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def read(self, timeout=1.0) -> bytes | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        # ORDEN IMPORTANTE: el hilo puede estar bloqueado dentro de
        # stream.read(). Si terminamos PyAudio con el hilo aún vivo, el proceso
        # revienta (es código C, no lanza excepción). Por eso: primero paramos
        # el stream (eso desbloquea el read), luego esperamos al hilo de verdad,
        # y solo al final soltamos PyAudio.
        self._running = False
        self.level = 0.0

        if self._stream:
            try:
                self._stream.stop_stream()
            except Exception:
                pass

        if self._thread:
            self._thread.join(timeout=3.0)
            if self._thread.is_alive():
                # El hilo sigue colgado: NO liberamos PyAudio (nos llevaría el
                # proceso por delante). Se soltará al cerrar la app.
                print("[loopback] el hilo no terminó; se deja PyAudio vivo")
                self._thread = None
                self._stream = None
                return

        if self._stream:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        try:
            self._pa.terminate()
        except Exception:
            pass
