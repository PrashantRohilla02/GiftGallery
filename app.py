import os
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

import sqlite3
import random
import string
import json
from flask import Flask, render_template, request, redirect, session, url_for, send_from_directory
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from deepface import DeepFace
import cv2
import re
import base64
from sklearn.metrics.pairwise import cosine_distances

app = Flask(__name__)
app.secret_key = 'super_secret_giftgallery_key' 

# Use absolute path for upload folder to avoid 404 errors
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


# ----------------- DATABASE LIFECYCLE MANAGEMENT -----------------
def init_db():
    with sqlite3.connect('giftgallery.db') as conn:
        cursor = conn.cursor()
        
        # 1. Users Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')
        
        # 2. Events Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_name TEXT NOT NULL, 
                event_code TEXT UNIQUE NOT NULL,
                host_id INTEGER,
                FOREIGN KEY (host_id) REFERENCES users (id)
            )
        ''')

        # 3. Photos Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                event_code TEXT NOT NULL,
                uploader_id INTEGER,
                FOREIGN KEY (uploader_id) REFERENCES users (id)
            )
        ''')

        # 4. NEW: Photo Embeddings Table (Stores AI vectors)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS photo_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                photo_id INTEGER,
                embedding TEXT NOT NULL,
                FOREIGN KEY (photo_id) REFERENCES photos (id)
            )
        ''')
        conn.commit()

init_db()
# -----------------------------------------------------------------

@app.route('/', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        with sqlite3.connect('giftgallery.db') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, password FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
            
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
        
        with sqlite3.connect('giftgallery.db') as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
                conn.commit()
                return redirect(url_for('login')) 
            except sqlite3.IntegrityError:
                error = "Username already exists! Please choose another."
                
    return render_template('register.html', error=error)

@app.route('/hub')
def user_hub():
    if 'user' not in session or 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    
    with sqlite3.connect('giftgallery.db') as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT event_name, event_code FROM events WHERE host_id = ?", (user_id,))
        my_events = cursor.fetchall()
        
        cursor.execute('''
            SELECT DISTINCT e.event_name, e.event_code 
            FROM events e
            JOIN photos p ON e.event_code = p.event_code
            WHERE p.uploader_id = ? AND e.host_id != ?
        ''', (user_id, user_id))
        contributed_events = cursor.fetchall()
        
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
    
    with sqlite3.connect('giftgallery.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT host_id FROM events WHERE event_code = ?", (entered_code,))
        event_row = cursor.fetchone()
        
        if not event_row:
            return "<h3>Invalid Event Code!</h3><br><a href='/hub'>Back to Hub</a>"
            
        host_id = event_row[0]
        
        if current_user_id == host_id:
            cursor.execute("SELECT filename FROM photos WHERE event_code = ?", (entered_code,))
            photos_data = cursor.fetchall()
            photos_list = [row[0] for row in photos_data]
            return render_template('gallery.html', event_code=entered_code, photos=photos_list, role="Host")
        else:
            return render_template('guest_selfie.html', event_code=entered_code)
        
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

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
            # Secure filename to prevent URL and path issues
            filename = secure_filename(file.filename)
            # Add random prefix to avoid collisions
            filename = f"{random.randint(1000,9999)}_{filename}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path) 
            
            # 1. QUICK DB WRITE
            with sqlite3.connect('giftgallery.db', timeout=20) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO photos (filename, event_code, uploader_id) VALUES (?, ?, ?)", 
                               (filename, event_code, session['user_id']))
                photo_id = cursor.lastrowid
                conn.commit()
            
            # 2. HEAVY AI LIFTING
            embeddings_to_save = []
            img_array = cv2.imread(file_path)
            if img_array is not None:
                try:
                    # AI face extraction
                    faces = DeepFace.extract_faces(
                        img_path=img_array, 
                        detector_backend="retinaface", 
                        enforce_detection=False, 
                        align=True
                    )
                    for face_data in faces:
                        if face_data.get('confidence', 0) < 0.8: # Ignore low confidence
                            continue
                            
                        face_uint8 = (face_data["face"] * 255).astype("uint8")
                        embedding = DeepFace.represent(
                            img_path=face_uint8, 
                            model_name="Facenet", 
                            detector_backend="skip", 
                            enforce_detection=False
                        )[0]["embedding"]
                        
                        embeddings_to_save.append(json.dumps(embedding))
                except Exception as e:
                    print(f"⚠️ Could not extract faces for {filename}: {e}")

            # 3. QUICK DB WRITE: Embeddings
            if embeddings_to_save:
                with sqlite3.connect('giftgallery.db', timeout=20) as conn:
                    cursor = conn.cursor()
                    for emb in embeddings_to_save:
                        cursor.execute("INSERT INTO photo_embeddings (photo_id, embedding) VALUES (?, ?)",
                                       (photo_id, emb))
                    conn.commit()

            uploaded_count += 1
            
    return redirect(url_for('user_hub'))


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
    
    with sqlite3.connect('giftgallery.db') as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO events (event_name, event_code, host_id) VALUES (?, ?, ?)", 
                       (event_name, event_code, session['user_id']))
        conn.commit()
        
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
        # ==========================================
        # 1. SAVE SELFIE
        # ==========================================
        if selfie_file and selfie_file.filename != '':
            ext = os.path.splitext(selfie_file.filename)[1] or '.jpg'
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_selfie_{session['user_id']}{ext}")
            selfie_file.save(save_path)

        elif selfie_base64 and len(selfie_base64) > 50:
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_selfie_{session['user_id']}.jpg")
            image_data = re.sub(r'^data:image/.+;base64,', '', selfie_base64)
            with open(save_path, "wb") as fh:
                fh.write(base64.b64decode(image_data))
        else:
            return "No selfie provided!", 400

        # ==========================================
        # 2. EXTRACT SELFIE EMBEDDING
        # ==========================================
        img1_array = cv2.imread(save_path)
        if img1_array is None:
            return "Error reading uploaded selfie.", 400

        try:
            selfie_faces = DeepFace.extract_faces(
                img_path=img1_array, detector_backend="retinaface", enforce_detection=True, align=True
            )
            
            selfie_face_uint8 = (selfie_faces[0]["face"] * 255).astype("uint8")
            selfie_embedding = DeepFace.represent(
                img_path=selfie_face_uint8, model_name="Facenet", detector_backend="skip", enforce_detection=False
            )[0]["embedding"]
            
        except Exception as e:
            # Render a nicer error page instead of a string
            return render_template('guest_selfie.html', event_code=event_code, error="Could not detect a face in your selfie. Please ensure your face is clearly visible.")


        # ==========================================
        # 3. COMPARE AGAINST PRE-CALCULATED DB EMBEDDINGS
        # ==========================================
        matched_photos = set() # Using a set to prevent duplicate filenames
        THRESHOLD = 0.40

        print("\n--- 🤖 FAST DB SEARCH STARTED ---")

        with sqlite3.connect('giftgallery.db') as conn:
            cursor = conn.cursor()
            
            # Fetch all stored embeddings for this specific event
            cursor.execute('''
                SELECT p.filename, pe.embedding 
                FROM photos p
                JOIN photo_embeddings pe ON p.id = pe.photo_id
                WHERE p.event_code = ?
            ''', (event_code,))
            
            gallery_data = cursor.fetchall()
            
            for filename, embedding_json in gallery_data:
                gallery_embedding = json.loads(embedding_json)
                
                # Calculate distance instantly without reading image files
                distance = cosine_distances([selfie_embedding], [gallery_embedding])[0][0]
                
                if distance <= THRESHOLD:
                    matched_photos.add(filename)
                    print(f"✅ Match Found in {filename} (distance={distance:.4f})")

        matched_photos = list(matched_photos)

        print("\n--- 🏁 FAST SEARCH COMPLETED ---")
        print(f"✅ Total matching photos: {len(matched_photos)}")

        return render_template(
            'gallery.html',
            event_code=event_code,
            photos=matched_photos,
            role="Guest (AI Filtered)"
        )

    finally:
        # ==========================================
        # 4. DELETE TEMP SELFIE
        # ==========================================
        if save_path and os.path.exists(save_path):
            try:
                os.remove(save_path)
            except Exception as e:
                print(f"⚠️ Could not delete temp selfie: {e}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)