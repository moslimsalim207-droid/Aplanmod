import os
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class Config:
    """Configuration base class"""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dawahi-secret-key-change-me-in-production')
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8MB max upload
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_REFRESH_EACH_REQUEST = True
    
    # Database
    DB_PATH = os.path.join(BASE_DIR, 'dawahi.db')
    
    # Upload directories
    UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')
    TICKETS_DIR = os.path.join(BASE_DIR, 'tickets')
    
    # Allowed file extensions
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
    
    # Debug mode
    DEBUG = False

class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise ValueError('SECRET_KEY environment variable must be set in production')

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
