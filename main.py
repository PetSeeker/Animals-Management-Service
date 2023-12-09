import boto3, psycopg2, os, logging
from fastapi import FastAPI, Form, UploadFile, HTTPException, File, Query 
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from uuid import UUID, uuid4
from io import BytesIO
from typing import List

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

s3 = boto3.client('s3', aws_access_key_id=ACCESS_KEY, aws_secret_access_key=SECRET_KEY, region_name=REGION)
#bucket = s3.Bucket(AWS_BUCKET)

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

            if animal_age <= 0 or (animal_price is not None and animal_price <= 0):
                return HTTPException(status_code=400, detail="Price and age must be greater than 0")
             
            if listing_type not in ['SALE', 'ADOPTION']:
                return HTTPException(status_code=400, detail="Invalid listing_type. Allowed values are 'SALE' or 'ADOPTION'.")
            
            if listing_type == "SALE" and animal_price is None:
                return HTTPException(status_code=400, detail="Price is required for SALE listings")
            
            if listing_type == "ADOPTION" and animal_price is not None:
                return HTTPException(status_code=400, detail="Price is not required for ADOPTION listings")
            
            listing_id = insert_listing_data(
                cursor, owner_email, animal_type, animal_breed,
                animal_age, animal_name, location,listing_type, animal_price, description
            )
            for image in images:
                if image:
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
    images: list[UploadFile] = Form([]),
):
    global connection

    try:
        with connection.cursor() as cursor:
            
            if animal_age <= 0 or (animal_price is not None and animal_price <= 0):
                return HTTPException(status_code=400, detail="Price and age must be greater than 0")
                
            if listing_type not in ['SALE', 'ADOPTION']:
                return HTTPException(status_code=400, detail="Invalid listing_type. Allowed values are 'SALE' or 'ADOPTION'.")
        
            if listing_type == "SALE" and animal_price is None:
                return HTTPException(status_code=400, detail="Price is required for SALE listings")
            
            if listing_type == "ADOPTION" and animal_price is not None:
                return HTTPException(status_code=400, detail="Price is not required for ADOPTION listings")
            
            check_listing_query = "SELECT * FROM listings WHERE id = %s"
            cursor.execute(check_listing_query, (str(listing_id),))
            existing_listing = cursor.fetchone()

            if not existing_listing:
                return HTTPException(status_code=404, detail="Listing not found")

            update_listing(cursor, listing_id, owner_email, animal_type, animal_breed, animal_age, animal_name, location, listing_type, animal_price, description)

            for image in images:
                if image:
                    image_url = upload_image_to_s3(image)
                    insert_image_data(cursor, image.filename, image_url, str(listing_id))

            connection.commit()

            return {"message": "Listing updated successfully with images"}
    
    except Exception as e:
        connection.rollback()
        logger.error(f"Error updating listing: {e}")
        return HTTPException(status_code=500, detail="Internal Server Error")

@app.put("/listings/{listing_id}/status")
async def update_listing_status(
    listing_id: UUID,
    listing_status: str = Form(...)
):
    global connection

    try:
        with connection.cursor() as cursor:

            if listing_status != "ACCEPTED":
                return HTTPException(status_code=400, detail="Invalid listing_status. Allowed values are 'ACCEPTED'")
            
            check_listing_query = "SELECT * FROM listings WHERE id = %s"
            cursor.execute(check_listing_query, (str(listing_id),))
            existing_listing = cursor.fetchone()

            if not existing_listing:
                return HTTPException(status_code=404, detail="Listing not found")

            update_listing_status_query = "UPDATE listings SET listing_status = %s WHERE id = %s"
            cursor.execute(update_listing_status_query, (listing_status, str(listing_id)))

            connection.commit()

            return {"message": "Listing status updated successfully"}
    
    except Exception as e:
        connection.rollback()
        logger.error(f"Error updating listing status: {e}")
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
async def get_listings_by_filter(
    listing_status: str = Query(...),
    listing_type: str = Query(None), 
    animal_type: str = Query(None), 
    user_emails: str = Query(None)):

    global connection
    try:
        with connection.cursor() as cursor:
            
            user_emails_list = user_emails.split(",") if user_emails else []
            listings = []
        
            if user_emails_list:
                for user_email in user_emails_list:
                    query = """ SELECT id, owner_email, animal_type, animal_breed, animal_age, animal_name, 
                                location, listing_type, animal_price, description
                                    FROM listings 
                                        WHERE owner_email = %s AND listing_status = %s
                            """
                    params = (user_email,listing_status,)

                    if listing_type:
                        query += " AND listing_type = %s"
                        params += (listing_type,)

                        if animal_type is not None:
                            query += " AND animal_type = %s"
                            params += (animal_type,)

                    cursor.execute(query, params)
                    rows = cursor.fetchall()

                    for row in rows:
                        listings.append(process_row(row, cursor))
            else:
                query = """ SELECT id, owner_email, animal_type, animal_breed, animal_age, animal_name, 
                            location, listing_type, animal_price, description 
                                FROM listings WHERE listing_status = %s
                        """
                params = (listing_status,)

                if listing_type:
                    query += " AND listing_type = %s"
                    params += (listing_type,)

                    if animal_type is not None:
                        query += " AND animal_type = %s"
                        params += (animal_type,)

                cursor.execute(query, params)
                rows = cursor.fetchall()

                for row in rows:
                    listings.append(process_row(row, cursor))

        return {"listings": listings}
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@app.get("/listings/user/{user_email}")
async def get_user_listings(
    user_email: str,
    listing_status: str = Query(...),
    listing_type: str = Query(None)
):
    global connection
    try:
        with connection.cursor() as cursor:
            if user_email is None:
                return HTTPException(status_code=404, detail="User email is missing")
            
            query = """ SELECT id, owner_email, animal_type, animal_breed, animal_age, animal_name, 
                                location, listing_type, animal_price, description
                                    FROM listings 
                                        WHERE owner_email = %s AND listing_status = %s
                            """
            params = (user_email,listing_status,)

            if listing_type:
                query += " AND listing_type = %s"
                params += (listing_type,)

            cursor.execute(query, params)

            rows = cursor.fetchall()
            user_listings = []
            for row in rows:
                user_listings.append(process_row(row, cursor))
        
            return {"user_listings": user_listings}
    
    except Exception as e:
        logger.error(f"Error: {e}")
        return HTTPException(status_code=500, detail="Internal Server Error")

@app.get("/listings/id/{listing_id}")
async def get_listing_by_id(listing_id: UUID):
    global connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM listings WHERE id = %s", (str(listing_id),))
            row = cursor.fetchone()
            if row:
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
                return {"listing": listing}
            else:
                return HTTPException(status_code=404, detail="Listing not found")
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
                listing_status VARCHAR(10) CHECK (listing_status IN ('ACCEPTED', 'PENDING')) NOT NULL,
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
        try:
            random_string = str(uuid4())
            unique_filename = f"{random_string}_{image.filename}"
            image_url = f"https://{AWS_BUCKET}.s3.{REGION}.amazonaws.com/{unique_filename}"

            image_data = BytesIO(image.file.read())
            s3.upload_fileobj(image_data, AWS_BUCKET, unique_filename, ExtraArgs={"ACL": "public-read", "ContentType": image.content_type})
            return image_url
        finally:
            image_data.close()

def insert_listing_data(cursor, owner_email, animal_type, animal_breed, animal_age, animal_name, location, listing_type, animal_price, description):
    listing_status = "PENDING"
    insert_query = "INSERT INTO listings (owner_email, animal_type, animal_breed, animal_age, animal_name, location, listing_type, animal_price, listing_status, description) VALUES (%s,%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"
    cursor.execute(insert_query, (owner_email, animal_type, animal_breed, animal_age, animal_name, location, listing_type, animal_price, listing_status, description))
    return cursor.fetchone()[0]

def insert_image_data(cursor, image_filename, image_url, listing_id):
    insert_query = "INSERT INTO images (image_name, image_url, listing_id) VALUES (%s, %s, %s)"
    cursor.execute(insert_query, (image_filename, image_url, listing_id))

def update_listing(cursor, listing_id, owner_email, animal_type, animal_breed, animal_age, animal_name, location, listing_type, animal_price, description):
    listing_status = "PENDING"
    update_listing_query = """
        UPDATE listings
        SET owner_email = %s, animal_type = %s, animal_breed = %s, 
        animal_age = %s, animal_name = %s, location = %s, listing_type = %s, animal_price = %s, 
        listing_status = %s, description = %s
        WHERE id = %s
    """
    cursor.execute(update_listing_query, (owner_email, animal_type, animal_breed, animal_age, animal_name, location, listing_type, animal_price, listing_status, description, str(listing_id)))

def get_images_for_listing(listing_id, cursor):
    cursor.execute("SELECT image_url FROM images WHERE listing_id = %s", (listing_id,))
    image_rows = cursor.fetchall()
    images = [image[0] for image in image_rows]
    return images

def process_row(row, cursor):
    listing_id, owner_email, animal_type, animal_breed, animal_age, \
        animal_name, location, listing_type, animal_price, description = row

    images = get_images_for_listing(listing_id, cursor)
    listing = {
        "listing_id": listing_id,
        "owner_email": owner_email,
        "animal_type": animal_type,
        "animal_breed": animal_breed,
        "animal_age": animal_age,
        "animal_name": animal_name,
        "location": location,
        "listing_type": listing_type,
        "animal_price": animal_price,
        "description": description,
        "images": images
    }
    return listing