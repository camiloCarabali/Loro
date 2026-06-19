"""Punto de entrada. Corre las dos direcciones de traducción a la vez.

Uso:
  1) python main.py --list          ver los índices de tus dispositivos
  2) python main.py                 te pregunta los 4 dispositivos y arranca

Requiere la variable de entorno GEMINI_API_KEY.
"""

import argparse
import asyncio
import os
import sys

from google import genai

from config import UNDERSTAND_TARGET, SPEAK_TARGET
from audio import list_devices, MicCapture, Player
from translator import TranslationSession


def ask_device(prompt: str) -> int:
    while True:
        raw = input(prompt).strip()
        if raw.isdigit():
            return int(raw)
        print("  Escribe el número del dispositivo.")


async def main():
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("Falta GEMINI_API_KEY. Expórtala antes de correr.")

    list_devices()
    print("Necesito 4 dispositivos. Mira la lista de arriba:\n")
    mic_real = ask_device("Tu MICRÓFONO real (tu voz): ")
    virtual_mic = ask_device("Cable 1 INPUT (lo que oirá Zoom como tu micro): ")
    call_in = ask_device("Cable 2 OUTPUT (voz del entrevistador que sale de Zoom): ")
    headphones = ask_device("Tus AUDÍFONOS (donde escucharás el español): ")

    client = genai.Client()

    # Sesión A — entender: entrevistador (call_in) -> español -> audífonos
    understand = TranslationSession(
        name="entender",
        client=client,
        mic=MicCapture(call_in),
        player=Player(headphones),
        target_language=UNDERSTAND_TARGET,
    )

    # Sesión B — hablar: tu micro -> inglés -> cable virtual (micro de Zoom)
    speak = TranslationSession(
        name="hablar",
        client=client,
        mic=MicCapture(mic_real),
        player=Player(virtual_mic),
        target_language=SPEAK_TARGET,
    )

    print("\nArrancando. Habla normal; Ctrl+C para salir.\n")
    try:
        await asyncio.gather(understand.run(), speak.run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        understand.close()
        speak.close()
        print("\nCerrado.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true",
                        help="Solo listar dispositivos y salir")
    args = parser.parse_args()
    if args.list:
        list_devices()
    else:
        asyncio.run(main())
