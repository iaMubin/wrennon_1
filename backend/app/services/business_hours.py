import datetime
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from app.db.session import SessionLocal
from app.db.models import SystemSetting
from app.logger import logger

from sqlalchemy.orm import Session
def is_within_business_hours(db: Session = None) -> bool:
    """Check if the current time is within configured business hours."""
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        setting = db.query(SystemSetting).filter_by(key="business_hours").first()
        if not setting or not setting.value:
            return True
            
        hours = json.loads(setting.value)
        tz_str = hours.get("timezone", "UTC")
        try:
            tz = ZoneInfo(tz_str)
        except ZoneInfoNotFoundError:
            tz = datetime.timezone.utc
            
        now = datetime.datetime.now(tz)
        day_str = now.strftime("%a").lower()[:3] # mon, tue, wed, thu, fri, sat, sun
        
        day_hours = hours.get(day_str)
        if not day_hours:
            return False
            
        start_str, end_str = day_hours
        start_time = datetime.datetime.strptime(start_str, "%H:%M").time()
        end_time = datetime.datetime.strptime(end_str, "%H:%M").time()
        
        return start_time <= now.time() <= end_time
        
    except Exception as e:
        logger.error(f"Error checking business hours: {e}")
        return True # Default to open on error
    finally:
        if close_db:
            db.close()
