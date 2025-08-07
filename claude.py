from flask import Flask, render_template, Response, jsonify, request, stream_with_context
import cv2
import numpy as np
import tensorflow as tf
import requests
import urllib.parse
import time
import os
import json
from onvif import ONVIFCamera
import zeep
import threading
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, db

# 🔥 Path to your service account key JSON
cred = credentials.Certificate("serviceAccountKey.json")

# 🔥 Initialize the Firebase app with your Realtime Database URL
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://self-balancing-7a9fe-default-rtdb.firebaseio.com/'
})

# ✅ Reference to CurrentData
current_data_ref = db.reference('/12_Plant_Health_Irrigation_System/Sensor/CurrentData')

# Initialize flags in Firebase (merged from init_flags.py)
def initialize_firebase_flags():
    try:
        # Root-level initialized
        db.reference('/12_Plant_Health_Irrigation_System').update({
            "initialized": True
        })

        # Sensor-level initialized
        db.reference('/12_Plant_Health_Irrigation_System/Sensor').update({
            "initialized": True
        })

        # Initialize relay node if it doesn't exist
        relay_ref = db.reference('/12_Plant_Health_Irrigation_System/Relay')
        relay_data = relay_ref.get()
        if not relay_data:
            relay_ref.update({
                "Automatic": "0",
                "Manual": "0",
                "Timer": "0",
                "TimerDuration": "0",  # Added field to store timer duration
                "TimerEnd": "0"        # Added field to store timer end timestamp
            })

        print("✅ Initialization flags added to Firebase.")
        return True
    except Exception as e:
        print(f"Error initializing Firebase flags: {e}")
        return False

# Call the initialization function
initialize_firebase_flags()

app = Flask(__name__)

# Global variables for SSE clients
sse_clients = {}
sse_lock = threading.Lock()

# Global variable for active timers
active_timers = {}
timer_lock = threading.Lock()

# Load the trained plant disease detection model
model = tf.keras.models.load_model('train2.h5')

# Dictionary mapping disease labels to pesticide recommendations and precautionary advice
disease_info_dict = {
    'healthy': {
        'pesticide': [
            "No pesticide needed",
            "Maintain regular watering",
            "Apply balanced fertilizer",
            "Inspect plants weekly for pests",
            "Keep weeds under control"
        ],
        'precaution': [
            "Monitor soil moisture levels",
            "Ensure proper spacing for airflow",
            "Use clean gardening tools",
            "Remove any damaged leaves promptly",
            "Keep field sanitation high"
        ],
        'crop_suggestion': [
            "Continue with current crop",
            "Experiment with companion planting",
            "Consider intercropping with legumes",
            "Rotate with nitrogen‑fixing crops",
            "Maintain soil health with cover crops"
        ]
    },

    'powdery': {
        'pesticide': [
            "Use sulfur fungicides",
            "Apply potassium bicarbonate sprays",
            "Use horticultural oils",
            "Try neem oil formulations",
            "Alternate products to prevent resistance"
        ],
        'precaution': [
            "Avoid overhead irrigation",
            "Prune to improve airflow",
            "Remove infected leaves immediately",
            "Water early to allow leaves to dry",
            "Sanitize tools between uses"
        ],
        'crop_suggestion': [
            "Plant powdery mildew‑resistant varieties",
            "Avoid high‑humidity prone crops",
            "Intercrop with resistant species",
            "Choose early‑maturing varieties",
            "Practice crop rotation"
        ]
    },

    'rust': {
        'pesticide': [
            "Use copper-based fungicides",
            "Apply Mancozeb sprays as recommended",
            "Use organic fungicides like neem oil",
            "Alternate fungicide groups to reduce resistance",
            "Apply sprays during early infection stages"
        ],
        'precaution': [
            "Remove infected leaves immediately",
            "Avoid watering foliage late in the day",
            "Maintain proper row spacing",
            "Clean up fallen leaves from soil surface",
            "Use certified disease‑free seeds"
        ],
        'crop_suggestion': [
            "Choose rust‑tolerant seed varieties",
            "Plan crop rotation with non‑host plants",
            "Consider resistant hybrids for long term",
            "Avoid planting in known rust hotspots",
            "Introduce cover crops to enrich soil"
        ]
    },

    'virus': {
        'pesticide': [
            "Remove infected plants completely",
            "Use insecticide soap sprays for vectors",
            "Introduce sticky traps to reduce pests",
            "Control aphids and whiteflies promptly",
            "Apply neem oil as a preventive"
        ],
        'precaution': [
            "Use certified virus‑free seedlings",
            "Disinfect tools after use",
            "Remove weeds around the field",
            "Control insect vectors effectively",
            "Avoid planting near infected fields"
        ],
        'crop_suggestion': [
            "Use virus‑resistant plant varieties",
            "Rotate with non‑host crops",
            "Choose tolerant hybrids",
            "Avoid continuous monocropping",
            "Consider barrier crops as protection"
        ]
    },

    'background': {
        'pesticide': [],
        'precaution': [],
        'crop_suggestion': []
    }
}

# Global variables
detected_disease = ''
camera_stream = None
camera_connected = False
stream_url = None
latest_frame = None
frame_lock = threading.Lock()
read_thread_running = False

# CP Plus Camera credentials
USERNAME = "admin"
PASSWORD = "admin@123"
CAMERA_IP = "192.168.29.229"
PORT = 8000

# Soil moisture control settings
SOIL_DEBOUNCE_TIME = 5  # seconds to wait before reacting to soil moisture changes
last_soil_change_time = 0
last_soil_value = None

# Custom converter for zeep to handle xsd:dateTime values properly
def zeep_pythonvalue(self, xmlvalue):
    return xmlvalue

# Patch zeep to handle custom data types
zeep.xsd.simple.AnySimpleType.pythonvalue = zeep_pythonvalue

def get_stream_uri(mycam, profile):
    """Get the stream URI from a camera profile"""
    try:
        media_service = mycam.create_media_service()
        
        # Get stream URI
        request = media_service.create_type('GetStreamUri')
        request.ProfileToken = profile.token
        request.StreamSetup = {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}}
        
        response = media_service.GetStreamUri(request)
        return response.Uri
    except Exception as e:
        print(f"Error getting stream URI: {e}")
        return None

def connect_to_camera():
    """Connect to the CP Plus camera and return a valid stream URL"""
    global camera_connected, stream_url
    
    try:
        print(f"Connecting to ONVIF camera at {CAMERA_IP}:{PORT}...")
        
        # Connect to the camera
        mycam = ONVIFCamera(CAMERA_IP, PORT, USERNAME, PASSWORD)
        
        # Get device information
        try:
            device_info = mycam.devicemgmt.GetDeviceInformation()
            print(f"✓ Successfully connected to camera via ONVIF!")
            print(f"Device Information:")
            print(f"  Manufacturer: {device_info.Manufacturer}")
            print(f"  Model: {device_info.Model}")
            print(f"  Firmware Version: {device_info.FirmwareVersion}")
            print(f"  Serial Number: {device_info.SerialNumber}")
        except Exception as e:
            print(f"Could not get device info: {e}")
        
        # Get camera profiles
        media_service = mycam.create_media_service()
        profiles = media_service.GetProfiles()
        
        print(f"\nFound {len(profiles)} stream profiles:")
        
        streaming_urls = []
        
        # Try each profile to get a stream URL
        for i, profile in enumerate(profiles):
            print(f"\nProfile {i+1}: {profile.Name}")
            
            # Get stream URI
            stream_uri = get_stream_uri(mycam, profile)
            if stream_uri:
                print(f"✓ RTSP Stream URI: {stream_uri}")
                streaming_urls.append(stream_uri)
            else:
                print("✗ Could not get RTSP Stream URI")
        
        if not streaming_urls:
            print("✗ No streaming URLs found via ONVIF.")
            
            # Try some common URL patterns for CP Plus cameras
            encoded_password = urllib.parse.quote(PASSWORD)
            common_urls = [
                f"rtsp://{USERNAME}:{encoded_password}@{CAMERA_IP}:{PORT}/cam/realmonitor?channel=1&subtype=0",
                f"rtsp://{USERNAME}:{encoded_password}@{CAMERA_IP}:{PORT}/h264/ch01/main/av_stream",
                f"rtsp://{USERNAME}:{encoded_password}@{CAMERA_IP}:{PORT}/Streaming/Channels/101",
                f"rtsp://{USERNAME}:{encoded_password}@{CAMERA_IP}:{PORT}/live/ch00_0",
                f"rtsp://{USERNAME}:{encoded_password}@{CAMERA_IP}:{PORT}/live",
                f"rtsp://{USERNAME}:{encoded_password}@{CAMERA_IP}:{PORT}/stream"
            ]
            
            print("\nTrying common CP Plus URL patterns:")
            for url in common_urls:
                print(f"Testing: {url}")
                streaming_urls.append(url)
        
        # Set RTSP transport to TCP using environment variable
        os.environ["OPENCV_FFMPEG_TRANSPORT_OPTION"] = "rtsp_transport=tcp"
        
        # Test each URL until we find one that works
        for url in streaming_urls:
            print(f"\nAttempting to stream video from URL: {url}")
            
            # Use OpenCV to test the stream
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            
            if not cap.isOpened():
                print(f"✗ Failed to open video stream with URL: {url}")
                continue
            
            # Try to read a frame to verify
            ret, frame = cap.read()
            if not ret:
                print("✗ Could not read frames from this URL")
                cap.release()
                continue
            
            print(f"✓ Successfully opened video stream with URL: {url}")
            cap.release()
            
            # Save the working URL
            stream_url = url
            camera_connected = True
            return url
        
        # If we reach here, no URL worked
        print("\n✗ Could not connect to any camera stream.")
        camera_connected = False
        return None
        
    except Exception as e:
        print(f"Error connecting to camera: {e}")
        camera_connected = False
        return None

def detect_disease(frame):
    # Preprocess the frame for model input
    resized_frame = cv2.resize(frame, (224, 224))
    normalized_frame = resized_frame / 255.0
    input_frame = np.expand_dims(normalized_frame, axis=0)
    
    # Make predictions using the loaded model
    predictions = model.predict(input_frame)
    predicted_class = np.argmax(predictions[0])
    confidence = predictions[0][predicted_class]
    
    # Class mapping based on ['Background', 'Healthy', 'Powdery', 'Rust', 'Virus']
    if predicted_class == 0:
        disease = 'background'
    elif predicted_class == 1:
        disease = 'healthy'
    elif predicted_class == 2:
        disease = 'powdery'
    elif predicted_class == 3:
        disease = 'rust'
    elif predicted_class == 4:
        disease = 'virus'
    else:
        disease = 'background'
    
    return disease, confidence

def frame_reader():
    global latest_frame, read_thread_running, camera_connected, stream_url

    # Ensure camera connected
    if not camera_connected or stream_url is None:
        stream_url = connect_to_camera()

    os.environ["OPENCV_FFMPEG_TRANSPORT_OPTION"] = "rtsp_transport=tcp"
    cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 3840)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2160)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FPS, 60)

    read_thread_running = True
    while read_thread_running:
        ret, frame = cap.read()
        if not ret:
            print("Frame read failed in background thread. Reconnecting...")
            camera_connected = False
            cap.release()
            time.sleep(1)
            stream_url = connect_to_camera()
            if stream_url is None:
                time.sleep(5)
                continue
            cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1080)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            cap.set(cv2.CAP_PROP_FPS, 15)
            continue
        
        with frame_lock:
            latest_frame = frame

    cap.release()

def generate_frames():
    global detected_disease, latest_frame, frame_lock

    frame_process_counter = 0

    while True:
        if latest_frame is None:
            time.sleep(0.05)  # wait a bit if no frame yet
            continue
        
        with frame_lock:
            frame = latest_frame.copy()

        frame_process_counter += 1

        # Process every 20th frame to reduce CPU load
        if frame_process_counter % 20 == 0:
            disease, confidence = detect_disease(frame)
            if disease != 'background':
                detected_disease = disease
                # Broadcast disease update to SSE clients
                broadcast_update("disease", {"disease": disease, "confidence": float(confidence)})

        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 100]
        ret, buffer = cv2.imencode('.jpg', frame, encode_param)
        frame_bytes = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

# Function to broadcast updates to all SSE clients
def broadcast_update(update_type, data):
    message = json.dumps({'type': update_type, 'data': data})
    with sse_lock:
        for client_id in list(sse_clients):
            try:
                client_queue = sse_clients[client_id]
                client_queue.put(f"data: {message}\n\n")
            except Exception as e:
                print(f"Error broadcasting to client {client_id}: {e}")
                # Remove problematic client
                sse_clients.pop(client_id, None)

# Function to check and manage soil moisture based control
def check_soil_moisture_control():
    global last_soil_change_time, last_soil_value
    
    try:
        # Get current soil moisture value
        current_data = current_data_ref.get() or {}
        soil_value = current_data.get('Soil')
        current_time = time.time()
        
        # Skip if no soil data
        if soil_value is None:
            return
            
        # Convert to int if possible
        try:
            soil_value = int(soil_value)
        except (ValueError, TypeError):
            # If not convertible to int, keep as is
            pass
            
        # First reading, just store it
        if last_soil_value is None:
            last_soil_value = soil_value
            last_soil_change_time = current_time
            return
            
        # Check if value has changed
        if soil_value != last_soil_value:
            print(f"Soil moisture changed: {last_soil_value} -> {soil_value}")
            last_soil_value = soil_value
            last_soil_change_time = current_time
            return
            
        # If value hasn't changed for DEBOUNCE_TIME, take action
        if (current_time - last_soil_change_time) >= SOIL_DEBOUNCE_TIME:
            relay_ref = db.reference('/12_Plant_Health_Irrigation_System/Relay')
            relay_data = relay_ref.get() or {}
            
            # Don't change anything if Manual mode is active
            if relay_data.get('Manual') == "1":
                print("🛑 Manual mode is active, skipping soil moisture control")
                return
            
            # Control Automatic mode based on soil moisture if Manual is not active
            if soil_value == 1 or soil_value == "1":
                # Soil is DRY - activate irrigation
                print("🌱 Soil is DRY - activating automatic irrigation")
                relay_ref.update({
                    "Automatic": "1"
                })
                broadcast_update("control_action", {
                    "action": "automatic_on",
                    "reason": "Soil is dry",
                    "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
            elif soil_value == 0 or soil_value == "0":
                # Soil is WET - deactivate irrigation
                print("💧 Soil is WET - deactivating automatic irrigation")
                relay_ref.update({
                    "Automatic": "0"
                })
                broadcast_update("control_action", {
                    "action": "automatic_off",
                    "reason": "Soil is wet",
                    "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
    except Exception as e:
        print(f"Error in soil moisture control: {e}")

# Function to check and process active timers
def check_active_timers():
    try:
        relay_ref = db.reference('/12_Plant_Health_Irrigation_System/Relay')
        relay_data = relay_ref.get() or {}
        
        # Check if timer is active
        if relay_data.get('Timer') == "1":
            # Get timer end timestamp
            timer_end_str = relay_data.get('TimerEnd', '0')
            
            try:
                timer_end = float(timer_end_str)
                current_time = time.time()
                
                # If timer has expired
                if current_time >= timer_end and timer_end > 0:
                    print(f"⏱️ Timer expired at {datetime.fromtimestamp(timer_end).strftime('%H:%M:%S')}")
                    
                    # Don't change Manual mode when timer expires
                    update_data = {
                        "Timer": "0",
                        "TimerEnd": "0",
                        "Automatic": "0"  # Set Automatic to 0 when Timer expires
                    }
                    
                    # Update Firebase
                    relay_ref.update(update_data)
                    
                    # Notify clients
                    broadcast_update("timer_expired", {
                        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    })
            except (ValueError, TypeError):
                print(f"Invalid timer end timestamp: {timer_end_str}")
    except Exception as e:
        print(f"Error checking active timers: {e}")

# Function to run background tasks
def background_tasks():
    while True:
        check_soil_moisture_control()
        check_active_timers()
        time.sleep(1)  # Check every second

@app.route('/')
def index():
    print("🔥 index() route hit!")

    current_data_ref = db.reference('/12_Plant_Health_Irrigation_System/Sensor/CurrentData')
    current_data = current_data_ref.get() or {}

    history_data_ref = db.reference('/12_Plant_Health_Irrigation_System/Sensor/SensorData')
    history_data = history_data_ref.get() or {}

    print("Fetched current sensor data:")
    print(current_data)
    print("Fetched history sensor data:")
    print(history_data)

    return render_template('index.html', current=current_data, history=history_data)

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/disease_info/<disease>')
def disease_info(disease):
    info = disease_info_dict.get(disease, {})
    return jsonify({
        'pesticide': info.get('pesticide', []),
        'precaution': info.get('precaution', []),
        'crop_suggestion': info.get('crop_suggestion', [])
    })

@app.route('/detected_disease')
def get_detected_disease():
    global detected_disease
    return jsonify({'disease': detected_disease})

@app.route('/climate_data')
def climate_data():
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    api_key = "e1d854c0293b3c6adeb8121ded279f44"
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&units=metric&appid={api_key}"
        response = requests.get(url)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/climate/<lat>/<lon>')
def climate(lat, lon):
    API_KEY = "ad3a6dcbcc671ec5516aac7635f601de"
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&units=metric&appid={API_KEY}"
    try:
        r = requests.get(url, timeout=5)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/camera_status')
def camera_status():
    global camera_connected, stream_url
    return jsonify({
        'connected': camera_connected,
        'stream_url': stream_url if camera_connected else None
    })

@app.route('/reconnect_camera')
def reconnect_camera():
    global camera_connected, stream_url
    stream_url = connect_to_camera()
    return jsonify({
        'success': camera_connected,
        'message': 'Camera connected successfully' if camera_connected else 'Failed to connect to camera'
    })

# Get sensor history data
def get_sensor_history():
    ref = db.reference('/12_Plant_Health_Irrigation_System/Sensor/SensorData')
    sensor_data = ref.get()

    if not sensor_data:
        return []

    result = []
    for timestamp, values in sensor_data.items():
        data_point = {
            "id": timestamp,
            "Temperature": values.get("Temperature", 0),
            "Humidity": values.get("Humidity", 0),
            "Soil": values.get("Soil", 0),
            "Water": values.get("Water", 0)
        }
        result.append(data_point)

    return result

# Get sensor logs for charting
def get_sensor_logs():
    try:
        ref = db.reference('/12_Plant_Health_Irrigation_System/Sensor/SensorData')
        sensor_data = ref.get()

        if not isinstance(sensor_data, dict):
            print("⚠️ SensorData is not a dictionary:", sensor_data)
            return []

        result = []
        for timestamp, values in sensor_data.items():
            if not isinstance(values, dict):
                print(f"⚠️ Skipping non-dict entry at {timestamp}: {values}")
                continue  # Skip invalid data

            data_point = {
                "timestamp": timestamp,
                "temperature": values.get("Temperature", 0),
                "humidity": values.get("Humidity", 0),
                "soilMoisture": values.get("Soil", 0),
                "water": values.get("Water", 0)
            }
            result.append(data_point)

        return result

    except Exception as e:
        print("❌ Error in get_sensor_logs():", str(e))
        return {"error": str(e)}

@app.route('/relay/status')
def relay_status():
    try:
        ref = db.reference('/12_Plant_Health_Irrigation_System/Relay')
        relay_data = ref.get() or {}
        
        # Add remaining time for timer if active
        if relay_data.get('Timer') == "1" and relay_data.get('TimerEnd'):
            try:
                timer_end = float(relay_data.get('TimerEnd', '0'))
                current_time = time.time()
                remaining_seconds = max(0, int(timer_end - current_time))
                relay_data['TimerRemaining'] = remaining_seconds
                
                # Also include the original timer duration for UI
                relay_data['TimerDurationUI'] = relay_data.get('TimerDuration', '0')
            except (ValueError, TypeError):
                relay_data['TimerRemaining'] = 0
        
        return jsonify(relay_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/relay/toggle_manual', methods=['POST'])
def relay_toggle_manual():
    """Toggle the Manual mode on/off"""
    try:
        ref = db.reference('/12_Plant_Health_Irrigation_System/Relay')
        
        # Get current status
        current_status = ref.get() or {}
        current_manual = current_status.get('Manual', '0')
        
        # Toggle Manual status (0 to 1, or 1 to 0)
        new_manual = "0" if current_manual == "1" else "1"
        
        # Only update Manual, don't touch Automatic
        ref.update({
            "Manual": new_manual
        })
        
        # Broadcast the update to all clients
        relay_data = ref.get() or {}
        broadcast_update("relay_update", relay_data)
        
        return jsonify({
            "status": "ok", 
            "mode": "manual_on" if new_manual == "1" else "manual_off"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/relay/automatic', methods=['POST'])
def relay_automatic():
    try:
        data = request.get_json()
        automatic_value = data.get('value', "1")  # Default to "1" if not specified
        
        ref = db.reference('/12_Plant_Health_Irrigation_System/Relay')
        
        # If setting Automatic to "0" and Timer is "1", also set Timer to "0"
        # If setting Automatic to "1", leave Timer as is
        relay_data = ref.get() or {}
        
        if automatic_value == "0" and relay_data.get('Timer') == "1":
            # When turning off Automatic mode, also turn off Timer if it's active
            ref.update({
                "Automatic": "0", 
                "Manual": "0",
                "Timer": "0",
                "TimerEnd": "0"
            })
            print("✅ Turned off Automatic mode and also deactivated Timer")
        else:
            # Normal behavior
            ref.update({
                "Automatic": automatic_value, 
                "Manual": "0"
            })
            print(f"✅ Set Automatic mode to {automatic_value}")
        
        # Broadcast the update to all clients
        relay_data = ref.get() or {}
        broadcast_update("relay_update", relay_data)
        
        return jsonify({"status": "ok", "mode": "automatic", "value": automatic_value})
    except Exception as e:
        print(f"Error in automatic route: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/relay/timer', methods=['POST'])
def relay_timer():
    """Set timer value with improved handling"""
    try:
        data = request.get_json()
        timer_value = data.get('timer', "0")
        timer_seconds = int(data.get('seconds', 0))
        
        # Validate timer seconds (must be positive and reasonable)
        if timer_seconds < 0:
            timer_seconds = 0
        elif timer_seconds > 3600:  # Max 1 hour
            timer_seconds = 3600
            
        ref = db.reference('/12_Plant_Health_Irrigation_System/Relay')
        current_data = ref.get() or {}
        
        # Don't affect Manual mode settings
        # If manual mode is active, don't change it
        update_data = {}
        
        # If timer is being activated
        if timer_value == "1" and timer_seconds > 0:
            # Calculate end time
            current_time = time.time()
            end_time = current_time + timer_seconds
            
            # Update Timer settings
            update_data.update({
                "Timer": "1",
                "TimerDuration": str(timer_seconds),
                "TimerEnd": str(end_time),
                "Automatic": "1"  # Set Automatic to 1 when Timer is 1
            })
            
            # Only update manual if it's not already active
            if current_data.get("Manual") != "1":
                update_data["Manual"] = "0"
                
            print(f"⏱️ Timer set for {timer_seconds} seconds, ending at {datetime.fromtimestamp(end_time).strftime('%H:%M:%S')}")
            print(f"✅ Automatic mode activated with timer")
        else:
            # Timer is being deactivated
            update_data.update({
                "Timer": "0",
                "TimerEnd": "0",
                "Automatic": "0"  # Set Automatic to 0 when Timer is 0
            })
            print(f"⏱️ Timer deactivated, automatic mode also turned off")
        
        # Apply updates
        ref.update(update_data)
        
        # Broadcast the update to all clients
        relay_data = ref.get() or {}
        if timer_value == "1":
            relay_data['TimerRemaining'] = timer_seconds
        broadcast_update("relay_update", relay_data)
        
        return jsonify({
            "status": "ok", 
            "Timer": timer_value,
            "seconds": timer_seconds
        })
    except Exception as e:
        print(f"Error in timer route: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/relay/manual', methods=['POST'])
def relay_manual():
    try:
        ref = db.reference('/12_Plant_Health_Irrigation_System/Relay')
        current_state = ref.get() or {}
        
        # Toggle behavior - if Manual is "1", set to "0"; otherwise set to "1"
        new_manual_state = "0" if current_state.get("Manual") == "1" else "1"
        
        # Only update the Manual field, don't touch Automatic
        ref.update({
            "Manual": new_manual_state
        })
        
        # Broadcast the update to all clients
        relay_data = ref.get() or {}
        broadcast_update("relay_update", relay_data)
        
        return jsonify({
            "status": "ok", 
            "mode": "manual", 
            "state": new_manual_state
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
# 👉👉 ROUTE: Get live Sensor CurrentData
@app.route('/sensor/current', methods=['GET'])
def sensor_current():
    ref = db.reference('/12_Plant_Health_Irrigation_System/Sensor/CurrentData')
    data = ref.get()
    return jsonify(data or {})

@app.route('/sensor/update', methods=['POST'])
def update_sensor():
    data = request.get_json()
    humidity = data.get('Humidity', 0)
    soil = data.get('Soil', 0)
    temperature = data.get('Temperature', 0)
    water = data.get('Water', 0)

    # Update CurrentData
    sensor_ref = db.reference('/12_Plant_Health_Irrigation_System/Sensor/CurrentData')
    sensor_ref.update({
        "Humidity": humidity,
        "Soil": soil,
        "Temperature": temperature,
        "Water": water
    })

    # ✅ Append to SensorData with auto-incremented ID
    sensor_data_ref = db.reference('/12_Plant_Health_Irrigation_System/Sensor/SensorData')

    # Get current data
    existing_data = sensor_data_ref.get()
    next_id = "001"
    if existing_data:
        existing_ids = sorted(existing_data.keys())
        last_id = existing_ids[-1]
        next_id = f"{int(last_id) + 1:03d}"

    # Store snapshot under new ID
    sensor_data_ref.child(next_id).set({
        "Humidity": humidity,
        "Soil": soil,
        "Temperature": temperature,
        "Water": water
    })

    # Broadcast update to connected clients
    broadcast_update("sensor_update", {
        "Humidity": humidity,
        "Soil": soil,
        "Temperature": temperature,
        "Water": water,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

    return jsonify({
        "status": "ok", 
        "message": "Sensor data updated and logged", 
        "entry_id": next_id
    })

@app.route('/initialize_flags')
def initialize_flags():
    try:
        # Call the initialization function
        success = initialize_firebase_flags()
        
        if success:
            return jsonify({"status": "ok", "message": "Flags initialized in Firebase"})
        else:
            return jsonify({"status": "error", "message": "Failed to initialize flags"}), 500
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/sensor/logs')
def sensor_logs():
    try:
        print("📥 Hit /sensor/logs")
        data = get_sensor_logs()
        print("✅ Data returned from get_sensor_logs():", data)
        return jsonify(data)
    except Exception as e:
        print("❌ Error in /sensor/logs:", str(e))
        return jsonify({'error': str(e)}), 500

# Server-Sent Events for real-time updates
@app.route('/firebase-updates')
def firebase_updates():
    """SSE endpoint for real-time Firebase updates"""
    def generate():
        from queue import Queue
        import uuid
        
        client_id = str(uuid.uuid4())
        queue = Queue()
        
        # Register this client
        with sse_lock:
            sse_clients[client_id] = queue
            
        try:
            # Send initial data
            current_data_ref = db.reference('/12_Plant_Health_Irrigation_System/Sensor/CurrentData')
            current_data = current_data_ref.get() or {}
            
            yield f"data: {json.dumps({'type': 'initial', 'data': current_data})}\n\n"
            
            # Send relay status
            relay_ref = db.reference('/12_Plant_Health_Irrigation_System/Relay')
            relay_data = relay_ref.get() or {}
            
            # Add remaining time for timer if active
            if relay_data.get('Timer') == "1" and relay_data.get('TimerEnd'):
                try:
                    timer_end = float(relay_data.get('TimerEnd', '0'))
                    current_time = time.time()
                    remaining_seconds = max(0, int(timer_end - current_time))
                    relay_data['TimerRemaining'] = remaining_seconds
                except (ValueError, TypeError):
                    relay_data['TimerRemaining'] = 0
            
            yield f"data: {json.dumps({'type': 'relay_update', 'data': relay_data})}\n\n"
            
            # Send disease data
            global detected_disease
            if detected_disease:
                yield f"data: {json.dumps({'type': 'disease', 'data': {'disease': detected_disease}})}\n\n"
            
            # Keep connection open for real-time updates
            while True:
                # Wait for new messages in the queue
                try:
                    message = queue.get(block=True, timeout=30)
                    yield message
                except:
                    # Send heartbeat message every 30 seconds
                    yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.now().timestamp()})}\n\n"
                
        finally:
            # Unregister client when connection closes
            with sse_lock:
                if client_id in sse_clients:
                    sse_clients.pop(client_id)
    
    return Response(stream_with_context(generate()), mimetype="text/event-stream")

# Server-Sent Events for real-time sensor data
@app.route('/sensor/current/realtime')
def sensor_current_realtime():
    """SSE endpoint for real-time sensor data updates"""
    def generate():
        last_data = None
        
        while True:
            # Get the latest data
            ref = db.reference('/12_Plant_Health_Irrigation_System/Sensor/CurrentData')
            data = ref.get()
            
            # Only send if data has changed
            if data != last_data:
                last_data = data
                # Format as SSE event
                yield f"data: {json.dumps(data)}\n\n"
            
            # Sleep for a short period
            time.sleep(2)
    
    return Response(stream_with_context(generate()), mimetype="text/event-stream")

# Function to monitor Firebase for changes
def setup_firebase_listeners():
    """Setup Firebase listeners to broadcast changes to SSE clients"""
    print("Setting up Firebase listeners...")
    
    # Monitor sensor data changes
    def monitor_sensor_data():
        last_data = None
        while True:
            try:
                current_data = db.reference('/12_Plant_Health_Irrigation_System/Sensor/CurrentData').get()
                if current_data != last_data and current_data is not None:
                    # Data has changed, broadcast to clients
                    broadcast_update("sensor_update", current_data)
                    last_data = current_data
            except Exception as e:
                print(f"Error monitoring sensor data: {e}")
            time.sleep(1.5)  # Poll every 1.5 seconds
    
    # Monitor relay changes
    def monitor_relay_changes():
        last_relay_data = None
        while True:
            try:
                relay_data = db.reference('/12_Plant_Health_Irrigation_System/Relay').get()
                
                # Add remaining time for active timers
                if relay_data and relay_data.get('Timer') == "1" and relay_data.get('TimerEnd'):
                    try:
                        timer_end = float(relay_data.get('TimerEnd', '0'))
                        current_time = time.time()
                        remaining_seconds = max(0, int(timer_end - current_time))
                        relay_data = dict(relay_data)  # Make a copy to avoid modifying the original
                        relay_data['TimerRemaining'] = remaining_seconds
                    except (ValueError, TypeError):
                        pass
                
                if relay_data != last_relay_data and relay_data is not None:
                    # Relay data has changed, broadcast to clients
                    broadcast_update("relay_update", relay_data)
                    last_relay_data = relay_data
            except Exception as e:
                print(f"Error monitoring relay data: {e}")
            time.sleep(1.5)  # Poll every 1.5 seconds
    
    # Start monitoring threads
    sensor_thread = threading.Thread(target=monitor_sensor_data)
    sensor_thread.daemon = True
    sensor_thread.start()
    
    relay_thread = threading.Thread(target=monitor_relay_changes)
    relay_thread.daemon = True
    relay_thread.start()

# Start a background thread to connect to the camera when the app starts
def init_camera():
    global stream_url
    stream_url = connect_to_camera()
    thread = threading.Thread(target=frame_reader)
    thread.daemon = True
    thread.start()


if __name__ == '__main__':
    # Start the camera connection in a background thread
    camera_thread = threading.Thread(target=init_camera)
    camera_thread.daemon = True
    camera_thread.start()
    
    # Setup Firebase listeners
    setup_firebase_listeners()
    
    # Start background tasks
    background_thread = threading.Thread(target=background_tasks)
    background_thread.daemon = True
    background_thread.start()
    
    # Wait a moment for the camera to connect
    time.sleep(2)
    
    # Start the Flask app
    app.run(debug=True, host='0.0.0.0', port=5000)