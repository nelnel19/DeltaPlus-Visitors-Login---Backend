import os
import logging
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Use environment variable for database URL, fallback to local SQLite
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./users.db")
logger.info(f"Database URL: {DATABASE_URL[:20]}...")  # Log partial URL for debugging

# Fix for Render's PostgreSQL URL (starts with postgres://)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    logger.info("Converted postgres:// to postgresql://")

# Configure engine based on database type
if DATABASE_URL.startswith("postgresql"):
    # For PostgreSQL on Render
    engine = create_engine(
        DATABASE_URL,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,  # Verify connections before using
        pool_recycle=3600    # Recycle connections after 1 hour
    )
    logger.info("Using PostgreSQL engine with connection pooling")
else:
    # For SQLite (local development)
    engine = create_engine(
        DATABASE_URL, 
        connect_args={"check_same_thread": False}
    )
    logger.info("Using SQLite engine")

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

# Database Model for User
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String)
    company_name = Column(String)
    phone = Column(String)
    city = Column(String)
    region = Column(String)
    email = Column(String, unique=True)
    created_at = Column(DateTime, default=get_philippine_time)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=True)
    
    event = relationship("Event", foreign_keys=[event_id], back_populates="users")
    created_events = relationship("Event", foreign_keys="Event.user_id", back_populates="creator")

# Database Model for Event
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
logger.info("Creating database tables...")
Base.metadata.create_all(bind=engine)
logger.info("Database tables created successfully")

# Request Schemas
class UserCreate(BaseModel):
    full_name: str
    company_name: str
    phone: str
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
    except Exception as e:
        logger.error(f"Database session error: {str(e)}")
        db.rollback()
    finally:
        db.close()

# Health check endpoint for Render
@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    try:
        # Test database connection
        user_count = db.query(User).count()
        return {
            "status": "healthy", 
            "database": "connected",
            "user_count": user_count,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}

@app.get("/")
def root():
    return {
        "message": "API is running", 
        "environment": os.getenv("RENDER", "development"),
        "database": os.getenv("DATABASE_URL", "sqlite").split(":")[0]
    }

@app.get("/debug/db-status")
def db_status(db: Session = Depends(get_db)):
    try:
        # Test database connection
        user_count = db.query(User).count()
        event_count = db.query(Event).count()
        
        # Get the actual database URL (masked for security)
        db_url = os.getenv("DATABASE_URL", "Not set")
        if db_url != "Not set":
            # Mask the password if present
            if "@" in db_url:
                parts = db_url.split("@")
                credentials = parts[0].split("://")[1].split(":")
                if len(credentials) > 1:
                    masked_url = f"{parts[0].split('://')[0]}://{credentials[0]}:****@{parts[1]}"
                else:
                    masked_url = db_url
            else:
                masked_url = db_url[:20] + "..."
        else:
            masked_url = "Not set"
        
        return {
            "status": "connected",
            "user_count": user_count,
            "event_count": event_count,
            "database_type": "postgresql" if DATABASE_URL.startswith("postgresql") else "sqlite",
            "database_url": masked_url,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Database connection error: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.post("/debug/check-user/{email}")
def check_user(email: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if user:
        return {
            "exists": True,
            "user_id": user.id,
            "full_name": user.full_name,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "region": user.region,
            "city": user.city
        }
    return {"exists": False}

@app.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    logger.info(f"Registration attempt for email: {user.email}")
    
    try:
        # Check if email already exists
        existing = db.query(User).filter(User.email == user.email).first()

        if existing:
            logger.warning(f"Email already registered: {user.email}")
            raise HTTPException(status_code=400, detail="Email already registered")

        # Get active event
        active_event = db.query(Event).filter(Event.is_active == True).first()
        
        # Create new user
        new_user = User(
            full_name=user.full_name,
            company_name=user.company_name,
            phone=user.phone,
            city=user.city,
            region=user.region,
            email=user.email,
            created_at=get_philippine_time(),
            event_id=active_event.id if active_event else None
        )

        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        logger.info(f"User registered successfully: ID {new_user.id}, Email: {new_user.email}")
        
        # Verify the user was saved
        verify_user = db.query(User).filter(User.id == new_user.id).first()
        if verify_user:
            logger.info(f"Verification: User {verify_user.id} found in database")
        else:
            logger.error(f"Verification FAILED: User {new_user.id} not found after commit!")

        return {
            "message": "Registration successful",
            "user_id": new_user.id,
            "assigned_event": active_event.event_name if active_event else None,
            "registered_at": new_user.created_at.strftime("%Y-%m-%d %H:%M:%S")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during registration: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

@app.get("/users")
def get_users(db: Session = Depends(get_db)):
    try:
        # Add cache control headers
        users = db.query(User).order_by(User.created_at.desc()).all()
        
        # Log the count for debugging
        logger.info(f"Fetching users: found {len(users)} users")
        
        return [
            {
                "id": user.id,
                "full_name": user.full_name,
                "company_name": user.company_name,
                "phone": user.phone,
                "city": user.city,
                "region": user.region,
                "email": user.email,
                "created_at": user.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "event_name": user.event.event_name if user.event else None,
                "event_schedule": user.event.event_schedule.strftime("%Y-%m-%d %H:%M:%S") if user.event else None
            }
            for user in users
        ]
    except Exception as e:
        logger.error(f"Error fetching users: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching users")

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
            created_at=get_philippine_time()
        )
        
        db.add(new_event)
        db.commit()
        db.refresh(new_event)
        
        logger.info(f"Event created successfully: {new_event.id} - {new_event.event_name}")
        
        return {
            "message": "Event created successfully",
            "event_id": new_event.id
        }
    except Exception as e:
        logger.error(f"Error creating event: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Error creating event: {str(e)}")

@app.get("/events", response_model=List[EventResponse])
def get_events(db: Session = Depends(get_db)):
    try:
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
    except Exception as e:
        logger.error(f"Error fetching events: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching events")

@app.post("/events/{event_id}/set-active")
def set_active_event(event_id: int, db: Session = Depends(get_db)):
    try:
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Deactivate all events
        db.query(Event).update({Event.is_active: False})
        # Activate the selected event
        event.is_active = True
        db.commit()
        
        logger.info(f"Event set to active: {event.event_name} (ID: {event.id})")
        
        return {
            "message": f"Event '{event.event_name}' is now the active event",
            "event_id": event.id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting active event: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error setting active event: {str(e)}")

@app.get("/events/active")
def get_active_event(db: Session = Depends(get_db)):
    try:
        active_event = db.query(Event).filter(Event.is_active == True).first()
        if not active_event:
            return {"message": "No active event set", "event_name": None}
        
        return {
            "id": active_event.id,
            "event_name": active_event.event_name,
            "event_schedule": active_event.event_schedule.strftime("%Y-%m-%d %H:%M:%S"),
            "is_active": True
        }
    except Exception as e:
        logger.error(f"Error fetching active event: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching active event")

@app.get("/events/{event_id}", response_model=EventResponse)
def get_event(event_id: int, db: Session = Depends(get_db)):
    try:
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching event: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching event")

@app.put("/events/{event_id}")
def update_event(event_id: int, event_update: EventCreate, db: Session = Depends(get_db)):
    try:
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Parse the datetime string (format: "YYYY-MM-DD HH:MM:SS")
        event_schedule = datetime.strptime(event_update.event_schedule, "%Y-%m-%d %H:%M:%S")
        
        event.event_name = event_update.event_name
        event.event_schedule = event_schedule
        event.user_id = event_update.user_id
        
        db.commit()
        db.refresh(event)
        
        logger.info(f"Event updated successfully: {event.id} - {event.event_name}")
        
        return {"message": "Event updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating event: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Error updating event: {str(e)}")

@app.delete("/events/{event_id}")
def delete_event(event_id: int, db: Session = Depends(get_db)):
    try:
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
        
        logger.info(f"Event deleted successfully: ID {event_id}")
        
        return {"message": "Event deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting event: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting event: {str(e)}")

@app.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        db.delete(user)
        db.commit()
        
        logger.info(f"User deleted successfully: ID {user_id}")
        
        return {"message": "User deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting user: {str(e)}")