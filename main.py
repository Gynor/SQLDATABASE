import os
import sqlite3
import json
import uuid
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, send_from_directory, abort

app = Flask(__name__)

# Configurations
UPLOAD_FOLDER = 'uploads'
DATABASE_FILE = 'database.db'

# Create upload directory if it does not exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_db_connection() -> sqlite3.Connection:
    """
    Creates and returns a database connection.
    Uses Row factory to enable dictionary-like access to columns.
    """
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    """
    Initializes the database schema on startup.
    Ensures that physical filenames are UNIQUE.
    """
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_filename TEXT NOT NULL,
                physical_filename TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                metadata TEXT,
                upload_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

# Initialize the database
init_db()

@app.route('/', methods=['GET'])
def index():
    """
    Home page route. 
    Lists uploaded files, handles search queries, and category filtering.
    """
    search_query = request.args.get('search', '').strip()
    cat_filter = request.args.get('filter_category', '').strip()

    query = "SELECT * FROM files WHERE 1=1"
    params = []

    if cat_filter:
        query += " AND category = ?"
        params.append(cat_filter)
    
    if search_query:
        # Search within both the original filename and the JSON metadata
        query += " AND (original_filename LIKE ? OR metadata LIKE ?)"
        params.extend([f"%{search_query}%", f"%{search_query}%"])

    query += " ORDER BY id DESC"

    with get_db_connection() as conn:
        files = conn.execute(query, params).fetchall()
    
    return render_template(
        'index.html', 
        files=files, 
        search_query=search_query, 
        cat_filter=cat_filter
    )

@app.route('/upload', methods=['POST'])
def upload_file():
    """
    Processes incoming file uploads and dynamic metadata.
    Saves the file to disk using a unique UUID to prevent overwriting.
    """
    if 'file' not in request.files:
        abort(400, description="No file part in the request.")
        
    file = request.files['file']
    category = request.form.get('category')
    
    if file.filename == '':
        abort(400, description="No selected file.")
        
    if file and category:
        # Sanitize the incoming filename for security
        safe_filename = secure_filename(file.filename)
        
        # Generate a unique physical filename using UUID4
        file_extension = os.path.splitext(safe_filename)[1]
        physical_filename = f"{uuid.uuid4().hex}{file_extension}"
        filepath = os.path.join(UPLOAD_FOLDER, physical_filename)
        
        # Collect dynamic form fields as metadata (excluding the category field)
        metadata = {key: value for key, value in request.form.items() if key != 'category'}
        
        try:
            # Save the file to the local disk
            file.save(filepath)
            
            # Insert the record into the database
            with get_db_connection() as conn:
                conn.execute('''
                    INSERT INTO files (original_filename, physical_filename, category, metadata) 
                    VALUES (?, ?, ?, ?)
                ''', (safe_filename, physical_filename, category, json.dumps(metadata)))
                conn.commit()
        except Exception as e:
            # Clean up the physical file if database insertion fails
            if os.path.exists(filepath):
                os.remove(filepath)
            abort(500, description=f"System error: {str(e)}")
            
    return redirect('/')

@app.route('/download/<physical_filename>')
def download_file(physical_filename):
    """
    Safely serves the requested file from the uploads directory.
    Uses the original filename for the download prompt.
    """
    # Retrieve the original filename to serve it correctly to the client
    with get_db_connection() as conn:
        file_record = conn.execute(
            "SELECT original_filename FROM files WHERE physical_filename = ?", 
            (physical_filename,)
        ).fetchone()
        
    if file_record is None:
        abort(404, description="File not found in the database.")
        
    return send_from_directory(
        UPLOAD_FOLDER, 
        physical_filename, 
        as_attachment=True,
        download_name=file_record['original_filename'] # User sees original name, not UUID
    )

@app.route('/delete/<int:file_id>', methods=['POST'])
def delete_file(file_id):
    """
    Deletes the file from the physical storage and removes its record from the database.
    """
    with get_db_connection() as conn:
        # Fetch the physical filename associated with the given file ID
        file_record = conn.execute(
            "SELECT physical_filename FROM files WHERE id = ?", 
            (file_id,)
        ).fetchone()
        
        if file_record:
            physical_filename = file_record['physical_filename']
            filepath = os.path.join(UPLOAD_FOLDER, physical_filename)
            
            # Remove the physical file from the disk if it exists
            if os.path.exists(filepath):
                os.remove(filepath)
                
            # Remove the corresponding record from the database
            conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
            conn.commit()
            
    return redirect('/')

if __name__ == '__main__':
    # Run the Flask development server
    app.run(host='192.168.1.226', port=80)