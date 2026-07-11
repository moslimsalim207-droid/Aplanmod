from flask import session
from constants import TRANSLATIONS

def t(key, lang=None):
    """Translate key to language"""
    if lang is None:
        lang = session.get('lang', 'ar')
    
    trans = TRANSLATIONS.get(key, {})
    return trans.get(lang, trans.get('ar', key))

def get_language():
    """Get current language"""
    return session.get('lang', 'ar')

def set_language(lang):
    """Set current language"""
    if lang in ('ar', 'en'):
        session['lang'] = lang
        return True
    return False

def get_theme():
    """Get current theme"""
    return session.get('theme', 'light')

def set_theme(theme):
    """Set current theme"""
    if theme in ('light', 'dark'):
        session['theme'] = theme
        return True
    return False
