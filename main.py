import boto3, psycopg2, os, logging
from fastapi import FastAPI, Form, UploadFile, HTTPException, File, Query 
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from uuid import UUID, uuid4

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

@app.on_event("startup")
async def startup_event():
    while not connect_db():
            continue

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

@app.get("/health/")
async def health():
    return HTTPException(status_code=200, detail="Server is healthy")


@app.post("/listings/")
async def create_listing(
    owner_email: str = Form(...),
    animal_type: str = Form(...),
    animal_breed: str = Form(...),
    animal_age: int = Form(...),
    animal_name: str = Form(...),
    location: str = Form(...),
    listing_type: str = Form(...),
    animal_price: float = Form(None),
    description: str = Form(None),
    images: list[UploadFile] = Form([])
):
    global connection
    try:
        with connection.cursor() as cursor:
            if listing_type not in ['SALE', 'ADOPTION']:
                return HTTPException(status_code=400, detail="Invalid listing_type. Allowed values are 'SALE' or 'ADOPTION'.")
            
            if listing_type == "SALE" and animal_price is None:
                return HTTPException(status_code=400, detail="Price is required for SALE listings")
                
            listing_id = insert_listing_data(
                cursor, owner_email, animal_type, animal_breed,
                animal_age, animal_name, location,listing_type, animal_price, description
            )
            logger.info(images)
        
            for image in images:
                if image:
                    logger.info(f"Uploading image: {image.filename}")
                    image_url = upload_image_to_s3(image)
                    insert_image_data(cursor, image.filename, image_url, listing_id)

            connection.commit()

            return {"message": "Listing created successfully with images"}
    
    except Exception as e:
        connection.rollback()
        logger.error(f"Error updating listing: {e}")
        return HTTPException(status_code=500, detail="Internal Server Error")

@app.put("/listings/{listing_id}")
async def edit_listing(
    listing_id: UUID,
    owner_email: str = Form(...),
    animal_type: str = Form(...),
    animal_breed: str = Form(...),
    animal_age: int = Form(...),
    animal_name: str = Form(...),
    location: str = Form(...),
    listing_type: str = Form(...),
    animal_price: float = Form(None),
    description: str = Form(None),
    images: list[UploadFile] = Form([])
):
    global connection

    try:
        with connection.cursor() as cursor:

            if listing_type not in ['SALE', 'ADOPTION']:
                return HTTPException(status_code=400, detail="Invalid listing_type. Allowed values are 'SALE' or 'ADOPTION'.")
        
            if listing_type == "SALE" and animal_price is None:
                return HTTPException(status_code=400, detail="Price is required for SALE listings")
            
            check_listing_query = "SELECT * FROM listings WHERE id = %s"
            cursor.execute(check_listing_query, (str(listing_id),))
            existing_listing = cursor.fetchone()

            if not existing_listing:
                return HTTPException(status_code=404, detail="Listing not found")

            update_listing(cursor, listing_id, owner_email, animal_type, animal_breed, animal_age, animal_name, location, listing_type, animal_price, description)

            for image in images:
                if image:
                    logger.info(f"Inserting image: {image}")
                    image_url = upload_image_to_s3(image)
                    insert_image_data(cursor, image.filename, image_url, str(listing_id))

            connection.commit()

            return {"message": "Listing updated successfully with images"}
    
    except Exception as e:
        connection.rollback()
        logger.error(f"Error updating listing: {e}")
        return HTTPException(status_code=500, detail="Internal Server Error")

@app.delete("/listings/{listing_id}")
async def delete_listing(listing_id: UUID):
    global connection

    try:
        with connection.cursor() as cursor:
        
            check_listing_query = "SELECT * FROM listings WHERE id = %s"
            cursor.execute(check_listing_query, (str(listing_id),))
            existing_listing = cursor.fetchone()

            if not existing_listing:
                return HTTPException(status_code=404, detail="Listing not found")

            delete_listing_query = "DELETE FROM listings WHERE id = %s"
            cursor.execute(delete_listing_query, (str(listing_id),))

            delete_images_query = "DELETE FROM images WHERE listing_id = %s"
            cursor.execute(delete_images_query, (str(listing_id),))

            connection.commit()

            return {"message": "Listing deleted successfully"}
    
    except Exception as e:
        connection.rollback()
        logger.error(f"Error deleting listing: {e}")
        return HTTPException(status_code=500, detail="Internal Server Error")

@app.get("/listings/")
async def get_listings_by_type(listing_type: str = Query(None)):
    global connection
    try:
        with connection.cursor() as cursor:
            if listing_type:
                cursor.execute("SELECT * FROM listings WHERE listing_type = %s", (listing_type,))
            else:
                cursor.execute("SELECT * FROM listings")

            rows = cursor.fetchall()
            listings = []
            for row in rows:
                listing_id = row[0]
                images = get_images_for_listing(listing_id, cursor)
                listing = {
                    "listing_id": listing_id,
                    "owner_email": row[1],
                    "animal_type": row[2],
                    "animal_breed": row[3],
                    "animal_age": row[4],
                    "animal_name": row[5],
                    "location": row[6],
                    "listing_type": row[7],
                    "animal_price": row[8],
                    "description": row[9],
                    "images": images
                }
                listings.append(listing)

            return {"listings": listings}
    except Exception as e:
        logger.error(f"Error: {e}")
        return HTTPException(status_code=500, detail="Internal Server Error")

@app.get("/listings/{user_email}")
async def get_listings_by_user_and_type(
    user_email: str,
    listing_type: str = Query(None)
):
    global connection
    try:
        with connection.cursor() as cursor:
            if user_email is None:
                return HTTPException(status_code=404, detail="User email is missing")

            if listing_type:
                query = "SELECT * FROM listings WHERE owner_email = %s AND listing_type = %s"
                cursor.execute(query, (user_email, listing_type))
            else:
                query = "SELECT * FROM listings WHERE owner_email = %s"
                cursor.execute(query, (user_email,))

            rows = cursor.fetchall()
            user_listings = []
            for row in rows:
                listing_id = row[0]
                images = get_images_for_listing(listing_id, cursor)
                user_listing = {
                    "listing_id": listing_id,
                    "owner_email": row[1],
                    "animal_type": row[2],
                    "animal_breed": row[3],
                    "animal_age": row[4],
                    "animal_name": row[5],
                    "location": row[6],
                    "listing_type": row[7],
                    "animal_price": row[8],
                    "description": row[9],
                    "images": images
                }
                user_listings.append(user_listing)

            return {"user_listings": user_listings}
    
    except Exception as e:
        logger.error(f"Error: {e}")
        return HTTPException(status_code=500, detail="Internal Server Error")

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
                animal_name VARCHAR NOT NULL,
                location VARCHAR NOT NULL,
                listing_type VARCHAR(10) CHECK (listing_type IN ('SALE', 'ADOPTION')) NOT NULL,
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
    random_string = str(uuid4())
    unique_filename = f"{random_string}_{image.filename}"
    image_url = f"https://{AWS_BUCKET}.s3.amazonaws.com/{unique_filename}"
    bucket.upload_fileobj(image.file, unique_filename, ExtraArgs={"ACL": "public-read"})
    return image_url

def insert_listing_data(cursor, owner_email, animal_type, animal_breed, animal_age, animal_name, location, listing_type, animal_price, description):
    insert_query = "INSERT INTO listings (owner_email, animal_type, animal_breed, animal_age, animal_name, location, listing_type, animal_price, description) VALUES (%s,%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"
    cursor.execute(insert_query, (owner_email, animal_type, animal_breed, animal_age, animal_name, location,listing_type, animal_price, description))
    return cursor.fetchone()[0]

def insert_image_data(cursor, image_filename, image_url, listing_id):
    insert_query = "INSERT INTO images (image_name, image_url, listing_id) VALUES (%s, %s, %s)"
    cursor.execute(insert_query, (image_filename, image_url, listing_id))

def update_listing(cursor, listing_id, owner_email, animal_type, animal_breed, animal_age, animal_name, location, listing_type, animal_price, description):
    update_listing_query = """
        UPDATE listings
        SET owner_email = %s, animal_type = %s, animal_breed = %s, 
        animal_age = %s, animal_name = %s, location = %s, listing_type = %s, animal_price = %s, 
        description = %s
        WHERE id = %s
    """
    cursor.execute(update_listing_query, (owner_email, animal_type, animal_breed, animal_age, animal_name, location, listing_type, animal_price, description, str(listing_id)))

def get_images_for_listing(listing_id, cursor):
    cursor.execute("SELECT image_url FROM images WHERE listing_id = %s", (listing_id,))
    image_rows = cursor.fetchall()
    images = [image[0] for image in image_rows]
    return images