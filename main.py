import os
import logging
from fastapi import FastAPI, Depends, HTTPException
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from bson import ObjectId
from datetime import datetime, timezone, timedelta
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel, Field, validator
import certifi

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB connection
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb+srv://arnel123:123123123@cluster0.tpjir.mongodb.net/?appName=Cluster0")
DB_NAME = os.getenv("DB_NAME", "visitors_db")

# Configure MongoDB client
try:
    # Add TLS/SSL certificates for secure connection
    client = MongoClient(
        MONGODB_URL,
        tlsCAFile=certifi.where(),  # For SSL certificate verification
        serverSelectionTimeoutMS=5000,  # Timeout after 5 seconds
        connectTimeoutMS=30000,
        socketTimeoutMS=30000
    )
    # Test connection
    client.admin.command('ping')
    logger.info("Successfully connected to MongoDB")
    
    db = client[DB_NAME]
    users_collection = db["users"]
    events_collection = db["events"]
    
    # Create indexes
    users_collection.create_index("email", unique=True)
    events_collection.create_index("event_name")
    
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {str(e)}")
    raise

app = FastAPI()

# Update CORS for production
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
    return ph_time

# Pydantic models for request/response
class UserCreate(BaseModel):
    full_name: str
    company_name: str
    phone: str
    city: str
    region: str
    email: str

class UserResponse(BaseModel):
    id: str
    full_name: str
    company_name: str
    phone: str
    city: str
    region: str
    email: str
    created_at: datetime
    event_id: Optional[str] = None
    event_name: Optional[str] = None
    event_schedule: Optional[datetime] = None

class EventCreate(BaseModel):
    event_name: str
    event_schedule: str
    user_id: Optional[str] = None

class EventResponse(BaseModel):
    id: str
    event_name: str
    event_schedule: datetime
    is_active: bool
    user_id: Optional[str] = None
    created_at: datetime
    
    class Config:
        json_encoders = {
            ObjectId: str
        }

# Helper function to convert MongoDB document to dict with string ID
def mongo_to_dict(obj, additional_fields=None):
    if obj:
        obj['id'] = str(obj['_id'])
        del obj['_id']
        if additional_fields:
            obj.update(additional_fields)
    return obj

# Dependency to get database
def get_db():
    return {
        "users": users_collection,
        "events": events_collection
    }

# Health check endpoint
@app.get("/health")
def health_check(db=Depends(get_db)):
    try:
        # Test database connection
        user_count = db["users"].count_documents({})
        return {
            "status": "healthy", 
            "database": "connected",
            "database_type": "mongodb",
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
        "database": "mongodb"
    }

@app.get("/debug/db-status")
def db_status(db=Depends(get_db)):
    try:
        # Test database connection
        user_count = db["users"].count_documents({})
        event_count = db["events"].count_documents({})
        
        # Get MongoDB info (mask connection string)
        db_url = os.getenv("MONGODB_URL", "Not set")
        if db_url != "Not set" and "@" in db_url:
            parts = db_url.split("@")
            masked_url = f"mongodb://****:****@{parts[1]}"
        else:
            masked_url = "mongodb://****:****@cluster.mongodb.net"
        
        return {
            "status": "connected",
            "database_type": "mongodb",
            "user_count": user_count,
            "event_count": event_count,
            "connection_string": masked_url,
            "database_name": DB_NAME,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Database connection error: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.post("/debug/check-user/{email}")
def check_user(email: str, db=Depends(get_db)):
    user = db["users"].find_one({"email": email})
    if user:
        user = mongo_to_dict(user)
        return {
            "exists": True,
            "user_id": user["id"],
            "full_name": user["full_name"],
            "created_at": user["created_at"].isoformat() if user.get("created_at") else None,
            "region": user["region"],
            "city": user["city"]
        }
    return {"exists": False}

@app.post("/register")
def register(user: UserCreate, db=Depends(get_db)):
    logger.info(f"Registration attempt for email: {user.email}")
    
    try:
        # Check if email already exists
        existing = db["users"].find_one({"email": user.email})
        if existing:
            logger.warning(f"Email already registered: {user.email}")
            raise HTTPException(status_code=400, detail="Email already registered")

        # Get active event
        active_event = db["events"].find_one({"is_active": True})
        
        # Create new user document
        new_user = {
            "full_name": user.full_name,
            "company_name": user.company_name,
            "phone": user.phone,
            "city": user.city,
            "region": user.region,
            "email": user.email,
            "created_at": get_philippine_time(),
            "event_id": str(active_event["_id"]) if active_event else None
        }

        result = db["users"].insert_one(new_user)
        new_user["_id"] = result.inserted_id
        
        logger.info(f"User registered successfully: ID {result.inserted_id}, Email: {user.email}")
        
        # Verify the user was saved
        verify_user = db["users"].find_one({"_id": result.inserted_id})
        if verify_user:
            logger.info(f"Verification: User {result.inserted_id} found in database")
        else:
            logger.error(f"Verification FAILED: User {result.inserted_id} not found after commit!")

        return {
            "message": "Registration successful",
            "user_id": str(result.inserted_id),
            "assigned_event": active_event["event_name"] if active_event else None,
            "registered_at": new_user["created_at"].strftime("%Y-%m-%d %H:%M:%S")
        }
        
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="Email already registered")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during registration: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

@app.get("/users", response_model=List[UserResponse])
def get_users(db=Depends(get_db)):
    try:
        users = list(db["users"].find().sort("created_at", -1))
        
        result = []
        for user in users:
            user_dict = mongo_to_dict(user)
            
            # Get event details if user has an event
            if user_dict.get("event_id"):
                event = db["events"].find_one({"_id": ObjectId(user_dict["event_id"])})
                if event:
                    user_dict["event_name"] = event["event_name"]
                    user_dict["event_schedule"] = event["event_schedule"]
            
            result.append(user_dict)
        
        logger.info(f"Fetching users: found {len(result)} users")
        return result
        
    except Exception as e:
        logger.error(f"Error fetching users: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching users")

@app.post("/events")
def create_event(event: EventCreate, db=Depends(get_db)):
    try:
        # Parse the datetime string (format: "YYYY-MM-DD HH:MM:SS")
        event_schedule = datetime.strptime(event.event_schedule, "%Y-%m-%d %H:%M:%S")
        
        event_count = db["events"].count_documents({})
        
        new_event = {
            "event_name": event.event_name,
            "event_schedule": event_schedule,
            "user_id": event.user_id,
            "is_active": (event_count == 0),
            "created_at": get_philippine_time()
        }
        
        result = db["events"].insert_one(new_event)
        
        logger.info(f"Event created successfully: {result.inserted_id} - {event.event_name}")
        
        return {
            "message": "Event created successfully",
            "event_id": str(result.inserted_id)
        }
    except Exception as e:
        logger.error(f"Error creating event: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error creating event: {str(e)}")

@app.get("/events", response_model=List[EventResponse])
def get_events(db=Depends(get_db)):
    try:
        events = list(db["events"].find().sort("event_schedule", 1))
        return [mongo_to_dict(event) for event in events]
    except Exception as e:
        logger.error(f"Error fetching events: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching events")

@app.post("/events/{event_id}/set-active")
def set_active_event(event_id: str, db=Depends(get_db)):
    try:
        event = db["events"].find_one({"_id": ObjectId(event_id)})
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Deactivate all events
        db["events"].update_many({}, {"$set": {"is_active": False}})
        
        # Activate the selected event
        db["events"].update_one(
            {"_id": ObjectId(event_id)}, 
            {"$set": {"is_active": True}}
        )
        
        logger.info(f"Event set to active: {event['event_name']} (ID: {event_id})")
        
        return {
            "message": f"Event '{event['event_name']}' is now the active event",
            "event_id": event_id
        }
    except Exception as e:
        logger.error(f"Error setting active event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error setting active event: {str(e)}")

@app.get("/events/active")
def get_active_event(db=Depends(get_db)):
    try:
        active_event = db["events"].find_one({"is_active": True})
        if not active_event:
            return {"message": "No active event set", "event_name": None}
        
        event_dict = mongo_to_dict(active_event)
        return {
            "id": event_dict["id"],
            "event_name": event_dict["event_name"],
            "event_schedule": event_dict["event_schedule"].strftime("%Y-%m-%d %H:%M:%S"),
            "is_active": True
        }
    except Exception as e:
        logger.error(f"Error fetching active event: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching active event")

@app.get("/events/{event_id}", response_model=EventResponse)
def get_event(event_id: str, db=Depends(get_db)):
    try:
        event = db["events"].find_one({"_id": ObjectId(event_id)})
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        return mongo_to_dict(event)
    except Exception as e:
        logger.error(f"Error fetching event: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching event")

@app.put("/events/{event_id}")
def update_event(event_id: str, event_update: EventCreate, db=Depends(get_db)):
    try:
        event = db["events"].find_one({"_id": ObjectId(event_id)})
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Parse the datetime string
        event_schedule = datetime.strptime(event_update.event_schedule, "%Y-%m-%d %H:%M:%S")
        
        db["events"].update_one(
            {"_id": ObjectId(event_id)},
            {"$set": {
                "event_name": event_update.event_name,
                "event_schedule": event_schedule,
                "user_id": event_update.user_id
            }}
        )
        
        logger.info(f"Event updated successfully: {event_id} - {event_update.event_name}")
        
        return {"message": "Event updated successfully"}
    except Exception as e:
        logger.error(f"Error updating event: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error updating event: {str(e)}")

@app.delete("/events/{event_id}")
def delete_event(event_id: str, db=Depends(get_db)):
    try:
        event = db["events"].find_one({"_id": ObjectId(event_id)})
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        was_active = event["is_active"]
        
        # Remove event reference from users
        db["users"].update_many(
            {"event_id": event_id},
            {"$set": {"event_id": None}}
        )
        
        # Delete the event
        db["events"].delete_one({"_id": ObjectId(event_id)})
        
        # If the deleted event was active, set another event as active
        if was_active:
            next_event = db["events"].find_one()
            if next_event:
                db["events"].update_one(
                    {"_id": next_event["_id"]},
                    {"$set": {"is_active": True}}
                )
        
        logger.info(f"Event deleted successfully: ID {event_id}")
        
        return {"message": "Event deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting event: {str(e)}")

@app.delete("/users/{user_id}")
def delete_user(user_id: str, db=Depends(get_db)):
    try:
        user = db["users"].find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        db["users"].delete_one({"_id": ObjectId(user_id)})
        
        logger.info(f"User deleted successfully: ID {user_id}")
        
        return {"message": "User deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting user: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting user: {str(e)}")

# Optional: Add cleanup on shutdown
@app.on_event("shutdown")
def shutdown_db_client():
    client.close()
    logger.info("MongoDB connection closed")