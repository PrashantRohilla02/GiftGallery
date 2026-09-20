import os
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
from dotenv import load_dotenv
load_dotenv() # Yeh .env file se keys automatically utha lega

import os
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
DB_URI = os.environ.get("DB_URI")
import json
import random
import string
import psycopg2
from flask import Flask, render_template, request, redirect, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from deepface import DeepFace
import cv2
import re
import base64
from sklearn.metrics.pairwise import cosine_distances
from supabase import create_client, Client
from PIL import Image
import io

app = Flask(__name__)
app.secret_key = 'super_secret_giftgallery_key' 

# --- SUPABASE CONFIGURATION ---
# --- SUPABASE CONFIGURATION (Secure Way) ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
DB_URI = os.environ.get("DB_URI")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_db_connection():
    return psycopg2.connect(DB_URI)

# ----------------- DATABASE INITIALIZATION -----------------
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
            event_name TEXT NOT NULL, 
            event_code TEXT UNIQUE NOT NULL,
            host_id INTEGER REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS photos (
            id SERIAL PRIMARY KEY,
            filename TEXT NOT NULL,
            event_code TEXT NOT NULL,
            uploader_id INTEGER REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS photo_embeddings (
            id SERIAL PRIMARY KEY,
            photo_id INTEGER REFERENCES photos(id) ON DELETE CASCADE,
            embedding TEXT NOT NULL
        )
    ''')
    conn.commit()
    cursor.close()
    conn.close()

init_db()
# -----------------------------------------------------------------

@app.route('/', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, password FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user and check_password_hash(user[2], password):
            session['user'] = user[1]       
            session['user_id'] = user[0]    
            return redirect(url_for('user_hub'))
        else:
            error = "Invalid Username or Password!"
                
    return render_template('login.html', error=error)

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        hashed_password = generate_password_hash(password) 
        
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, hashed_password))
            conn.commit()
            cursor.close()
            conn.close()
            return redirect(url_for('login')) 
        except Exception:
            conn.rollback()
            cursor.close()
            conn.close()
            error = "Username already exists! Please choose another."
                
    return render_template('register.html', error=error)

@app.route('/hub')
def user_hub():
    if 'user' not in session or 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT event_name, event_code FROM events WHERE host_id = %s", (user_id,))
    my_events = cursor.fetchall()
    
    cursor.execute('''
        SELECT DISTINCT e.event_name, e.event_code 
        FROM events e
        JOIN photos p ON e.event_code = p.event_code
        WHERE p.uploader_id = %s AND e.host_id != %s
    ''', (user_id, user_id))
    contributed_events = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('hub.html', username=session['user'], my_events=my_events, contributed_events=contributed_events)

@app.route('/join', methods=['POST'])
def join_event():
    if 'user' not in session:
        return redirect(url_for('login'))
    entered_code = request.form.get('event_code')
    return render_template('dashboard.html', event_code=entered_code)

@app.route('/gallery', methods=['POST'])
def view_gallery():
    if 'user' not in session or 'user_id' not in session:
        return redirect(url_for('login'))
        
    entered_code = request.form.get('gallery_code')
    current_user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT host_id FROM events WHERE event_code = %s", (entered_code,))
    event_row = cursor.fetchone()
    
    if not event_row:
        cursor.close()
        conn.close()
        return "<h3>Invalid Event Code!</h3><br><a href='/hub'>Back to Hub</a>"
        
    host_id = event_row[0]
    
    if current_user_id == host_id:
        cursor.execute("SELECT filename FROM photos WHERE event_code = %s", (entered_code,))
        photos_data = cursor.fetchall()
        cursor.close()
        conn.close()
        photos_list = [row[0] for row in photos_data]
        return render_template('gallery.html', event_code=entered_code, photos=photos_list, role="Host")
    else:
        cursor.close()
        conn.close()
        return render_template('guest_selfie.html', event_code=entered_code)

@app.route('/upload', methods=['POST'])
def upload_photo():
    if 'user' not in session or 'user_id' not in session:
        return redirect(url_for('login'))
        
    if 'photo' not in request.files:
        return "No photo uploaded!", 400
        
    files = request.files.getlist('photo') 
    event_code = request.form.get('event_code')
    uploaded_count = 0

    for file in files:
        if file and file.filename != '':
            filename = file.filename
            
            # --- IMAGE COMPRESSION LOGIC START ---
            img = Image.open(file)
            
            # Agar image PNG (RGBA) hai toh usko JPEG (RGB) mein convert karein
            if img.mode != 'RGB':
                img = img.convert('RGB')
                
            # Image ka resolution thoda kam karein (Max 1280x1280)
            img.thumbnail((1280, 1280))
            
            # Image ko compress karke bytes mein badlein (70% quality)
            img_io = io.BytesIO()
            img.save(img_io, format='JPEG', quality=70)
            compressed_bytes = img_io.getvalue()
            
            # Ab naya filename banayein (hamesha .jpg)
            filename = filename.rsplit('.', 1)[0] + '.jpg'
            # --- IMAGE COMPRESSION LOGIC END ---
            
            # 1. Supabase Storage par COMPRESSED photo upload karein
            storage_path = f"{event_code}/{filename}"
            try:
                supabase.storage.from_("event_photos").upload(
                    path=storage_path,
                    file=compressed_bytes,  # Yahan compressed_bytes pass kiya
                    file_options={"content-type": "image/jpeg"}
                )
            except Exception as e:
                print(f"⚠️ Storage upload error: {e}")

            # Public URL nikalna
            public_url = supabase.storage.from_("event_photos").get_public_url(storage_path)

            # 2. Database mein photo record save karein
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO photos (filename, event_code, uploader_id) VALUES (%s, %s, %s) RETURNING id", 
                           (public_url, event_code, session['user_id']))
            photo_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()
            conn.close()
            
            # 3. AI Face Embedding Extraction (ArcFace)
            embeddings_to_save = []
            # Temporarily save to local disk just for OpenCV reading
            temp_path = f"temp_{filename}"
            with open(temp_path, "wb") as f:
                f.write(compressed_bytes) # AI ko bhi compressed image denge

            img_array = cv2.imread(temp_path)
            if os.path.exists(temp_path):
                os.remove(temp_path)

            if img_array is not None:
                try:
                    faces = DeepFace.extract_faces(
                        img_path=img_array, 
                        detector_backend="retinaface", 
                        enforce_detection=False, 
                        align=True
                    )
                    for face_data in faces:
                        if face_data.get('confidence', 0) == 0: 
                            continue
                            
                        face_uint8 = (face_data["face"] * 255).astype("uint8")
                        embedding = DeepFace.represent(
                            img_path=face_uint8, 
                            model_name="ArcFace", 
                            detector_backend="skip", 
                            enforce_detection=False
                        )[0]["embedding"]
                        
                        embeddings_to_save.append(json.dumps(embedding))
                except Exception as e:
                    print(f"⚠️ Could not extract faces for {filename}: {e}")

            # 4. Save Embeddings to Supabase DB
            if embeddings_to_save:
                conn = get_db_connection()
                cursor = conn.cursor()
                for emb in embeddings_to_save:
                    cursor.execute("INSERT INTO photo_embeddings (photo_id, embedding) VALUES (%s, %s)",
                                   (photo_id, emb))
                conn.commit()
                cursor.close()
                conn.close()

            uploaded_count += 1
            
    return f"<h3>{uploaded_count} Photos successfully added to Event: {event_code}!</h3><br><a href='/hub'>Back to Hub</a>"

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/create_event', methods=['POST'])
def create_event():
    if 'user' not in session or 'user_id' not in session:
        return redirect(url_for('login'))
        
    event_name = request.form.get('event_name') 
    event_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO events (event_name, event_code, host_id) VALUES (%s, %s, %s)", 
                   (event_name, event_code, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()
        
    return render_template('dashboard.html', event_code=event_code, event_name=event_name)

@app.route('/match_faces', methods=['POST'])
def match_faces():
    if 'user' not in session or 'user_id' not in session:
        return redirect(url_for('login'))

    event_code = request.form.get('event_code')
    selfie_file = request.files.get('selfie')
    selfie_base64 = request.form.get('selfie_base64')

    save_path = None

    try:
        if selfie_file and selfie_file.filename != '':
            ext = os.path.splitext(selfie_file.filename)[1] or '.jpg'
            save_path = f"temp_selfie_{session['user_id']}{ext}"
            selfie_file.save(save_path)

        elif selfie_base64 and len(selfie_base64) > 50:
            save_path = f"temp_selfie_{session['user_id']}.jpg"
            image_data = re.sub(r'^data:image/.+;base64,', '', selfie_base64)
            with open(save_path, "wb") as fh:
                fh.write(base64.b64decode(image_data))
        else:
            return "No selfie provided!", 400

        img1_array = cv2.imread(save_path)
        if img1_array is None:
            return "Error reading uploaded selfie.", 400

        try:
            selfie_faces = DeepFace.extract_faces(
                img_path=img1_array, detector_backend="retinaface", enforce_detection=True, align=True
            )
            
            selfie_face_uint8 = (selfie_faces[0]["face"] * 255).astype("uint8")
            selfie_embedding = DeepFace.represent(
                img_path=selfie_face_uint8, model_name="ArcFace", detector_backend="skip", enforce_detection=False
            )[0]["embedding"]
            
        except Exception:
            return "Could not detect a face in your selfie. Please upload a clear front-facing photo.", 400

        matched_photos = set() 
        THRESHOLD = 0.68

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT p.filename, pe.embedding 
            FROM photos p
            JOIN photo_embeddings pe ON p.id = pe.photo_id
            WHERE p.event_code = %s
        ''', (event_code,))
        
        gallery_data = cursor.fetchall()
        cursor.close()
        conn.close()
        
        for filename, embedding_json in gallery_data:
            gallery_embedding = json.loads(embedding_json)
            distance = cosine_distances([selfie_embedding], [gallery_embedding])[0][0]
            
            if distance <= THRESHOLD:
                matched_photos.add(filename)

        matched_photos = list(matched_photos)

        return render_template(
            'gallery.html',
            event_code=event_code,
            photos=matched_photos,
            role="Guest (AI Filtered)"
        )

    finally:
        if save_path and os.path.exists(save_path):
            try:
                os.remove(save_path)
            except Exception as e:
                print(f"⚠️ Could not delete temp selfie: {e}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)