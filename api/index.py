# api/index.py - Vercel Compatible Version
from flask import Flask, render_template, Response, jsonify, request, stream_with_context
import os
import json
import time
from datetime import datetime, timedelta
import requests
import urllib.parse

# Import Firebase (lighter version for serverless)
import firebase_admin
from firebase_admin import credentials, db

app = Flask(__name__, 
           template_folder='../templates',
           static_folder='../static')

# Initialize Firebase with environment variables instead of file
def init_firebase():
    try:
        # Use environment variables for Firebase credentials
        firebase_config = {
            "type": os.getenv("FIREBASE_TYPE"),
            "project_id": os.getenv("FIREBASE_PROJECT_ID"),
            "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": os.getenv("FIREBASE_PRIVATE_KEY", "").replace('\\n', '\n'),
            "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.getenv("FIREBASE_CLIENT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_CERT_URL")
        }
        
        # Only initialize if not already done
        if not firebase_admin._apps:
            cred = credentials.Certificate(firebase_config)
            firebase_admin.initialize_app(cred, {
                'databaseURL': os.getenv('FIREBASE_DATABASE_URL', 'https://self-balancing-7a9fe-default-rtdb.firebaseio.com/')
            })
        
        return True
    except Exception as e:
        print(f"Firebase initialization error: {e}")
        return False

# Initialize Firebase
firebase_initialized = init_firebase()

# Disease info dictionary (keeping your existing data)
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
    # ... (rest of your disease_info_dict remains the same)
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

@app.route('/')
def index():
    try:
        if not firebase_initialized:
            return render_template('index.html', 
                                 current={}, 
                                 history={}, 
                                 error="Firebase not initialized")
        
        current_data_ref = db.reference('/12_Plant_Health_Irrigation_System/Sensor/CurrentData')
        current_data = current_data_ref.get() or {}

        history_data_ref = db.reference('/12_Plant_Health_Irrigation_System/Sensor/SensorData')
        history_data = history_data_ref.get() or {}

        return render_template('index.html', current=current_data, history=history_data)
    except Exception as e:
        return render_template('index.html', current={}, history={}, error=str(e))

@app.route('/disease_info/<disease>')
def disease_info(disease):
    info = disease_info_dict.get(disease, {})
    return jsonify({
        'pesticide': info.get('pesticide', []),
        'precaution': info.get('precaution', []),
        'crop_suggestion': info.get('crop_suggestion', [])
    })

@app.route('/climate_data')
def climate_data():
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    api_key = os.getenv("OPENWEATHER_API_KEY", "e1d854c0293b3c6adeb8121ded279f44")
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&units=metric&appid={api_key}"
        response = requests.get(url, timeout=10)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/climate/<lat>/<lon>')
def climate(lat, lon):
    API_KEY = os.getenv("OPENWEATHER_API_KEY_2", "ad3a6dcbcc671ec5516aac7635f601de")
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&units=metric&appid={API_KEY}"
    try:
        r = requests.get(url, timeout=10)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)})

# Simplified camera status (remove complex camera functionality for serverless)
@app.route('/camera_status')
def camera_status():
    return jsonify({
        'connected': False,
        'stream_url': None,
        'message': 'Camera streaming not available in serverless deployment'
    })

@app.route('/video_feed')
def video_feed():
    def generate_placeholder():
        # Return a placeholder response for video feed
        yield (b'--frame\r\n'
               b'Content-Type: text/plain\r\n\r\n'
               b'Video streaming not available in serverless mode\r\n')
    
    return Response(generate_placeholder(), mimetype='multipart/x-mixed-replace; boundary=frame')

# Sensor and relay routes (Firebase-dependent, keep if Firebase works)
@app.route('/relay/status')
def relay_status():
    try:
        if not firebase_initialized:
            return jsonify({"error": "Firebase not initialized"}), 500
            
        ref = db.reference('/12_Plant_Health_Irrigation_System/Relay')
        relay_data = ref.get() or {}
        
        # Add remaining time for timer if active
        if relay_data.get('Timer') == "1" and relay_data.get('TimerEnd'):
            try:
                timer_end = float(relay_data.get('TimerEnd', '0'))
                current_time = time.time()
                remaining_seconds = max(0, int(timer_end - current_time))
                relay_data['TimerRemaining'] = remaining_seconds
                relay_data['TimerDurationUI'] = relay_data.get('TimerDuration', '0')
            except (ValueError, TypeError):
                relay_data['TimerRemaining'] = 0
        
        return jsonify(relay_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/relay/toggle_manual', methods=['POST'])
def relay_toggle_manual():
    try:
        if not firebase_initialized:
            return jsonify({"error": "Firebase not initialized"}), 500
            
        ref = db.reference('/12_Plant_Health_Irrigation_System/Relay')
        current_status = ref.get() or {}
        current_manual = current_status.get('Manual', '0')
        new_manual = "0" if current_manual == "1" else "1"
        
        ref.update({"Manual": new_manual})
        
        return jsonify({
            "status": "ok", 
            "mode": "manual_on" if new_manual == "1" else "manual_off"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/relay/automatic', methods=['POST'])
def relay_automatic():
    try:
        if not firebase_initialized:
            return jsonify({"error": "Firebase not initialized"}), 500
            
        data = request.get_json()
        automatic_value = data.get('value', "1")
        
        ref = db.reference('/12_Plant_Health_Irrigation_System/Relay')
        relay_data = ref.get() or {}
        
        if automatic_value == "0" and relay_data.get('Timer') == "1":
            ref.update({
                "Automatic": "0", 
                "Manual": "0",
                "Timer": "0",
                "TimerEnd": "0"
            })
        else:
            ref.update({
                "Automatic": automatic_value, 
                "Manual": "0"
            })
        
        return jsonify({"status": "ok", "mode": "automatic", "value": automatic_value})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/sensor/current', methods=['GET'])
def sensor_current():
    try:
        if not firebase_initialized:
            return jsonify({"error": "Firebase not initialized"}), 500
            
        ref = db.reference('/12_Plant_Health_Irrigation_System/Sensor/CurrentData')
        data = ref.get()
        return jsonify(data or {})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/sensor/update', methods=['POST'])
def update_sensor():
    try:
        if not firebase_initialized:
            return jsonify({"error": "Firebase not initialized"}), 500
            
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

        # Add to SensorData with timestamp
        sensor_data_ref = db.reference('/12_Plant_Health_Irrigation_System/Sensor/SensorData')
        existing_data = sensor_data_ref.get()
        next_id = "001"
        if existing_data:
            existing_ids = sorted(existing_data.keys())
            last_id = existing_ids[-1]
            next_id = f"{int(last_id) + 1:03d}"

        sensor_data_ref.child(next_id).set({
            "Humidity": humidity,
            "Soil": soil,
            "Temperature": temperature,
            "Water": water
        })

        return jsonify({
            "status": "ok", 
            "message": "Sensor data updated and logged", 
            "entry_id": next_id
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/sensor/logs')
def sensor_logs():
    try:
        if not firebase_initialized:
            return jsonify({"error": "Firebase not initialized"}), 500
            
        ref = db.reference('/12_Plant_Health_Irrigation_System/Sensor/SensorData')
        sensor_data = ref.get()

        if not isinstance(sensor_data, dict):
            return jsonify([])

        result = []
        for timestamp, values in sensor_data.items():
            if not isinstance(values, dict):
                continue

            data_point = {
                "timestamp": timestamp,
                "temperature": values.get("Temperature", 0),
                "humidity": values.get("Humidity", 0),
                "soilMoisture": values.get("Soil", 0),
                "water": values.get("Water", 0)
            }
            result.append(data_point)

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Health check endpoint
@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "firebase": firebase_initialized,
        "timestamp": datetime.now().isoformat()
    })

# For Vercel
if __name__ == '__main__':
    app.run(debug=True)
