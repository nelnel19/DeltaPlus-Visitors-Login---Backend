# migrate_db.py
import sqlite3
import os

def migrate_database():
    db_path = "users.db"
    
    # Check if database exists
    if not os.path.exists(db_path):
        print("Database not found. Please run the FastAPI server first to create it.")
        return
    
    # Connect to the database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check existing columns
        cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]
        print("Existing columns:", columns)
        
        # Add new columns if they don't exist
        new_columns = [
            ("house_number", "VARCHAR"),
            ("street_name", "VARCHAR"),
            ("barangay", "VARCHAR"),
            ("city", "VARCHAR"),
            ("province", "VARCHAR"),
            ("region", "VARCHAR")
        ]
        
        for column_name, column_type in new_columns:
            if column_name not in columns:
                try:
                    cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}")
                    print(f"Added column: {column_name}")
                except sqlite3.OperationalError as e:
                    print(f"Error adding {column_name}: {e}")
            else:
                print(f"Column {column_name} already exists")
        
        # Check if 'address' column exists and if we should drop it
        if 'address' in columns:
            print("\nNOTE: The 'address' column still exists in the database.")
            print("Since you're now using separate address fields, you may want to keep it for backward compatibility")
            print("or drop it if you're sure all data has been migrated.")
            
            # Optional: Uncomment these lines if you want to drop the address column
            # Note: SQLite has limited ALTER TABLE support, dropping columns is complex
            # Better to keep it for now or recreate the database
            
        conn.commit()
        print("\nMigration completed successfully!")
        
    except sqlite3.Error as e:
        print(f"Database error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database()