import os
from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_pymongo import PyMongo

def create_app(test_config=None):
    load_dotenv()
    # create and configure the app
    app = Flask(__name__, template_folder='templates', instance_relative_config=True)
    
    mongo_uri = os.getenv('MONGO_URI')
    app.config['MONGO_URI'] = mongo_uri

    secret_key = os.getenv('SECRET_KEY')
    app.config['SECRET_KEY'] = secret_key
    try:
        mongo = PyMongo(app)
        mongo.db.command('ping')
        print("MongoDB connection successful!")

        # collections
        users_collection = mongo.db.users
        # scans_collection = mongo.db.scans
        # report_collection = mongo.db.report

        #store collections
        app.config['USERS_COLLECTION'] = users_collection
        # app.config['SCANS_COLLECTION'] = scans_collection
        # app.config['REPORTS_COLLECTION'] = reports_collection
    except Exception as e:
        print(f"MongoDB Connection Error: {e}")
    if test_config is None:
        # load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)

    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    @app.route('/')
    def index():
        #check if user is logged in
        is_logged_in = session.get('is_logged_in', False)
        return render_template("index.html", is_logged_in = is_logged_in)
    
    @app.route('/feedback')
    def feedback():
        return render_template('feedback.html')
    
    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'POST':
            email = request.form.get('email')
            password = request.form.get('password')

            new_user = {
                'email': email,
                'password': password
            }

            try:
                app.config["USERS_COLLECTION"].insert_one(new_user)
                flash('Successful registration')
                return render_template('upload.html')
            except Exception as e:
                flash(f"Registration failed: {str(e)}", 'error')
                return render_template('register.html')

        return render_template("register.html")
    
    @app.route('/login', methods = ['GET', 'POST'])
    def login():
        error = None
        if request.method == 'POST':
            email = request.form.get('email')
            password = request.form.get('password')           

            user = app.config['USERS_COLLECTION'].find_one({'email': email})

            if user and user[password] == password:
                session['is_logged_in'] = True
                session['email'] = email
                return redirect(url_for('upload'))
            else:
                flash('Invalid email/password')
        
        return render_template("login.html", error=error)

    @app.route('/upload')
    def form():
        return render_template("upload.html")
    
    @app.route('/dashboard')
    def dashboard():
        if not session.get('is_logged_in'):
            return redirect(url_for('login'))
        return render_template("dashboard.html")
    
    '''
    @app.route('/predict', methods = ['POST'])
    def predict():
        try:

            return jsonify({"prediction":predicted_class})
        except Exception as e:
            return jsonify({"error":str(e)})
    '''
        
    @app.route('/logout')
    def logout():
        session.pop('email', None)
        session['is_logged_in', None]
        return redirect(url_for('index'))

    return app
