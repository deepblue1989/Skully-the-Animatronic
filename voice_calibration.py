import numpy as np
import sounddevice as sd
from kokoro_onnx import Kokoro
import time
import re

# --- 1. THE EXPERIMENT HUB ---
# Change these values, save, and run to hear the difference.
PRIMARY_VOICE = "bm_daniel"      # Authority/Bass
SECONDARY_VOICE = "bm_lewis"  # Grit/Texture
BLEND_WEIGHT = 0.4             # 0.7 = 70% Primary, 30% Secondary
SPEED = 1.1                  # 1.0 is normal, 1.2 is snappy/sarcastic

# The text Skully will say for the test
TEST_TEXT = "I am currently calculating the probability that this voice satisfies your aesthetic requirements. It remains low."

# --- 2. CONFIGURATION ---
VOICE_MODEL = "kokoro-v1.0.int8.onnx"
VOICE_BIN = "voices-v1.0.bin"

# --- 3. THE VOICE ALCHEMIST ---
def run_voice_test():
    print(f"Loading {VOICE_MODEL}...")
    try:
        kokoro = Kokoro(VOICE_MODEL, VOICE_BIN)
    except Exception as e:
        print(f"Error loading models: {e}. Check if files are in the same folder!")
        return

    print(f"\n--- SKULLY VOICE LAB ---")
    print(f"Mixing: {PRIMARY_VOICE} ({int(BLEND_WEIGHT*100)}%) + {SECONDARY_VOICE} ({int((1-BLEND_WEIGHT)*100)}%)")
    print(f"Speed: {SPEED}")
    
    # Get raw embeddings
    try:
        v_a = kokoro.get_voice_style(PRIMARY_VOICE)
        v_b = kokoro.get_voice_style(SECONDARY_VOICE)
    except Exception as e:
        print(f"Voice name error: {e}")
        return

    # Mathematical blend
    mixed_vector = (v_a * BLEND_WEIGHT) + (v_b * (1.0 - BLEND_WEIGHT))

    # Generate Audio
    print("Synthesizing...")
    start = time.time()
    samples, sample_rate = kokoro.create(
        TEST_TEXT, 
        voice=mixed_vector, 
        speed=SPEED, 
        lang="en-us"
    )
    print(f"Done in {round(time.time() - start, 3)}s.")

    # Playback
    print("Playing audio...")
    sd.play(samples, sample_rate)
    sd.wait()
    print("Test Complete.")

if __name__ == "__main__":
    run_voice_test()