import os
from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_pymongo import PyMongo
from datetime import datetime
from werkzeug.utils import secure_filename
from bson.objectid import ObjectId
from ml_model import predict

def create_app(test_config=None):
    load_dotenv()
    # create and configure the app
    app = Flask(__name__, template_folder='templates', instance_relative_config=True)
    
    mongo_uri = os.getenv('MONGO_URI')
    print('Loaded Mongo URI:', mongo_uri)
    if not mongo_uri:
        raise Exception("MONGO_URI not found in environment")
    
    app.config['MONGO_URI'] = mongo_uri
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    
    mongo = PyMongo()
    mongo.init_app(app)

    try:
        mongo.db.command('ping')
        print("MongoDB connection successful!")

    except Exception as e:
        print(f"mongodb connection error: {e}")
        raise Exception("MongoDB not connected")
    
    app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'uploads')
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # collections
    users_collection = mongo.db.users
    feedback_collection = mongo.db.feedback
    patients_collection = mongo.db.patient_details
    scans_collection = mongo.db.scans
    results_collection = mongo.db.results

    #store collections
    app.config['USERS_COLLECTION'] = users_collection
    app.config['FEEDBACK_COLLECTION'] = feedback_collection
    app.config['PATIENTS_COLLECTION'] = patients_collection
    app.config['SCANS_COLLECTION'] = scans_collection
    app.config['RESULTS_COLLECTION'] = results_collection

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
        return render_template("login.html")
    
    @app.route('/register', methods=['GET', 'POST'])
    def register():
        print("DEBUG USERS_COLLECTION:", app.config.get("USERS_COLLECTION"))

        if request.method == 'POST':
            email = request.form.get('email')
            password = request.form.get('password')
            
            users_collection = app.config.get("USERS_COLLECTION")
            if users_collection is None:
                flash("Database connection is unavailable")
                return render_template('register.html')
            
            new_user = {
                'email': email,
                'password': password
            }

            try:
                users_collection.insert_one(new_user)
                flash('Successful registration')
                return redirect(url_for('upload'))
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

            if user and user['password'] == password:
                session['is_logged_in'] = True
                session['email'] = email
                return redirect(url_for('upload'))
            else:
                flash('Invalid email/password')
        
        return render_template("login.html", error=error)
    
    @app.route('/feedback', methods=['GET', 'POST'])
    def feedback():
        if not session.get('is_logged_in'):
          return redirect(url_for('login'))
        
        if request.method == 'POST':
            comment = request.form.get('comment')
            user_email = session.get('email')
            
            if comment:
                feedback_doc ={
                    'email': user_email,
                    'comment': comment,
                    'timestamp': datetime.now()
                }
                feedback_collection.insert_one(feedback_doc)
                flash('Thank you for your feedback!')
                return redirect(url_for('feedback'))
            
        return render_template('feedback.html')
    
    def predict(filepath):
        classification_result = 'some_classifiaction'
        prognosis_result = 'some_prognosis'
        classification_conf = 0.95
        prognosis_config = 0.90
        return classification_result, prognosis_result, classification_conf, prognosis_config

    @app.route('/upload', methods=['GET', 'POST'])
    def upload():
        if not session.get('is_logged_in'):
          return redirect(url_for('login'))
        
        if request.method == 'POST':
            patient_data = {
                'name': request.form.get('patient-name'),
                'dob': request.form.get('dob'),
                'hospital_number': request.form.get('hospital-number'),
                'NHS': request.form.get('NHS'),
                'uploaded_by': session.get('email'),
                'created_at': datetime.now()
            }

            patients_collection = app.config['PATIENTS_COLLECTION']
            patient_insert = patients_collection.insert_one(patient_data)
            patient_id = patient_insert.inserted_id

            file = request.files['file']
            if file:
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)

                classification_result, prognosis_result, classification_conf, prognosis_config= predict(filepath) #replace with my model
                prediction = {
                    'classification': classification_result,
                    'prognosis': prognosis_result,
                    'accuracy': {
                        'classification': classification_conf,
                        'prognosis': prognosis_config
                    },
                    'model_version':'v1.0'
                }
                scan_data = {
                    'patient_id': patient_id,
                    'filename': filename,
                    'filepath': filepath,
                    'uploaded_at': datetime.now(),
                    'prediction': prediction
                }

                scans_collection = app.config['SCANS_COLLECTION']
                scans_collection.insert_one(scan_data)


            session['patient_id'] = str(patient_id)
            
            flash('file successfully uploaded')
            return redirect(url_for('dashboard'))
        return render_template("upload.html")
    
    @app.route('/dashboard')
    def dashboard():
        if not session.get('is_logged_in'):
          return redirect(url_for('login'))
        
        patient_id = session.get('patient_id')
        if not patient_id:
            flash("No patient data found!")
            return redirect(url_for('upload'))
        
        patient = app.config['PATIENTS_COLLECTION'].find_one({'_id': ObjectId(patient_id)})
        scans = list(app.config['SCANS_COLLECTION'].find({'patient_id': ObjectId(patient_id)}))

        return render_template('dashboard.html', patient=patient, scans=scans)
        
    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('index'))

    return app
