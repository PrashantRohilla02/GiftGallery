import os
import sqlite3
from flask import Flask, render_template, request, redirect, session, url_for

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
        conn.commit()

# Server start hone se pehle database initialize karo
init_db()
# -----------------------------------------------------------------

# 1. Login Page Route (Abhi simple logic hai, DB connect baad me karenge)
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username:
            session['user'] = username
            return redirect(url_for('user_hub'))
            
    return render_template('login.html')

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
    if 'user' not in session:
        return redirect(url_for('login'))
    entered_code = request.form.get('gallery_code')
    return f"<h3>Showing Gallery for Event: {entered_code}</h3><br><a href='/hub'>Back to Hub</a>"

@app.route('/upload', methods=['POST'])
def upload_photo():
    if 'user' not in session:
        return redirect(url_for('login'))
    if 'photo' not in request.files:
        return "No photo uploaded!", 400
        
    file = request.files['photo']
    event_code = request.form.get('event_code')

    if file and file.filename != '':
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(file_path)
        return f"<h3>Photo uploaded by {session['user']} for event {event_code}!</h3><br><a href='/hub'>Back to Hub</a>"
        
    return "No selected file", 400

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)