import os
import sqlite3
import random
import string
from flask import Flask, render_template, request, redirect, session, url_for, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

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
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('hub.html', username=session['user'])

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
        else:
            return f"""
            <div style="text-align:center; margin-top:50px; font-family:sans-serif;">
                <h2>🔒 Private AI Gallery</h2>
                <p>Event Code: <b>{entered_code}</b></p>
                <p>You are joining as a Guest. To protect everyone's privacy, you can only see photos that have YOUR face in them.</p>
                <button style="padding:10px 20px; background:#3b82f6; color:white; border:none; border-radius:5px; font-weight:bold;">
                    Step 1: Upload Your Selfie to Match
                </button>
                <br><br>
                <p style="color:gray; font-size:12px;">(AI DeepFace Engine integration pending...)</p>
                <a href='/hub'>Back to Hub</a>
            </div>
            """
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
        
    # 6-character ka random uppercase aur number wala code generate karo
    event_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    
    with sqlite3.connect('giftgallery.db') as conn:
        cursor = conn.cursor()
        # Naya code aur user_id (host) ko database ki 'events' table me save karo
        cursor.execute("INSERT INTO events (event_code, host_id) VALUES (?, ?)", (event_code, session['user_id']))
        conn.commit()
        
    # Code banne ke baad seedha dashboard par bhej do
    return render_template('dashboard.html', event_code=event_code)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)