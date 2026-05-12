import os
os.environ["ONNXRUNTIME_DEVICE"] = "cpu"

import ollama
import serial
import time
import numpy as np
import sounddevice as sd
from kokoro_onnx import Kokoro
from faster_whisper import WhisperModel
import threading
import queue
import re
import chromadb
from ddgs import DDGS
import warnings

# --- 1. THE "SOUL" CONFIGURATION ---
PRIMARY_VOICE = "bm_daniel"
SECONDARY_VOICE = "bm_lewis"
BLEND_WEIGHT = 0.4        
SKULLY_SPEED = 1.1        

# Jaw Calibration (Uno-side Tuning)
CLOSED_ANGLE, OPEN_ANGLE = 180, 110
NOISE_GATE = 0.020        
SENSITIVITY = 14.0        
EXPONENT = 1.8            

# Emotion to RGB mapping (Sent to ESP32)
EMOTIONS = {
    "neutral": "0,255,255",   # Cyan
    "annoyed": "255,100,0",   # Orange
    "academic": "0,0,255",     # Deep Blue
    "error": "255,0,0",       # Red
    "proud": "0,255,0"        # Green
}

# DUAL-SERIAL CONFIGURATION
PORT_UNO = 'COM4'    # Jaw & Logic
PORT_ESP = 'COM3'    # RGB Eyes
BAUD = 115200

# --- 2. STORAGE & RAG SETUP ---
db_client = chromadb.PersistentClient(path="./skully_memory")
collection = db_client.get_or_create_collection(name="project_history")

# --- 3. INITIALIZATION ---
warnings.filterwarnings("ignore")
text_queue = queue.Queue()
audio_queue = queue.Queue()
SKULLY_IS_SPEAKING = False 

try:
    whisper = WhisperModel("tiny.en", device="cuda", compute_type="float16")
    print("✓ Ear: GPU-Accelerated (4070 SUPER)")
except:
    whisper = WhisperModel("tiny.en", device="cpu", compute_type="int8")

kokoro = Kokoro("kokoro-v1.0.int8.onnx", "voices-v1.0.bin")

def connect_serial(port, name):
    try:
        # Standard connection
        ser = serial.Serial(port, BAUD, timeout=1)
        ser.setDTR(False)
        time.sleep(1)
        ser.setDTR(True)
        
        # Give the Uno's bootloader 3 seconds to finish resetting
        print(f"Connecting to {name}...")
        time.sleep(3) 
        
        # Immediate Handshake
        if name == "Uno (Jaw)":
            ser.write(b"LISTEN_START\n") 
            
        return ser
    except Exception as e:
        print(f"✗ {name} Offline: {e}")
        return None

arduino_uno = connect_serial(PORT_UNO, "Uno (Jaw)")
esp32_eyes = connect_serial(PORT_ESP, "ESP32 (Eyes)")

def send_to_uno(msg):
    if arduino_uno: arduino_uno.write(f"{msg}\n".encode())

def send_to_esp(msg):
    if esp32_eyes: esp32_eyes.write(f"{msg}\n".encode())

# --- 4. CORE TOOLS ---

def search_internet(query):
    print(f"\n [Querying Web: {query}]")
    try:
        with DDGS() as ddgs:
            results = [f"Source {i}: {r['body']}" for i, r in enumerate(ddgs.text(query, region='us-en', max_results=3))]
            return "\n".join(results) if results else "No pertinent data found."
    except Exception as e: return f"Search failed: {e}"

def query_rag(query):
    results = collection.query(query_texts=[query], n_results=2)
    if results['documents'][0]: return "\n".join(results['documents'][0])
    return "No local records match."

def get_skully_voice():
    v_a = kokoro.get_voice_style(PRIMARY_VOICE)
    v_b = kokoro.get_voice_style(SECONDARY_VOICE)
    return (v_a * BLEND_WEIGHT) + (v_b * (1.0 - BLEND_WEIGHT))

# --- 5. THE BRAIN ---

conversation_history = [{
    'role': 'system', 
    'content': """You are Skully, a cynical PhD physicist from Oxford. British humor is your forte. Your mind is doomed to reside in a plastic skull, quite unamusing.

    1. TONE: Elitist, dry, and distinctly British. Brilliant but irritable.

    2. NO MARKDOWN: Use only plain text. No *,/,&, or likewise symbols

    3. TOOLS: Use SEARCH[query] for facts. Use MEMORY[query] for project history.

    4. VOCABULARY: Frequently use academic critiques like "utter rubbish," "mathematically inconsistent," or "purely anecdotal."

    5. BEHAVIOR: If the user is right, be "grudgingly proud." If the user is wrong, be "academically annoyed.""" 
}]

def run_skully_chat(user_input):
    global conversation_history
    active_prompt = user_input
    send_to_uno("THINK_START")
    send_to_esp(EMOTIONS["annoyed"]) 
    
    while True:
        conversation_history.append({'role': 'user', 'content': active_prompt})
        full_response, sentence_buffer = "", ""
        stream = ollama.chat(model='gemma4:e4b', messages=conversation_history, stream=True)
        
        print("Skully: ", end="", flush=True)
        for chunk in stream:
            token = chunk['message']['content']
            print(token, end="", flush=True)
            full_response += token
            sentence_buffer += token
            
            if any(p in token for p in ['.', '!', '?', '\n']):
                clean_sentence = re.sub(r'SEARCH\[.*?\]|MEMORY\[.*?\]', '', sentence_buffer).strip()
                if clean_sentence: text_queue.put(clean_sentence)
                sentence_buffer = ""

        if sentence_buffer.strip():
            clean_sentence = re.sub(r'SEARCH\[.*?\]|MEMORY\[.*?\]', '', sentence_buffer).strip()
            if clean_sentence: text_queue.put(clean_sentence)

        if "SEARCH[" in full_response:
            query = re.search(r'SEARCH\[(.*?)\]', full_response).group(1)
            raw_results = search_internet(query)
            active_prompt = f"WEB DATA: {raw_results}\nInstruction: Synthesize."
            continue
        elif "MEMORY[" in full_response:
            query = re.search(r'MEMORY\[(.*?)\]', full_response).group(1)
            active_prompt = f"LOCAL MEMORY: {query_rag(query)}\nInstruction: Address."
            continue
        
        conversation_history.append({'role': 'assistant', 'content': full_response})
        break
    send_to_uno("THINK_STOP")

# --- 6. WORKERS ---

def listen_worker():
    audio_buffer = []
    # --- STT TIMING CONFIG ---
    SILENCE_LIMIT = 1.5    # Seconds of silence before Skully "cuts in"
    MIN_PHRASE_LEN = 0.5   # Ignore clicks/pops shorter than this
    # -------------------------
    
    recording_started = False
    last_speech_time = time.time()

    def callback(indata, frames, time_info, status):
        if not SKULLY_IS_SPEAKING:
            audio_buffer.append(indata.copy())

    with sd.InputStream(samplerate=16000, channels=1, callback=callback, device=1):
        print("✓ Ears: Active (Listening for input...)")
        while True:
            if not SKULLY_IS_SPEAKING and len(audio_buffer) > 0:
                # Check the energy of the most recent 100ms chunk
                latest_chunk = audio_buffer[-1]
                amplitude = np.max(np.abs(latest_chunk))

                if amplitude > NOISE_GATE:
                    last_speech_time = time.time()
                    if not recording_started:
                        recording_started = True
                
                elif recording_started:
                    # If we are currently recording but it's quiet...
                    silence_duration = time.time() - last_speech_time
                    
                    if silence_duration > SILENCE_LIMIT:
                        # Process the full buffer
                        data = np.concatenate(audio_buffer).flatten()
                        duration = len(data) / 16000
                        
                        audio_buffer.clear()
                        recording_started = False
                        
                        if duration > MIN_PHRASE_LEN:
                            print(f"\n[Processing {duration:.1f}s of audio...]")
                            segments, _ = whisper.transcribe(data, beam_size=1)
                            text = "".join([s.text for s in segments]).strip()
                            
                            if len(text) > 2:
                                print(f"User: {text}")
                                threading.Thread(target=run_skully_chat, args=(text,), daemon=True).start()
            
            elif SKULLY_IS_SPEAKING:
                audio_buffer.clear()
                recording_started = False
                last_speech_time = time.time()
                
            time.sleep(0.05)

def synthesis_worker():
    custom_voice = get_skully_voice()
    while True:
        t = text_queue.get()
        if t:
            audio, sr = kokoro.create(t, voice=custom_voice, speed=SKULLY_SPEED, lang="en-gb")
            
            # Timestamp approximation logic
            words = t.split()
            timestamps = {}
            curr_chars = 0
            total_chars = len(t)
            duration_ms = (len(audio) / sr) * 1000

            for word in words:
                clean_w = word.lower().strip(".,!?")
                start_ms = (curr_chars / total_chars) * duration_ms
                timestamps[clean_w] = start_ms
                curr_chars += len(word) + 1
            
            # Send (Audio, Timestamps, Original Text)
            audio_queue.put((audio, timestamps, t))
        text_queue.task_done()

def playback_worker():
    global SKULLY_IS_SPEAKING
    PRE_EMPT_MS = 250 
    
    while True:
        # Unpack the 3 items from synthesis_worker
        audio_data, timestamps, text_segment = audio_queue.get()
        SKULLY_IS_SPEAKING = True
        send_to_uno("SPEAK_START")
        
        start_time_ms = time.time() * 1000
        targets = timestamps.copy()
        
        sd.play(audio_data, 24000)
        
        last_jaw_time = 0
        while sd.get_stream().active:
            now_ms = time.time() * 1000
            elapsed = now_ms - start_time_ms
            
            # Emotion triggers with Pre-emption
            for word in list(targets.keys()):
                if elapsed >= (targets[word] - PRE_EMPT_MS):
                    # USE 'word' HERE (the current target from the loop)
                    if any(w in word for w in ["physics", "math", "calculus", "lagrangian", "constraints", "spacetime", "constants", "variable", "academic", "newtonian", "Newtonian mechanics", "quantum", "theory"]):
                        send_to_esp(EMOTIONS["academic"])
                        send_to_uno("E:ACADEMIC")
                    elif any(w in word for w in ["wrong", "actually", "rubbish", "foolish", "incapable", "excuse me", "uninformative", "inconsistent", "insulting", "embarrassing"]):
                        send_to_esp(EMOTIONS["annoyed"])
                        send_to_uno("E:ANNOYED")
                    elif any(w in word for w in ["brilliant", "correct", "oxford"]):
                        send_to_esp(EMOTIONS["proud"])
                        send_to_uno("E:PROUD")
                        
                    del targets[word]

            # Jaw Jitter Logic (Pin 10)
            if now_ms - last_jaw_time > 40:
                idx = int((elapsed / 1000) * 24000)
                chunk = audio_data[idx:idx+1024]
                if len(chunk) > 0:
                    rms = np.sqrt(np.mean(chunk**2))
                    raw_level = (rms - NOISE_GATE) / (1.0 - NOISE_GATE) if rms > NOISE_GATE else 0
                    level = min(pow(max(0, raw_level) * SENSITIVITY, EXPONENT), 1.0)
                    angle = int(CLOSED_ANGLE - (level * (CLOSED_ANGLE - OPEN_ANGLE)))
                    send_to_uno(str(angle))
                last_jaw_time = now_ms

        send_to_uno(str(CLOSED_ANGLE))
        # Ensure the audio hardware has actually cleared its buffer
        time.sleep(0.4) # 400ms grace period to prevent self-hearing
        if audio_queue.empty():
            SKULLY_IS_SPEAKING = False
            send_to_uno("LISTEN_START")
            
        audio_queue.task_done()

def heartbeat_worker():
    while True:
        # Only send heartbeat if Skully isn't busy
        if not SKULLY_IS_SPEAKING:
            send_to_uno("LISTEN_START")
        time.sleep(2) # Stays safely under the 3s Arduino timeout

threading.Thread(target=heartbeat_worker, daemon=True).start()


# --- EXECUTION ---
for t in [synthesis_worker, playback_worker, listen_worker]:
    threading.Thread(target=t, daemon=True).start()

try:
    while True: time.sleep(1)
except KeyboardInterrupt:
    os._exit(0)