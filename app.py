import os
from flask import Flask, render_template, request, redirect, session, url_for

app = Flask(__name__)
# Session secure rakhne ke liye ek secret key zaroori hoti hai
app.secret_key = 'super_secret_giftgallery_key' 

UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# 1. Login Page Route
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Yaha future me SQLite database check lagega
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Abhi ke liye simple dummy login (koi bhi naam daalo, login ho jayega)
        if username:
            session['user'] = username
            return redirect(url_for('user_hub'))
            
    return render_template('login.html')

# 2. Main User Hub (Jaha 2 options milenge)
@app.route('/hub')
def user_hub():
    # Agar user login nahi hai, toh wapas login par bhejo
    if 'user' not in session:
        return redirect(url_for('login'))
        
    return render_template('hub.html', username=session['user'])

# 3. Join Event (Upload Photos) Route
@app.route('/join', methods=['POST'])
def join_event():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    entered_code = request.form.get('event_code')
    return render_template('dashboard.html', event_code=entered_code)

# 4. View Gallery Route (Photos dekhne ke liye)
@app.route('/gallery', methods=['POST'])
def view_gallery():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    entered_code = request.form.get('gallery_code')
    # Ye page hum aage banayenge jaha clustered photos dikhengi
    return f"<h3>Showing Gallery for Event: {entered_code}</h3><br><a href='/hub'>Back to Hub</a>"

# 5. Upload Logic
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

# 6. Logout Route
@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)