import os
import pickle
import tempfile
from PIL import Image
import numpy as np
import tensorflow as tf
from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_pymongo import PyMongo
from datetime import datetime
from werkzeug.utils import secure_filename
from bson.objectid import ObjectId
import boto3
from botocore.exceptions import NoCredentialsError

def create_app(test_config=None):
    load_dotenv()
    # create and configure the app
    app = Flask(__name__, template_folder='templates', instance_relative_config=True)
    
    s3 = boto3.client('s3', 
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS'),
        region_name='eu-north-1')
    
    def load_pickel_from_s3(bucket_name, key):
        with tempfile.NamedTemporaryFile() as tmp_file:
            s3.download_fileobj(bucket_name, key, tmp_file)
            tmp_file.seek(0)
            model = pickle.load(tmp_file)
        return model
    def load_keras_from_s3(bucket_name, key):
        with tempfile.NamedTemporaryFile(suffix=".h5") as tmp_file:
            s3.download_fileobj(bucket_name, key, tmp_file)
            tmp_file.seek(0)
            model = tf.keras.models.load_model(tmp_file.name) 
        return model

    def preprocess_image(filepath, target_size=(224, 224), for_keras=True):
        image = Image.open(filepath).convert('RGB')
        image = image.resize(target_size)
        image_array = np.array(image)

        if for_keras:
            image_array = image_array / 255.0  # Normalize
            image_array = np.expand_dims(image_array, axis=0)  # Add batch dimension
        else:
            image_array = image_array.flatten()  # Flatten for SVM
            image_array = image_array / 255.0  # Normalize

        return image_array

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
        
        if 'email' not in session:
                flash('Please login to leave feedback!')
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

    @app.route('/upload', methods=['GET', 'POST'])
    def upload():
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

                scan_data = {
                    'patient_id': patient_id,
                    'filename': filename,
                    'filepath': filepath,
                    'uploaded_at': datetime.now()
                }

                scans_collection = app.config['SCANS_COLLECTION']
                scans_collection.insert_one(scan_data)

            session['patient_id'] = str(patient_id)

            # load model from S3
            vgg_model = load_keras_from_s3('dissertation','vgg_model.h5')
            svm_model = load_pickel_from_s3('dissertation','svm_model.pkl')

            # load and process image
            image = Image.open(filepath).convert('RGB')

            # preprocessing for VGG16
            vgg_img = image.resize((224, 244))
            vgg_array = np.array(vgg_img)/255.0
            vgg_array = np.expand_dims(vgg_array, axis=0)

            # Classification
            vgg_pred = vgg_model.predict(vgg_array)
            classification_label = np.argmax(vgg_pred)

            # SVM
            svm_img = image.resize((128, 128))
            svm_array = np.array(svm_img).flatten().reshape(1, -1)
            prognosis = svm_model.predict(svm_array)[0]

            #results
            results_collection = app.config['RESULTS_COLLECTION']
            results_collection.insert_one({
                'patient_id': patient_id,
                'classification': int(classification_label),
                'prognosis': str(prognosis),
                'timestamp': datetime.now()
            })
            flash('file successfully uploaded')
            
            return redirect(url_for('dashboard'))
        
    
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
        result = app.config['RESULTS_COLLECTION'].find_one({'patient_id': ObjectId(patient_id)})

        return render_template('dashboard.html', patient=patient, scans=scans, result=result)
        
    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('index'))

    return app
