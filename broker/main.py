import os
import asyncio
from datetime import datetime
import paho.mqtt.client as mqtt
from nicegui import app, ui, run
from faster_whisper import WhisperModel

# --- SETUP ---
BROKER_IP = "localhost"
RECORDINGS_DIR = "recordings"
MODEL_PATH = "./whisper-tiny-samromur-ct2"

os.makedirs(RECORDINGS_DIR, exist_ok=True)
os.environ["HF_HUB_OFFLINE"] = "1"

print("Hleð inn Whisper líkani...")
whisper_model = WhisperModel(
    MODEL_PATH, 
    device="cpu", 
    compute_type="int8", 
    local_files_only=True
)
print("Whisper líkan tilbúið!")

app.add_static_files('/audio', RECORDINGS_DIR)

# Geymir niðurstöður úr hljóðritunum: { filepath: texti }
transcriptions = {}

loop = None  # Asyncio event loop

def transcribe_audio(filepath: str) -> str:
    """Hljóðritar skrá með Whisper (CPU þungt fall)."""
    try:
        segments, info = whisper_model.transcribe(filepath, language="is")
        text = " ".join([segment.text for segment in segments])
        return text.strip() if text else "(Enginn texti fannst)"
    except Exception as e:
        return f"Villa við hljóðritun: {e}"

async def process_transcription(filepath: str):
    """Sér um hljóðritun á skrá án þess að frysta viðmótið."""
    transcriptions[filepath] = "Hljóðritar..."
    refresh_recordings_list()

    # Keyrum CPU-þunga Whisper vinnsluna í sér þræði
    text = await run.io_bound(transcribe_audio, filepath)
    transcriptions[filepath] = text
    
    print(f"Hljóðritun lokið [{filepath}]: {text}")
    refresh_recordings_list()

async def process_incoming_audio(sender: str, payload: bytes, forward_topic: str):
    """Sér um öll skref þegar nýtt MQTT hljóð berst."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{sender}_{timestamp}.wav"
    filepath = os.path.join(RECORDINGS_DIR, filename)

    # 1. Vista hljóðskrá
    with open(filepath, "wb") as f:
        f.write(payload)
    print(f"Hljóðskrá vistuð: {filepath}")

    # 2. Framsenda strax á hitt tækið
    mqtt_client.publish(forward_topic, payload)

    # 3. Láta notanda vita
    ui.notify(f"Nýtt hljóð barst frá {sender}!", type='info')
    
    # 4. Hefja hljóðritun
    await process_transcription(filepath)

# --- MQTT MÓTTAK ---
def on_connect(client, userdata, flags, rc, properties=None):
    print("Raspberry Pi 4 er tengdur við Mosquitto broker!")
    client.subscribe("zero1/#")
    client.subscribe("zero2/#")

def on_message(client, userdata, msg):
    print(f"\n[PI 4 MÓTTEKIÐ] Topic: {msg.topic}")

    sender = None
    forward_topic = None

    if msg.topic == "zero1/hljod":
        sender = "zero1"
        forward_topic = "zero2/mottekid_hljod"
    elif msg.topic == "zero2/hljod":
        sender = "zero2"
        forward_topic = "zero1/mottekid_hljod"

    if sender and loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(
            process_incoming_audio(sender, msg.payload, forward_topic), 
            loop
        )

# Uppsetning MQTT Client
mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

def start_mqtt():
    global loop
    loop = asyncio.get_running_loop()
    mqtt_client.connect(BROKER_IP, 1883, 60)
    mqtt_client.loop_start()

def stop_mqtt():
    mqtt_client.loop_stop()

app.on_startup(start_mqtt)
app.on_shutdown(stop_mqtt)

# --- NICEGUI NOTANDAVIÐMÓT ---
recordings_container = None

def refresh_recordings_list():
    if recordings_container is None:
        return
    
    recordings_container.clear()
    files = sorted(os.listdir(RECORDINGS_DIR), reverse=True)
    audio_files = [f for f in files if f.endswith('.wav')]

    with recordings_container:
        if not audio_files:
            ui.label("Engar hljóðupptökur fundust í möppunni.").classes("text-gray-500 italic")
            return

        for fname in audio_files:
            fpath = os.path.join(RECORDINGS_DIR, fname)
            
            # Ef skráin hefur ekki verið unnin ennþá, byrjum við að hljóðrita hana
            if fpath not in transcriptions:
                transcriptions[fpath] = "Bíður eftir hljóðritun..."
                # Ef loop er virkt, ræsum við hljóðritun í bakgrunni
                if loop and loop.is_running():
                    asyncio.create_task(process_transcription(fpath))

            text_status = transcriptions.get(fpath, "Bíður eftir hljóðritun...")

            with ui.card().classes('w-full mb-3 p-4 shadow-md'):
                with ui.row().classes('w-full items-center justify-between'):
                    ui.label(fname).classes('font-bold text-lg')
                    ui.audio(f'/audio/{fname}').classes('w-64')

                ui.label(f"Texti: {text_status}").classes('text-gray-700 mt-2 font-medium')

@ui.page('/')
def main_page():
    global recordings_container
    
    ui.label('Hljóðupptökur og MQTT Stjórnborð').classes('text-2xl font-bold mb-4')

    with ui.row().classes('mb-4 gap-4'):
        # Hnappur sem endurhleður alla síðuna í vafranum
        ui.button('Endurhlaða síðu', on_click=lambda: ui.run_javascript('location.reload()')).props('icon=refresh')

    ui.separator().classes('mb-4')

    recordings_container = ui.column().classes('w-full max-w-3xl')
    refresh_recordings_list()

ui.run(title="MQTT Hljóðkerfi", port=8080, reload=False)
