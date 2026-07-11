import random
from constants import COUNTRY_DATA, LOCAL_CITIES, HOTEL_NAMES, ROOM_TYPES

def seed_airlines(db):
    """Seed airlines data"""
    airline_ids = {}
    for country, info in COUNTRY_DATA.items():
        for name in info['airlines']:
            cur = db.execute(
                'INSERT INTO airlines(name, country) VALUES(?, ?)',
                (name, country)
            )
            airline_ids[name] = (cur.lastrowid, country)
    return airline_ids

def seed_flights(db):
    """Seed flights data"""
    random.seed(42)
    hours = ['06:15', '09:30', '12:45', '16:20', '20:10', '23:40']
    
    airline_ids = {}
    for country, info in COUNTRY_DATA.items():
        for name in info['airlines']:
            cur = db.execute(
                'SELECT id FROM airlines WHERE name=? AND country=?',
                (name, country)
            )
            row = cur.fetchone()
            if row:
                airline_ids[name] = (row['id'], country)
    
    all_countries = list(COUNTRY_DATA.keys())
    
    for name, (aid, home_country) in airline_ids.items():
        from_city = COUNTRY_DATA[home_country]['city']
        destinations = [c for c in all_countries if c not in (home_country, 'دولي')]
        random.shuffle(destinations)
        
        for to_country in destinations[:6]:
            to_city = COUNTRY_DATA[to_country]['city']
            dep = random.choice(hours)
            dur_h = random.randint(1, 6)
            base = random.randint(180, 650) * 10
            
            db.execute(
                """INSERT INTO flights(
                    airline_id, from_city, to_city, to_country, dep_time, arr_time,
                    duration, price_economy, price_second, price_business, price_first
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (aid, from_city, to_city, to_country, dep,
                 f"{(int(dep[:2])+dur_h)%24:02d}:{dep[3:]}", f"{dur_h} ساعة",
                 base, int(base*1.3), int(base*2.1), int(base*3.2))
            )
        
        # Local flights
        cities = LOCAL_CITIES.get(home_country, [])
        for to_city in cities:
            dep = random.choice(hours)
            dur_h = random.randint(1, 2)
            base = random.randint(40, 120) * 10
            
            db.execute(
                """INSERT INTO flights(
                    airline_id, from_city, to_city, to_country, dep_time, arr_time,
                    duration, price_economy, price_second, price_business, price_first
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (aid, from_city, to_city, home_country, dep,
                 f"{(int(dep[:2])+dur_h)%24:02d}:{dep[3:]}", f"{dur_h} ساعة",
                 base, int(base*1.3), int(base*2.1), int(base*3.2))
            )

def seed_hotels(db):
    """Seed hotels and rooms data"""
    for country, info in COUNTRY_DATA.items():
        city = info['city']
        country_label = 'تركيا' if country == 'دولي' else country
        
        for stars, names in HOTEL_NAMES.items():
            hname = random.choice(names)
            cur = db.execute(
                'INSERT INTO hotels(city, country, name, stars) VALUES(?, ?, ?, ?)',
                (city, country_label, hname, stars)
            )
            hid = cur.lastrowid
            
            for rtype, cap in ROOM_TYPES:
                price = (stars * 350) + random.randint(-60, 120) + (cap * 40)
                db.execute(
                    'INSERT INTO rooms(hotel_id, room_type, capacity, price_per_night) VALUES(?, ?, ?, ?)',
                    (hid, rtype, cap, price)
                )
