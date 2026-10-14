import time
import subprocess
import os
import RPi.GPIO as GPIO
import paho.mqtt.client as mqtt

# --- STILLINGAR ---
BROKER_IP = "10.201.48.131"   # IP-talan á Raspberry Pi 4 (Broker)
BUTTON_PIN = 17               # Takki á ReSpeaker HAT
WAV_FILENAME = "upptaka.wav"  # Upptökuskrá
AUDIO_CARD = "plughw:0,0"     # Hljóðkortið hjá Pi Zero (Athugaðu með 'arecord -l')

# Topics fyrir MQTT
MY_SEND_TOPIC = "zero2/hljod"           # Sendir upptökur hingað á Pi 4
MY_RECEIVE_TOPIC = "zero2/mottekid_hljod" # Hlustar hér ef hitt Pi Zero sendir

# Stýribreytur
is_recording = False
recording_process = None

# --- MQTT MÓTTAKA ---
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Tengdur við MQTT Broker (Pi 4)!")
        client.subscribe(MY_RECEIVE_TOPIC)
    else:
        print(f"Tenging mislukkaðist, villukóði: {rc}")

def on_message(client, userdata, msg):
    print(f"\n[MÓTTEKIÐ] Hljóðskrá berst frá hinum Pi Zero!")
    with open("mottekid_hljod.wav", "wb") as f:
        f.write(msg.payload)
    print("Hljóðskrá vistuð sem 'mottekid_hljod.wav'.")
    
    subprocess.run(["aplay", "-D", AUDIO_CARD, "mottekid_hljod.wav"])

# --- RÆSA MQTT CLIENT ---
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

print(f"Tengist við Pi 4 ({BROKER_IP})...")
client.connect(BROKER_IP, 1883, 60)
client.loop_start()  # Hlustar í bakgrunni

# --- GPIO TAKKA STILLINGAR ---
GPIO.setmode(GPIO.BCM)
# ReSpeaker takkinn dregur pinnann í LOW þegar ýtt er á hann
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# --- UPPTÖKUFÖLL ---
def start_recording():
    global recording_process, is_recording
    print("\n[UPPTAKA HAFIN] Takið upp... (Ýttu aftur á takkann til að stöðva)")
    
    # Eyðum eldri skrá ef hún er til
    if os.path.exists(WAV_FILENAME):
        os.remove(WAV_FILENAME)
        
    # Keyrum 'arecord' í bakgrunni (Subprocess)
    cmd = ["arecord", "-D", AUDIO_CARD, "-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "wav", WAV_FILENAME]
    recording_process = subprocess.Popen(cmd)
    is_recording = True

def stop_recording_and_send():
    global recording_process, is_recording
    print("[UPPTÖKU LOKIÐ] Stöðva upptöku...")
    
    # Stöðvum arecord ferlið snyrtilega
    if recording_process:
        recording_process.terminate()
        recording_process.wait()
        recording_process = None
        
    is_recording = False
    time.sleep(0.5) # Gefum kerfinu stutta stund til að loka skránni

    # Sendum .wav skrána yfir MQTT
    if os.path.exists(WAV_FILENAME):
        print(f"Sendi '{WAV_FILENAME}' til Pi 4...")
        with open(WAV_FILENAME, "rb") as f:
            file_bytes = f.read()
        client.publish(MY_SEND_TOPIC, file_bytes)
        print("Hljóðskrá send!")
    else:
        print("VILLA: Upptökuskrá fannst ekki!")

# --- AÐALHYRINGUR (MAIN LOOP) ---
print("\nKerfið er tilbúið! Ýttu á takkann á ReSpeaker HAT til að hefja upptöku.")

try:
    last_button_state = GPIO.input(BUTTON_PIN)
    
    while True:
        current_button_state = GPIO.input(BUTTON_PIN)
        
        # Ef ýtt er á takkann (state breytist úr HIGH í LOW)
        if last_button_state == GPIO.HIGH and current_button_state == GPIO.LOW:
            time.sleep(0.05) # Debounce vörn
            
            if not is_recording:
                start_recording()
            else:
                stop_recording_and_send()
                
        last_button_state = current_button_state
        time.sleep(0.05)

except KeyboardInterrupt:
    print("\nStöðva dagskrá...")

finally:
    if is_recording and recording_process:
        recording_process.terminate()
    GPIO.cleanup()
    client.loop_stop()
    client.disconnect()
