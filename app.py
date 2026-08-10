import os
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'  # Ye TensorFlow ke saare warnings ko chup kara dega

import os
import sqlite3
import random
import string
from flask import Flask, render_template, request, redirect, session, url_for, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from deepface import DeepFace
import cv2

app = Flask(__name__)
app.secret_key = 'super_secret_giftgallery_key' 

UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ----------------- DATABASE LIFECYCLE MANAGEMENT -----------------
def init_db():
    # Database se connect karo (agar nahi hai toh SQLite khud bana dega)
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
        
        # 2. Events Table (Relational logic)
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
        conn.commit()

# Server start hone se pehle database initialize karo
init_db()
# -----------------------------------------------------------------

# 1. Login Page Route (Abhi simple logic hai, DB connect baad me karenge)
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
            
            # Agar user mila aur password sahi hai
            if user and check_password_hash(user[2], password):
                session['user'] = user[1]       # Username save kiya
                session['user_id'] = user[0]    # User ID save ki (aage event host link karne ke liye)
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
        hashed_password = generate_password_hash(password) # Password encrypt kar diya
        
        with sqlite3.connect('giftgallery.db') as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
                conn.commit()
                return redirect(url_for('login')) # Account banne ke baad login par bhejo
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
        
        # 1. Jo events is user ne khud banaye hain (HOST)
        cursor.execute("SELECT event_name, event_code FROM events WHERE host_id = ?", (user_id,))
        my_events = cursor.fetchall()
        
        # 2. Jo events me is user ne photos upload ki hain (GUEST)
        # JOIN laga kar hum un events ko filter kar rahe hain jiska ye user host nahi hai, par uploader zaroor hai
        cursor.execute('''
            SELECT DISTINCT e.event_name, e.event_code 
            FROM events e
            JOIN photos p ON e.event_code = p.event_code
            WHERE p.uploader_id = ? AND e.host_id != ?
        ''', (user_id, user_id))
        contributed_events = cursor.fetchall()
        
    return render_template('hub.html', 
                           username=session['user'], 
                           my_events=my_events, 
                           contributed_events=contributed_events)
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
        
        # 1. Pata karo ki is event ka Host (malik) kaun hai
        cursor.execute("SELECT host_id FROM events WHERE event_code = ?", (entered_code,))
        event_row = cursor.fetchone()
        
        if not event_row:
            return "<h3>Invalid Event Code!</h3><br><a href='/hub'>Back to Hub</a>"
            
        host_id = event_row[0]
        
        # 2. HOST VIEW: Agar current user hi host hai, toh saari photos dikhao
        if current_user_id == host_id:
            cursor.execute("SELECT filename FROM photos WHERE event_code = ?", (entered_code,))
            photos_data = cursor.fetchall()
            photos_list = [row[0] for row in photos_data]
            return render_template('gallery.html', event_code=entered_code, photos=photos_list, role="Host")
            
        # 3. GUEST VIEW: Yahan humara AI DeepFace wala jaadu aayega
        # 3. GUEST VIEW: AI Selfie Page par bhejo
        else:
            return render_template('guest_selfie.html', event_code=entered_code)
        
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/upload', methods=['POST'])
def upload_photo():
    if 'user' not in session or 'user_id' not in session:
        return redirect(url_for('login'))
        
    # 'photo' ki jagah form se multiple files aayengi
    if 'photo' not in request.files:
        return "No photo uploaded!", 400
        
    files = request.files.getlist('photo')  # getlist() sari photos ek list me le aayega
    event_code = request.form.get('event_code')
    uploaded_count = 0

    with sqlite3.connect('giftgallery.db') as conn:
        cursor = conn.cursor()
        
        # Har ek photo par loop chalayenge
        for file in files:
            if file and file.filename != '':
                filename = file.filename
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path) 
                
                # Database me entry
                cursor.execute("INSERT INTO photos (filename, event_code, uploader_id) VALUES (?, ?, ?)", 
                               (filename, event_code, session['user_id']))
                uploaded_count += 1
        
        conn.commit()
            
    return f"<h3>{uploaded_count} Photos successfully added to Event: {event_code}!</h3><br><a href='/hub'>Back to Hub</a>"

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/create_event', methods=['POST'])
def create_event():
    if 'user' not in session or 'user_id' not in session:
        return redirect(url_for('login'))
        
    event_name = request.form.get('event_name') # HTML form se event ka naam layega
    event_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    
    with sqlite3.connect('giftgallery.db') as conn:
        cursor = conn.cursor()
        # FIX YAHAN HAI: event_name ko INSERT statement me add kiya gaya hai
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
    
    # File ko usi ke original naam/extension ke sath save karenge
    if selfie_file and selfie_file.filename != '':
        # Extension nikalne ke liye
        ext = os.path.splitext(selfie_file.filename)[1] 
        if not ext: ext = '.jpg'
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_selfie_{session['user_id']}{ext}")
        selfie_file.save(save_path)
        
    elif selfie_base64 and len(selfie_base64) > 50:
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_selfie_{session['user_id']}.jpg")
        image_data = re.sub('^data:image/.+;base64,', '', selfie_base64)
        with open(save_path, "wb") as fh:
            fh.write(base64.b64decode(image_data))
    else:
        return "No selfie provided!", 400

    # 🚨 NAYA LOGIC: OpenCV se photo ko explicitly read karo
    img1_array = cv2.imread(save_path)
    
    if img1_array is None:
        print("❌ CRITICAL ERROR: OpenCV could not read the saved selfie!")
        return "Error reading the uploaded photo format. Try a different photo.", 400

    with sqlite3.connect('giftgallery.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT filename FROM photos WHERE event_code = ?", (event_code,))
        event_photos = cursor.fetchall()
        
    matched_photos = []
    
    print("\n--- 🤖 AI FACE MATCHING STARTED ---")
    for (photo_name,) in event_photos:
        target_path = os.path.join(app.config['UPLOAD_FOLDER'], photo_name)
        
        # Gallery photo ko bhi array me convert karo
        img2_array = cv2.imread(target_path)
        
        if img2_array is None:
            print(f"⚠️ Skipping {photo_name}: Could not read file.")
            continue
            
        try:
            print(f"🔍 Scanning photo: {photo_name}...")
            
            # DeepFace me ab paths nahi, direct image ka data ja raha hai
            result = DeepFace.verify(
                img1_path=img1_array, 
                img2_path=img2_array, 
                model_name="Facenet", 
                enforce_detection=False
            )
            print(f"   -> Match Status: {result['verified']} (Distance: {round(result['distance'], 3)})")
            
            if result['verified']:
                matched_photos.append(photo_name)
        except Exception as e:
            print(f"❌ Error checking {photo_name}: {e}")
            continue
            
    print("--- 🏁 AI MATCHING COMPLETED ---\n")
            
    # Cleanup
    if os.path.exists(save_path):
        os.remove(save_path)
        
    return render_template('gallery.html', event_code=event_code, photos=matched_photos, role="Guest (AI Filtered)")    
    return render_template('gallery.html', event_code=event_code, photos=matched_photos, role="Guest (AI Filtered)")
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)