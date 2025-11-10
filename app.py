#!/usr/bin/env python3
"""
Flask web interface for the SQL Query Tool.
"""

import os
import json
from flask import Flask, render_template, request, jsonify, session
from main import DatabaseConnection, NaturalLanguageQuery, get_groq_api_key

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Required for session

db_connection = None
nl_processor = None

# Initialize the natural language processor
try:
    nl_processor = NaturalLanguageQuery()
except Exception as e:
    print(f"Warning: Could not initialize natural language processor: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/check-connection')
def check_connection():
    if db_connection and db_connection.connection and db_connection.connection.is_connected():
        return jsonify({"connected": True, "database": db_connection.database})
    return jsonify({"connected": False})

@app.route('/connect', methods=['POST'])
def connect():
    global db_connection
    
    try:
        data = request.get_json()
        
        # Create a new database connection
        db_connection = DatabaseConnection(
            host=data.get('host', 'localhost'),
            user=data['user'],
            password=data['password'],
            database=data['database'],
            ssl_disabled=data.get('ssl_disabled', True)
        )
        
        # Test the connection
        if db_connection.connect():
            return jsonify({"status": "success"})
        else:
            return jsonify({"error": "Failed to connect to the database"}), 400
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/query', methods=['POST'])
def execute_query():
    global db_connection, nl_processor
    
    if not db_connection or not db_connection.connection or not db_connection.connection.is_connected():
        return jsonify({"error": "Not connected to database"}), 400
    
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        query_type = request.args.get('type', 'sql')
        
        if not query:
            return jsonify({"error": "Empty query"}), 400
        
        # Handle natural language query
        if query_type == 'nl' and nl_processor:
            try:
                # Get schema info for context
                schema_info = db_connection.get_schema_info()
                # Convert natural language to SQL
                success, sql_query, error = nl_processor.natural_language_to_sql(query, schema_info)
                if not success or not sql_query:
                    error_msg = error or "Could not generate SQL from your question"
                    return jsonify({"error": error_msg}), 400
                
                # Execute the generated SQL
                success, result, error = db_connection.execute_query(sql_query)
                
                if success:
                    # If it's a SELECT query, return the results
                    if isinstance(result, tuple):
                        columns, rows = result
                        results = []
                        for row in rows:
                            results.append(dict(zip(columns, row)))
                        return jsonify({"sql": sql_query, "results": results})
                    # For other query types, return the number of affected rows
                    else:
                        return jsonify({"sql": sql_query, "affected_rows": result})
                else:
                    return jsonify({"error": error}), 400
                    
            except Exception as e:
                return jsonify({"error": f"Error processing natural language query: {str(e)}"}), 500
        
        # Handle direct SQL query
        elif query_type == 'sql':
            success, result, error = db_connection.execute_query(query)
            
            if success:
                # If it's a SELECT query, return the results
                if isinstance(result, tuple):
                    columns, rows = result
                    results = []
                    for row in rows:
                        results.append(dict(zip(columns, row)))
                    return jsonify({"results": results})
                # For other query types, return the number of affected rows
                else:
                    return jsonify({"affected_rows": result})
            else:
                return jsonify({"error": error}), 400
        
        else:
            return jsonify({"error": "Invalid query type or natural language processing not available"}), 400
            
    except Exception as e:
        return jsonify({"error": f"Error executing query: {str(e)}"}), 500

if __name__ == '__main__':
    # Create necessary directories
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    
    # Run the Flask app
    app.run(debug=True, port=5000)
