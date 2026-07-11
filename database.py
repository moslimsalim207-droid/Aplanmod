import sqlite3
import os
from config import Config

DB_PATH = Config.DB_PATH

def get_db():
    """Get database connection from Flask g object"""
    from flask import g
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db

def close_db(e=None):
    """Close database connection"""
    from flask import g
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    """Initialize database schema"""
    if os.path.exists(DB_PATH):
        return
    
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT NOT NULL,
            country TEXT NOT NULL,
            passport_file TEXT,
            passport_issue_date TEXT,
            passport_expiry_date TEXT,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        
        CREATE TABLE IF NOT EXISTS airlines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            country TEXT NOT NULL,
            logo_emoji TEXT DEFAULT '✈️'
        );
        
        CREATE TABLE IF NOT EXISTS flights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            airline_id INTEGER NOT NULL,
            from_city TEXT NOT NULL,
            to_city TEXT NOT NULL,
            to_country TEXT NOT NULL,
            dep_time TEXT NOT NULL,
            arr_time TEXT NOT NULL,
            duration TEXT NOT NULL,
            price_economy INTEGER NOT NULL,
            price_second INTEGER NOT NULL,
            price_business INTEGER NOT NULL,
            price_first INTEGER NOT NULL,
            FOREIGN KEY(airline_id) REFERENCES airlines(id)
        );
        
        CREATE TABLE IF NOT EXISTS hotels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT NOT NULL,
            country TEXT NOT NULL,
            name TEXT NOT NULL,
            stars INTEGER NOT NULL
        );
        
        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hotel_id INTEGER NOT NULL,
            room_type TEXT NOT NULL,
            capacity INTEGER NOT NULL,
            price_per_night INTEGER NOT NULL,
            FOREIGN KEY(hotel_id) REFERENCES hotels(id)
        );
        
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_code TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            flight_id INTEGER NOT NULL,
            ticket_class TEXT NOT NULL,
            flight_price INTEGER NOT NULL,
            room_id INTEGER,
            checkin TEXT,
            checkout TEXT,
            hotel_price INTEGER DEFAULT 0,
            total_price INTEGER NOT NULL,
            pdf_file TEXT,
            status TEXT NOT NULL DEFAULT 'confirmed',
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(flight_id) REFERENCES flights(id),
            FOREIGN KEY(room_id) REFERENCES rooms(id)
        );
    """)
    db.commit()
    seed_data(db)
    db.close()

def seed_data(db):
    """Seed database with initial data"""
    from data import seed_airlines, seed_flights, seed_hotels
    
    if db.execute('SELECT COUNT(*) c FROM airlines').fetchone()['c'] > 0:
        return
    
    seed_airlines(db)
    seed_flights(db)
    seed_hotels(db)
    db.commit()
