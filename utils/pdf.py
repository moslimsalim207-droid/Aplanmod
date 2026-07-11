# -*- coding: utf-8 -*-
"""
PDF Generation utilities
"""

import os
from database import get_db
from config import Config
from constants import CLASS_LABELS

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code128

def generate_ticket_pdf(booking_id):
    """Generate PDF ticket for booking"""
    db = get_db()
    
    b = db.execute('SELECT * FROM bookings WHERE id=?', (booking_id,)).fetchone()
    user = db.execute('SELECT * FROM users WHERE id=?', (b['user_id'],)).fetchone()
    flight = db.execute('SELECT * FROM flights WHERE id=?', (b['flight_id'],)).fetchone()
    airline = db.execute('SELECT * FROM airlines WHERE id=?', (flight['airline_id'],)).fetchone()
    room = db.execute('SELECT * FROM rooms WHERE id=?', (b['room_id'],)).fetchone() if b['room_id'] else None
    hotel = db.execute('SELECT * FROM hotels WHERE id=?', (room['hotel_id'],)).fetchone() if room else None
    
    fname = f"ticket_{b['ref_code']}.pdf"
    fpath = os.path.join(Config.TICKETS_DIR, fname)
    
    c = canvas.Canvas(fpath, pagesize=A4)
    w, h = A4
    gold = colors.HexColor('#b8912b')
    navy = colors.HexColor('#0f1b30')
    muted = colors.HexColor('#555555')
    
    # Header
    c.setFillColor(navy)
    c.rect(0, h-90, w, 90, fill=1, stroke=0)
    c.setFillColor(gold)
    c.setFont('Helvetica-Bold', 20)
    c.drawCentredString(w/2, h-45, 'DAWAHI TRAVEL & TOURISM AGENCY')
    c.setFont('Helvetica', 11)
    c.setFillColor(colors.white)
    c.drawCentredString(w/2, h-65, 'E-Ticket / Booking Confirmation')
    
    # Reference
    y = h - 130
    c.setFillColor(colors.black)
    c.setFont('Helvetica-Bold', 13)
    c.drawString(40, y, f"Reference: {b['ref_code']}")
    c.setFont('Helvetica', 10)
    c.drawRightString(w-40, y, f"Issued: {b['created_at'][:19]}")
    
    # Passenger Info
    y -= 30
    c.setFont('Helvetica-Bold', 12)
    c.drawString(40, y, 'Passenger Information')
    c.setStrokeColor(gold)
    c.line(40, y-4, w-40, y-4)
    y -= 20
    c.setFont('Helvetica', 10)
    c.drawString(50, y, f"Name: {user['username']}")
    y -= 15
    c.drawString(50, y, f"Email: {user['email']}   Phone: {user['phone']}")
    y -= 15
    c.drawString(50, y, f"Country: {user['country']}")
    
    # Flight Details
    y -= 30
    c.setFont('Helvetica-Bold', 12)
    c.drawString(40, y, 'Flight Details')
    c.line(40, y-4, w-40, y-4)
    y -= 20
    c.setFont('Helvetica', 10)
    c.drawString(50, y, f"Airline: {airline['name']}")
    y -= 15
    c.drawString(50, y, f"Route: {flight['from_city']} -> {flight['to_city']} ({flight['to_country']})")
    y -= 15
    c.drawString(50, y, f"Departure: {flight['dep_time']}   Arrival: {flight['arr_time']}   Duration: {flight['duration']}")
    y -= 15
    c.drawString(50, y, f"Class: {CLASS_LABELS.get(b['ticket_class'], b['ticket_class'])}")
    y -= 15
    c.setFillColor(colors.HexColor('#0a7a3d'))
    c.drawString(50, y, f"Flight Price: {b['flight_price']} SDG")
    c.setFillColor(colors.black)
    
    # Hotel Booking
    if hotel and room:
        y -= 30
        c.setFont('Helvetica-Bold', 12)
        c.drawString(40, y, 'Hotel Booking')
        c.line(40, y-4, w-40, y-4)
        y -= 20
        c.setFont('Helvetica', 10)
        c.drawString(50, y, f"Hotel: {hotel['name']} ({'*' * hotel['stars']})")
        y -= 15
        c.drawString(50, y, f"City: {hotel['city']} - {hotel['country']}")
        y -= 15
        c.drawString(50, y, f"Room: {room['room_type']} (Capacity {room['capacity']})")
        y -= 15
        c.drawString(50, y, f"Check-in: {b['checkin']}   Check-out: {b['checkout']}")
        y -= 15
        c.setFillColor(colors.HexColor('#0a7a3d'))
        c.drawString(50, y, f"Hotel Price: {b['hotel_price']} SDG")
        c.setFillColor(colors.black)
    
    # Total
    y -= 35
    c.setFont('Helvetica-Bold', 14)
    c.setFillColor(navy)
    c.drawString(40, y, f"TOTAL: {b['total_price']} SDG")
    c.setFillColor(colors.black)
    
    # Barcode
    y -= 50
    barcode_val = code128.Code128(b['ref_code'], barHeight=18*mm, barWidth=0.5)
    barcode_val.drawOn(c, 40, y - barcode_val.height)
    c.setFont('Helvetica', 9)
    c.setFillColor(muted)
    c.drawString(40, y - barcode_val.height - 12, f"Scan at check-in counter - {b['ref_code']}")
    
    # Footer
    c.setFont('Helvetica-Oblique', 8)
    c.drawCentredString(w/2, 30, 'Dawahi Travel & Tourism Agency — Thank you for booking with us')
    
    c.showPage()
    c.save()
    
    return fname
