"""Configuración central del traductor en vivo."""

MODEL = "gemini-3.5-live-translate-preview"

# Tasas que exige la Live API (no las cambies).
INPUT_RATE = 16000   # lo que Gemini espera recibir (PCM 16-bit mono)
OUTPUT_RATE = 24000  # lo que Gemini devuelve (PCM 16-bit mono)
CHUNK_MS = 100       # tamaño de chunk recomendado por la doc

# Cuántas muestras hay en un chunk de 100 ms a 16 kHz.
INPUT_CHUNK_SAMPLES = int(INPUT_RATE * CHUNK_MS / 1000)  # 1600

# ── Idiomas ────────────────────────────────────────────────────────────
# Sesión A = "entender": lo que dice el entrevistador -> tu idioma.
# Sesión B = "hablar":   lo que tú dices -> el idioma del entrevistador.
UNDERSTAND_TARGET = "es"  # traducir hacia español (para que tú escuches)
SPEAK_TARGET = "en"       # traducir hacia inglés (para que la llamada oiga)
