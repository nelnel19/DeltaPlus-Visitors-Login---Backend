import os
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional

# Use environment variable for database URL, fallback to local SQLite
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./users.db")

# Fix for Render's PostgreSQL URL (starts with postgres://)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Configure engine based on database type
if DATABASE_URL.startswith("postgresql"):
    engine = create_engine(DATABASE_URL)
else:
    engine = create_engine(
        DATABASE_URL, connect_args={"check_same_thread": False}
    )

SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

app = FastAPI()

# Update CORS for production - get allowed origins from environment variable
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "https://deltaplus-visitors-login-frontend.onrender.com").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helper function to get Philippine Time (UTC+8)
def get_philippine_time():
    utc_time = datetime.now(timezone.utc)
    ph_time = utc_time + timedelta(hours=8)  # Philippines is UTC+8
    return ph_time.replace(tzinfo=None)  # Remove timezone info for database storage

# Database Model for User - REMOVED house_number, street_name, barangay
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String)
    company_name = Column(String)
    phone = Column(String)
    # Removed: house_number, street_name, barangay
    city = Column(String)
    region = Column(String)
    email = Column(String, unique=True)
    created_at = Column(DateTime, default=get_philippine_time)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=True)
    
    event = relationship("Event", foreign_keys=[event_id], back_populates="users")
    created_events = relationship("Event", foreign_keys="Event.user_id", back_populates="creator")

# Database Model for Event (unchanged)
class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    event_name = Column(String, nullable=False)
    event_schedule = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=get_philippine_time)
    
    users = relationship("User", foreign_keys="User.event_id", back_populates="event")
    creator = relationship("User", foreign_keys=[user_id], back_populates="created_events")

# Create tables
Base.metadata.create_all(bind=engine)

# Request Schemas - REMOVED house_number, street_name, barangay
class UserCreate(BaseModel):
    full_name: str
    company_name: str
    phone: str
    # Removed: house_number, street_name, barangay
    city: str
    region: str
    email: str

class EventCreate(BaseModel):
    event_name: str
    event_schedule: str
    user_id: Optional[int] = None

class EventResponse(BaseModel):
    id: int
    event_name: str
    event_schedule: str
    is_active: bool
    user_id: Optional[int]
    created_at: str
    
    class Config:
        from_attributes = True

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Health check endpoint for Render
@app.get("/health")
def health_check():
    return {"status": "healthy", "database": "connected"}

@app.get("/")
def root():
    return {"message": "API is running", "environment": os.getenv("RENDER", "development")}

@app.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == user.email).first()

    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    active_event = db.query(Event).filter(Event.is_active == True).first()
    
    new_user = User(
        full_name=user.full_name,
        company_name=user.company_name,
        phone=user.phone,
        # Removed: house_number, street_name, barangay
        city=user.city,
        region=user.region,
        email=user.email,
        created_at=get_philippine_time(),  # Use Philippine Time
        event_id=active_event.id if active_event else None
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "message": "Registration successful",
        "user_id": new_user.id,
        "assigned_event": active_event.event_name if active_event else None,
        "registered_at": new_user.created_at.strftime("%Y-%m-%d %H:%M:%S")  # Return the time
    }

@app.get("/users")
def get_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [
        {
            "id": user.id,
            "full_name": user.full_name,
            "company_name": user.company_name,
            "phone": user.phone,
            # Removed: house_number, street_name, barangay
            "city": user.city,
            "region": user.region,
            "email": user.email,
            "created_at": user.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "event_name": user.event.event_name if user.event else None,
            "event_schedule": user.event.event_schedule.strftime("%Y-%m-%d %H:%M:%S") if user.event else None
        }
        for user in users
    ]

# Event Endpoints (unchanged - keeping all event-related endpoints)
@app.post("/events")
def create_event(event: EventCreate, db: Session = Depends(get_db)):
    try:
        # Parse the datetime string (format: "YYYY-MM-DD HH:MM:SS")
        event_schedule = datetime.strptime(event.event_schedule, "%Y-%m-%d %H:%M:%S")
        
        event_count = db.query(Event).count()
        
        new_event = Event(
            event_name=event.event_name,
            event_schedule=event_schedule,
            user_id=event.user_id,
            is_active=(event_count == 0),
            created_at=get_philippine_time()  # Use Philippine Time
        )
        
        db.add(new_event)
        db.commit()
        db.refresh(new_event)
        
        return {
            "message": "Event created successfully",
            "event_id": new_event.id
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error creating event: {str(e)}")

@app.get("/events", response_model=List[EventResponse])
def get_events(db: Session = Depends(get_db)):
    events = db.query(Event).order_by(Event.event_schedule).all()
    return [
        {
            "id": event.id,
            "event_name": event.event_name,
            "event_schedule": event.event_schedule.strftime("%Y-%m-%d %H:%M:%S"),
            "is_active": event.is_active,
            "user_id": event.user_id,
            "created_at": event.created_at.strftime("%Y-%m-%d %H:%M:%S")
        }
        for event in events
    ]

@app.post("/events/{event_id}/set-active")
def set_active_event(event_id: int, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    
    # Deactivate all events
    db.query(Event).update({Event.is_active: False})
    # Activate the selected event
    event.is_active = True
    db.commit()
    
    return {
        "message": f"Event '{event.event_name}' is now the active event",
        "event_id": event.id
    }

@app.get("/events/active")
def get_active_event(db: Session = Depends(get_db)):
    active_event = db.query(Event).filter(Event.is_active == True).first()
    if not active_event:
        return {"message": "No active event set", "event_name": None}
    
    return {
        "id": active_event.id,
        "event_name": active_event.event_name,
        "event_schedule": active_event.event_schedule.strftime("%Y-%m-%d %H:%M:%S"),
        "is_active": True
    }

@app.get("/events/{event_id}", response_model=EventResponse)
def get_event(event_id: int, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    
    return {
        "id": event.id,
        "event_name": event.event_name,
        "event_schedule": event.event_schedule.strftime("%Y-%m-%d %H:%M:%S"),
        "is_active": event.is_active,
        "user_id": event.user_id,
        "created_at": event.created_at.strftime("%Y-%m-%d %H:%M:%S")
    }

@app.put("/events/{event_id}")
def update_event(event_id: int, event_update: EventCreate, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    
    try:
        # Parse the datetime string (format: "YYYY-MM-DD HH:MM:SS")
        event_schedule = datetime.strptime(event_update.event_schedule, "%Y-%m-%d %H:%M:%S")
        
        event.event_name = event_update.event_name
        event.event_schedule = event_schedule
        event.user_id = event_update.user_id
        
        db.commit()
        db.refresh(event)
        
        return {"message": "Event updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error updating event: {str(e)}")

@app.delete("/events/{event_id}")
def delete_event(event_id: int, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    
    was_active = event.is_active
    
    # Remove event reference from users
    db.query(User).filter(User.event_id == event_id).update({User.event_id: None})
    
    # Delete the event
    db.delete(event)
    db.commit()
    
    # If the deleted event was active, set another event as active
    if was_active:
        next_event = db.query(Event).first()
        if next_event:
            next_event.is_active = True
            db.commit()
    
    return {"message": "Event deleted successfully"}

@app.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    db.delete(user)
    db.commit()
    
    return {"message": "User deleted successfully"}