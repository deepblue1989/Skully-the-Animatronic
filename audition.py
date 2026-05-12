from kokoro_onnx import Kokoro
import sounddevice as sd

# Load the brain and voices from your folder
kokoro = Kokoro("kokoro-v1.0.int8.onnx", "voices-v1.0.bin")

# Sarcastic text to test his "vibe"
text = "I'm a skeleton running on a neural network. I have no skin in this game, literally."

print("Generating speech... hold on.")

# 'am_onyx' is a deep, resonant voice.
# Other options: 'am_michael', 'am_adam', 'af_sky'
samples, sample_rate = kokoro.create(text, voice="am_adam", speed=1.0, lang="en-us")

print("Playing audio now!")
sd.play(samples, sample_rate)
sd.wait()