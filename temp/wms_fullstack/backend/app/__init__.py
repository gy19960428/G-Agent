import os
from pathlib import Path

from flask import Flask, jsonify, request
from dotenv import load_dotenv

from . import db


def create_app(test_config=None):
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.getenv('WMS_SECRET_KEY', 'dev-wms-fullstack'),
        DATABASE_URL=os.getenv('WMS_DATABASE_URL', 'sqlite:///wms_dev.db'),
        CORS_ORIGINS=os.getenv('WMS_CORS_ORIGINS', 'http://127.0.0.1:5173,http://localhost:5173'),
    )
    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.teardown_appcontext(db.close_db)

    @app.after_request
    def add_cors_headers(response):
        allowed_origins = [origin.strip() for origin in app.config['CORS_ORIGINS'].split(',') if origin.strip()]
        origin = request.headers.get('Origin')
        allow_all = '*' in allowed_origins
        lan_origin = origin and origin.startswith('http://') and (
            origin.startswith('http://localhost')
            or origin.startswith('http://127.0.0.1')
            or origin.startswith('http://192.168.')
            or origin.startswith('http://10.')
            or origin.startswith('http://172.')
        )
        if origin and (allow_all or origin in allowed_origins or lan_origin):
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Vary'] = 'Origin'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-WMS-User'
            response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
        return response

    @app.route('/api/<path:_path>', methods=['OPTIONS'])
    def api_options(_path):
        return ('', 204)

    @app.get('/api/health')
    def health():
        return jsonify({'ok': True, 'service': 'wms-backend'})

    @app.cli.command('init-db')
    def init_db_command():
        db.init_db()
        print('Initialized database')

    from .api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    return app
