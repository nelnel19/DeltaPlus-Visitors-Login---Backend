import os
import logging
from fastapi import FastAPI, Depends, HTTPException
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from bson import ObjectId
from datetime import datetime, timezone, timedelta
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel
import certifi

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB connection
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb+srv://arnel123:123123123@cluster0.tpjir.mongodb.net/?appName=Cluster0")
DB_NAME = os.getenv("DB_NAME", "visitors_db")

# Configure MongoDB client
try:
    client = MongoClient(
        MONGODB_URL,
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=30000,
        socketTimeoutMS=30000
    )
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

# CORS configuration
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
    ph_time = utc_time + timedelta(hours=8)
    return ph_time

# Pydantic models
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
    event_location: str
    event_start_date: str
    event_end_date: str
    user_id: Optional[str] = None

class EventResponse(BaseModel):
    id: str
    event_name: str
    event_location: str
    event_start_date: datetime
    event_end_date: datetime
    is_active: bool
    user_id: Optional[str] = None
    created_at: datetime

def mongo_to_dict(obj):
    if obj:
        obj['id'] = str(obj['_id'])
        del obj['_id']
    return obj

def get_db():
    return {
        "users": users_collection,
        "events": events_collection
    }

@app.get("/health")
def health_check(db=Depends(get_db)):
    try:
        user_count = db["users"].count_documents({})
        return {
            "status": "healthy", 
            "database": "connected",
            "user_count": user_count,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {"status": "unhealthy", "error": str(e)}

@app.get("/")
def root():
    return {"message": "API is running", "database": "mongodb"}

@app.post("/register")
def register(user: UserCreate, db=Depends(get_db)):
    logger.info(f"Registration attempt for email: {user.email}")
    
    try:
        existing = db["users"].find_one({"email": user.email})
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")

        active_event = db["events"].find_one({"is_active": True})
        
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
        
        return {
            "message": "Registration successful",
            "user_id": str(result.inserted_id),
            "assigned_event": active_event["event_name"] if active_event else None,
        }
        
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="Email already registered")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during registration: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

@app.get("/users")
def get_users(db=Depends(get_db)):
    try:
        users = list(db["users"].find().sort("created_at", -1))
        
        result = []
        for user in users:
            user_dict = mongo_to_dict(user)
            
            if user_dict.get("event_id"):
                event = db["events"].find_one({"_id": ObjectId(user_dict["event_id"])})
                if event:
                    user_dict["event_name"] = event["event_name"]
                    # Use event_start_date if exists, otherwise use event_schedule
                    if event.get("event_start_date"):
                        user_dict["event_schedule"] = event["event_start_date"]
                    elif event.get("event_schedule"):
                        user_dict["event_schedule"] = event["event_schedule"]
            
            result.append(user_dict)
        
        return result
        
    except Exception as e:
        logger.error(f"Error fetching users: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching users")

@app.post("/events")
def create_event(event: EventCreate, db=Depends(get_db)):
    try:
        # Parse dates
        event_start_date = datetime.strptime(event.event_start_date, "%Y-%m-%d")
        event_end_date = datetime.strptime(event.event_end_date, "%Y-%m-%d")
        
        if event_end_date < event_start_date:
            raise HTTPException(status_code=400, detail="End date cannot be before start date")
        
        event_count = db["events"].count_documents({})
        
        new_event = {
            "event_name": event.event_name,
            "event_location": event.event_location,
            "event_start_date": event_start_date,
            "event_end_date": event_end_date,
            "user_id": event.user_id,
            "is_active": (event_count == 0),
            "created_at": get_philippine_time()
        }
        
        result = db["events"].insert_one(new_event)
        
        return {
            "message": "Event created successfully",
            "event_id": str(result.inserted_id)
        }
    except Exception as e:
        logger.error(f"Error creating event: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error creating event: {str(e)}")

@app.get("/events")
def get_events(db=Depends(get_db)):
    try:
        events = list(db["events"].find().sort("created_at", -1))
        
        # Format events to handle both old and new structure
        formatted_events = []
        for event in events:
            event_dict = mongo_to_dict(event)
            
            # Handle old events (with event_schedule)
            if "event_schedule" in event_dict and "event_start_date" not in event_dict:
                event_dict["event_start_date"] = event_dict["event_schedule"]
                event_dict["event_end_date"] = event_dict["event_schedule"]
                event_dict["event_location"] = event_dict.get("event_location", "TBA")
            
            # Ensure all events have required fields
            if "event_start_date" not in event_dict:
                event_dict["event_start_date"] = event_dict.get("created_at", datetime.now())
            if "event_end_date" not in event_dict:
                event_dict["event_end_date"] = event_dict.get("created_at", datetime.now())
            if "event_location" not in event_dict:
                event_dict["event_location"] = "TBA"
            
            formatted_events.append(event_dict)
        
        return formatted_events
    except Exception as e:
        logger.error(f"Error fetching events: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching events: {str(e)}")

@app.post("/events/{event_id}/set-active")
def set_active_event(event_id: str, db=Depends(get_db)):
    try:
        event = db["events"].find_one({"_id": ObjectId(event_id)})
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        db["events"].update_many({}, {"$set": {"is_active": False}})
        db["events"].update_one({"_id": ObjectId(event_id)}, {"$set": {"is_active": True}})
        
        return {"message": f"Event '{event['event_name']}' is now active"}
    except Exception as e:
        logger.error(f"Error setting active event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.get("/events/active")
def get_active_event(db=Depends(get_db)):
    try:
        active_event = db["events"].find_one({"is_active": True})
        if not active_event:
            return {"message": "No active event set", "event_name": None}
        
        event_dict = mongo_to_dict(active_event)
        
        # Handle old event structure
        if "event_schedule" in event_dict and "event_start_date" not in event_dict:
            event_dict["event_start_date"] = event_dict["event_schedule"]
            event_dict["event_end_date"] = event_dict["event_schedule"]
            event_dict["event_location"] = event_dict.get("event_location", "TBA")
        
        # Ensure all fields exist
        start_date = event_dict.get("event_start_date")
        end_date = event_dict.get("event_end_date")
        location = event_dict.get("event_location", "TBA")
        
        return {
            "id": event_dict["id"],
            "event_name": event_dict["event_name"],
            "event_location": location,
            "event_start_date": start_date.strftime("%Y-%m-%d") if start_date else "",
            "event_end_date": end_date.strftime("%Y-%m-%d") if end_date else "",
            "is_active": True
        }
    except Exception as e:
        logger.error(f"Error fetching active event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.put("/events/{event_id}")
def update_event(event_id: str, event_update: EventCreate, db=Depends(get_db)):
    try:
        event = db["events"].find_one({"_id": ObjectId(event_id)})
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        event_start_date = datetime.strptime(event_update.event_start_date, "%Y-%m-%d")
        event_end_date = datetime.strptime(event_update.event_end_date, "%Y-%m-%d")
        
        if event_end_date < event_start_date:
            raise HTTPException(status_code=400, detail="End date cannot be before start date")
        
        db["events"].update_one(
            {"_id": ObjectId(event_id)},
            {"$set": {
                "event_name": event_update.event_name,
                "event_location": event_update.event_location,
                "event_start_date": event_start_date,
                "event_end_date": event_end_date,
                "user_id": event_update.user_id
            }}
        )
        
        return {"message": "Event updated successfully"}
    except Exception as e:
        logger.error(f"Error updating event: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error: {str(e)}")

@app.delete("/events/{event_id}")
def delete_event(event_id: str, db=Depends(get_db)):
    try:
        event = db["events"].find_one({"_id": ObjectId(event_id)})
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        was_active = event["is_active"]
        
        db["users"].update_many({"event_id": event_id}, {"$set": {"event_id": None}})
        db["events"].delete_one({"_id": ObjectId(event_id)})
        
        if was_active:
            next_event = db["events"].find_one()
            if next_event:
                db["events"].update_one({"_id": next_event["_id"]}, {"$set": {"is_active": True}})
        
        return {"message": "Event deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.delete("/users/{user_id}")
def delete_user(user_id: str, db=Depends(get_db)):
    try:
        result = db["users"].delete_one({"_id": ObjectId(user_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {"message": "User deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting user: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.on_event("shutdown")
def shutdown_db_client():
    client.close()
    logger.info("MongoDB connection closed")