from firebase_admin import credentials, initialize_app, db

# Load service account key
cred = credentials.Certificate("serviceAccountKey.json")

# Initialize Firebase app
initialize_app(cred, {
    'databaseURL': 'https://self-balancing-7a9fe-default-rtdb.firebaseio.com/'
})

# ✅ Set root-level initialized
root_ref = db.reference('12_Plant_health_Irrigation_System')
root_ref.update({
    "initialized": True
})

# ✅ Set Sensor-level initialized
sensor_ref = db.reference('12_Plant_health_Irrigation_System/Sensor')
sensor_ref.update({
    "initialized": True
})

print("✅ Initialization flags added to Firebase.")
