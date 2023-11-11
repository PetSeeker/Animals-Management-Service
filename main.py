import boto3, psycopg2, uvicorn, os, logging
from fastapi import FastAPI, UploadFile, Form, File
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from uuid import UUID

# FastAPI App Configuration
app = FastAPI(debug=True)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

connection = None
cursor = None

AWS_BUCKET = os.getenv("BUCKET")
ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
REGION = os.getenv("REGION")

s3 = boto3.resource('s3', aws_access_key_id=ACCESS_KEY, aws_secret_access_key=SECRET_KEY, region_name=REGION)
bucket = s3.Bucket(AWS_BUCKET)

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_DATABASE = os.getenv("DB_DATABASE")

app = FastAPI()

# Database Connection
def connect_db():
    global connection, cursor
    try:
        connection = psycopg2.connect(user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT, database=DB_DATABASE)

        cursor = connection.cursor()
        if connection:
            cursor.execute("SELECT version();")
            db_version = cursor.fetchone()
            logger.info(f"Connected to {db_version[0]}")
            create_tables()
            return True
        else:
            logger.error("Failed to connect to the database.")
            return False
    except (Exception, psycopg2.Error) as error:
        logger.error(f"Error while connecting to PostgreSQL: {error}")
        return False

@app.post("/listings/")
async def create_listing(
    owner_email: str = Form(...),
    animal_type: str = Form(...),
    animal_breed: str = Form(...),
    animal_age: int = Form(...),
    listing_type: str = Form(...),
    animal_price: float = Form(None),
    description: str = Form(None),
    images: list[UploadFile] = File(...),
):
    global connection, cursor

    try:
        cursor = connection.cursor()

        if listing_type == "SALE" and animal_price is None:
            raise Exception("Price is required for SALE listings")

        listing_id = insert_listing_data(cursor, owner_email, animal_type, animal_breed, animal_age, listing_type, animal_price, description)

        for image in images:
            image_url = upload_image_to_s3(image)
            insert_image_data(cursor, image.filename, image_url, listing_id)

        connection.commit()

        return {"message": "Listing created successfully with images"}
    
    except Exception as e:
        connection.rollback()
        return JSONResponse(jsonable_encoder({"ERROR": str(e)}))@app.put("/listings/{listing_id}")

@app.put("/listings/{listing_id}")
async def edit_listing(
    listing_id: UUID,
    owner_email: str = Form(...),
    animal_type: str = Form(...),
    animal_breed: str = Form(...),
    animal_age: int = Form(...),
    listing_type: str = Form(...),
    animal_price: float = Form(None),
    description: str = Form(None),
    images: list[UploadFile] = File(...),
):
    global connection, cursor

    try:
        cursor = connection.cursor()

        check_listing_query = "SELECT * FROM listings WHERE id = %s"
        cursor.execute(check_listing_query, (str(listing_id),))
        existing_listing = cursor.fetchone()

        if not existing_listing:
            raise Exception("Listing not found")

        update_listing_query = """
            UPDATE listings
            SET owner_email = %s, animal_type = %s, animal_breed = %s, 
            animal_age = %s, listing_type = %s, animal_price = %s, 
            description = %s
            WHERE id = %s
        """
        cursor.execute(update_listing_query, (owner_email, animal_type, animal_breed, animal_age, listing_type, animal_price, description, str(listing_id)))

        get_existing_images_query = "SELECT image_name FROM images WHERE listing_id = %s"
        cursor.execute(get_existing_images_query, (str(listing_id),))
        existing_images_rows = cursor.fetchall()
        existing_images = set(row[0] for row in existing_images_rows) if existing_images_rows else set()

        new_image_filenames = set(image for image in images)
        images_to_delete = existing_images - new_image_filenames
        images_to_insert = new_image_filenames - existing_images
     
        delete_images_query = "DELETE FROM images WHERE listing_id = %s AND image_name = %s"
        for image in images_to_delete:
            cursor.execute(delete_images_query, (str(listing_id), image))

        for image in images_to_insert:
            image_url = upload_image_to_s3(image)
            insert_image_data(cursor, image.filename, image_url, str(listing_id))

        connection.commit()

        return {"message": "Listing updated successfully with images"}
    
    except Exception as e:
        connection.rollback()
        return JSONResponse(jsonable_encoder({"ERROR": str(e)}))

@app.delete("/listings/{listing_id}")
async def delete_listing(listing_id: UUID):
    global connection, cursor

    try:
        cursor = connection.cursor()

        # Check if the listing with the given ID exists
        check_listing_query = "SELECT * FROM listings WHERE id = %s"
        cursor.execute(check_listing_query, (str(listing_id),))
        existing_listing = cursor.fetchone()

        if not existing_listing:
            raise Exception("Listing not found")

        # Delete the listing
        delete_listing_query = "DELETE FROM listings WHERE id = %s"
        cursor.execute(delete_listing_query, (str(listing_id),))

        # Delete associated images
        delete_images_query = "DELETE FROM images WHERE listing_id = %s"
        cursor.execute(delete_images_query, (str(listing_id),))

        connection.commit()

        return {"message": "Listing deleted successfully"}
    
    except Exception as e:
        connection.rollback()
        return JSONResponse(jsonable_encoder({"ERROR": str(e)}))

@app.get("/listings/")
async def get_all_listings():
    global connection, cursor
    try:
        cursor.execute("SELECT * FROM listings")
        rows = cursor.fetchall()
        listings = [{"listing_id": row[0], "owner_email": row[1], "animal_type": row[2], "animal_breed": row[3], "animal_age": row[4], "listing_type": row[5], "animal_price": row[6], "description": row[7]} for row in rows]

        return JSONResponse(jsonable_encoder({"listings": listings}))
    except Exception as e:
        error_message = f"Error getting listings -> {str(e)}"
        return {"message": error_message}

@app.get("/listings/{user_email}")
async def get_listings_by_user(user_email: str):
    global connection, cursor
    try:
        if user_email is None:
            raise ValueError("User email is missing")

        query = "SELECT * FROM listings WHERE owner_email = %s"
        cursor.execute(query, (user_email,))
        rows = cursor.fetchall()

        if not rows:
            return JSONResponse(jsonable_encoder({"message": "No listings found for this user"}))

        user_listings = [{"listing_id": row[0], "owner_email": row[1], "animal_type": row[2], "animal_breed": row[3], "animal_age": row[4], "listing_type": row[5], "animal_price": row[6], "description": row[7]} for row in rows]

        return JSONResponse(jsonable_encoder({"user_listings": user_listings}))
    
    except ValueError as e:
        return JSONResponse(jsonable_encoder({"message": f"Invalid query parameter: {e}"}))
    
    except Exception as e:
        return JSONResponse(jsonable_encoder({"ERROR": str(e)}))

# Function to create tables
def create_tables():
    try:
        global connection,cursor

        # Create the 'listings' 
        create_listings_table = """
            CREATE TABLE IF NOT EXISTS listings (
                id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
                owner_email VARCHAR NOT NULL,
                animal_type VARCHAR NOT NULL,
                animal_breed VARCHAR NOT NULL,
                animal_age INT NOT NULL,
                listing_type VARCHAR NOT NULL,
                animal_price DOUBLE PRECISION,
                description TEXT
            );
        """

        cursor = connection.cursor()
        cursor.execute(create_listings_table)

        # Create the 'images' table with a foreign key reference to listings
        create_images_table = """
            CREATE TABLE IF NOT EXISTS images (
                id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
                image_name TEXT NOT NULL,
                image_url TEXT NOT NULL,
                listing_id UUID REFERENCES listings(id) ON DELETE CASCADE
            );
        """
        cursor.execute(create_images_table)

        connection.commit()
        logger.info("Tables created successfully in PostgreSQL database")
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"Error creating tables: {error}")

def upload_image_to_s3(image):
    image_url = f"https://{AWS_BUCKET}.s3.amazonaws.com/{image.filename}"
    bucket.upload_fileobj(image.file, image.filename, ExtraArgs={"ACL": "public-read"})
    return image_url

def insert_listing_data(cursor, owner_email, animal_type, animal_breed, animal_age, listing_type, animal_price, description):
    insert_query = "INSERT INTO listings (owner_email, animal_type, animal_breed, animal_age, listing_type, animal_price, description) VALUES (%s,%s, %s, %s, %s, %s, %s) RETURNING id"
    cursor.execute(insert_query, (owner_email, animal_type, animal_breed, animal_age, listing_type, animal_price, description))
    return cursor.fetchone()[0]

def insert_image_data(cursor, image_filename, image_url, listing_id):
    insert_query = "INSERT INTO images (image_name, image_url, listing_id) VALUES (%s, %s, %s)"
    cursor.execute(insert_query, (image_filename, image_url, listing_id))

if __name__ == "__main__":
    while not connect_db():
        continue
    uvicorn.run(app, host="0.0.0.0", port=8000)
