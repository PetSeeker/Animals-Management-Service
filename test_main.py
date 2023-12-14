import pytest, os
from uuid import uuid4
from fastapi.testclient import TestClient
from fastapi import UploadFile
from unittest.mock import patch, MagicMock
from main import app, connect_db

@pytest.fixture
def test_client():
    return TestClient(app)

@pytest.fixture
def mock_db_connection():
    with patch('main.psycopg2.connect') as mock_connect:
        mock_connection = MagicMock()
        mock_cursor = MagicMock()

        mock_cursor.__enter__.return_value = mock_cursor

        mock_connect.return_value = mock_connection

        yield mock_connection, mock_cursor 

def test_connect_db_success(mock_db_connection):
    mock_connection, mock_cursor = mock_db_connection
    mock_connection.cursor.return_value = mock_cursor

    result = connect_db()

    assert result is True

def test_health(test_client):

    response = test_client.get("/health/")
    
    assert response.status_code == 200
    assert response.json() == {"status": "Server is healthy"}

@pytest.mark.parametrize("animal_age, listing_type, animal_price, files, expected_status_code, expected_message", [
    (2, 'SALE', 100, None, 200, "Listing created successfully"),
    (2, 'ADOPTION', None, None, 200, "Listing created successfully"),
    (2, 'SALE', 100, [('test.jpg', open('test_images/test.jpg', 'rb'))], 200, "Listing created successfully"),
    (2, 'ADOPTION', None, [('test_images/test.jpg', open('test_images/test.jpg', 'rb')), ('test_images/test1.jpg', open('test_images/test1.jpg', 'rb'))], 200, "Listing created successfully"),
])
def test_create_listing_success(test_client, animal_age, listing_type, animal_price, files, expected_status_code, expected_message):
    form_data = {
        "owner_email": "test@example.com",
        "animal_type": "Dog",
        "animal_breed": "Labrador",
        "animal_name": "Buddy",
        "animal_age": animal_age,
        "location": "New York",
        "listing_type": listing_type,
        "animal_price": animal_price,
        "description": "This is a test listing"
    }

    response = test_client.post("/listings/", data=form_data, files=files)

    assert response.status_code == expected_status_code
    assert response.json()['message'] == expected_message

@pytest.mark.parametrize("animal_age, listing_type, animal_price, expected_status_code, expected_detail", [
    (0, 'SALE', 100, 400, "Price and age must be greater than 0"),
    (2, 'INVALID_TYPE', None, 400, "Invalid listing_type. Allowed values are 'SALE' or 'ADOPTION'."),
    (3, 'SALE', None, 400, "Price is required for SALE listings"),
    (3, 'ADOPTION', 100, 400, "Price is not required for ADOPTION listings"),
])
def test_create_listing_failure(test_client, animal_age, listing_type, animal_price, expected_status_code, expected_detail):

    form_data = {
        "owner_email": "test@example.com",
        "animal_type": "Dog",
        "animal_breed": "Labrador",
        "animal_name": "Buddy",
        "animal_age": animal_age,
        "location": "New York",
        "listing_type": listing_type,
        "animal_price": animal_price,
        "description": "This is a test listing"
    }

    response = test_client.post("/listings/", data=form_data)

    assert response.json()['status_code'] == expected_status_code
    assert response.json()['detail'] == expected_detail

@pytest.mark.parametrize("animal_age, listing_type, animal_price, files, expected_status_code, expected_message", [
    (2, 'SALE', 100, None, 200, "Listing updated successfully"),
    (2, 'ADOPTION', None, None, 200, "Listing updated successfully"),
    (2, 'SALE', 100, [('test_images/test.jpg', open('test_images/test.jpg', 'rb'))], 200, "Listing updated successfully"),
    (2, 'ADOPTION', None, [('test_images/test.jpg', open('test_images/test.jpg', 'rb')), ('test_images/test1.jpg', open('test_images/test1.jpg', 'rb'))], 200, "Listing updated successfully"),
])
def test_edit_listing_success(test_client, animal_age, listing_type, animal_price, files, expected_status_code, expected_message):

    listing_id = str(uuid4())
    form_data = {
        "owner_email": "new_test@example.com",
        "animal_type": "Cat",
        "animal_breed": "Siamese",
        "animal_age": animal_age,
        "animal_name": "Whiskers",
        "location": "New York",
        "listing_type": listing_type,
        "animal_price": animal_price,
        "description": "Updated test listing"
    }

    response = test_client.put(f"/listings/{listing_id}", data=form_data, files=files)

    assert response.status_code == expected_status_code
    assert response.json()['message'] == expected_message

@pytest.mark.parametrize("animal_age, listing_type, animal_price, expected_status_code, expected_detail", [
    (0, 'SALE', 100, 400, "Price and age must be greater than 0"),
    (2, 'INVALID_TYPE', None, 400, "Invalid listing_type. Allowed values are 'SALE' or 'ADOPTION'."),
    (3, 'SALE', None, 400, "Price is required for SALE listings"),
    (3, 'ADOPTION', 100, 400, "Price is not required for ADOPTION listings"),
])
def test_edit_listing_invalid_input(test_client, animal_age, listing_type, animal_price, expected_status_code, expected_detail):

    listing_id = str(uuid4())
    form_data = {
        "owner_email": "new_test@example.com",
        "animal_type": "Cat",
        "animal_breed": "Siamese",
        "animal_age": animal_age,
        "animal_name": "Whiskers",
        "location": "New York",
        "listing_type": listing_type,
        "animal_price": animal_price,
        "description": "Updated test listing"
    }

    response = test_client.put(f"/listings/{listing_id}", data=form_data)

    assert response.json()['status_code'] == expected_status_code
    assert response.json()['detail'] == expected_detail

def test_edit_listing_listing_not_found(test_client, mock_db_connection):
    
    mock_connection, mock_cursor = mock_db_connection
    mock_cursor.fetchone.return_value = None

    form_data = {
        "owner_email": "new_test@example.com",
        "animal_type": "Cat",
        "animal_breed": "Siamese",
        "animal_age": 3,
        "animal_name": "Whiskers",
        "location": "New York",
        "listing_type": "ADOPTION",
        "animal_price": None,
        "description": "Updated test listing"
    }

    mock_connection.cursor.return_value = mock_cursor

    listing_id = str(uuid4())
    with patch('main.connection', mock_connection):
        response = test_client.put(f"/listings/{listing_id}", data=form_data)
    
    assert response.json()['status_code'] == 404
    assert response.json()['detail'] == "Listing not found"
    
def test_delete_listing_success(test_client):
        
    listing_id = str(uuid4())

    response = test_client.delete(f"/listings/{listing_id}")

    assert response.status_code == 200
    assert response.json() == {"message": "Listing deleted successfully"}

def test_delete_listing_not_found(test_client, mock_db_connection):

    mock_connection, mock_cursor = mock_db_connection
    mock_cursor.fetchone.return_value = None

    mock_connection.cursor.return_value = mock_cursor
    
    listing_id = str(uuid4())
    with patch('main.connection', mock_connection):
        response = test_client.delete(f"/listings/{listing_id}")

    assert response.json()['status_code'] == 404
    assert response.json()['detail'] == "Listing not found"

def test_update_listing_status_success(test_client):

    listing_id = str(uuid4())
    form_data = {
        "listing_status": "ACCEPTED"
    }

    response = test_client.put(f"/listings/{listing_id}/status", data=form_data)

    print(response.json())

    assert response.status_code == 200
    assert response.json() == {"message": "Listing status updated successfully"}

def test_update_listing_status_failure(test_client):

    listing_id = str(uuid4())
    form_data = {
        "listing_status": "PENDING"
    }

    response = test_client.put(f"/listings/{listing_id}/status", data=form_data)

    print(response.json())

    assert response.json()['status_code'] == 400
    assert response.json()['detail'] == "Invalid listing_status. Allowed values are 'ACCEPTED'"

def test_update_listing_status_not_found(test_client, mock_db_connection):
    
    mock_connection, mock_cursor = mock_db_connection
    mock_cursor.fetchone.return_value = None

    mock_connection.cursor.return_value = mock_cursor
    
    listing_id = str(uuid4())
    with patch('main.connection', mock_connection):
        response = test_client.put(f"/listings/{listing_id}/status", data={"listing_status": "ACCEPTED"})

    assert response.json()['status_code'] == 404
    assert response.json()['detail'] == "Listing not found"

@pytest.mark.parametrize("params", [
    ({"listing_status": "PENDING", "listing_type": "SALE", "animal_type": "Dog", "user_emails": "test@example.com"}),
    ({"listing_status": "PENDING", "listing_type": "SALE", "user_emails": "test@example.com"}),
    ({"listing_status": "PENDING", "user_emails": "test@example.com"}),
    ({"listing_status": "PENDING", "listing_type": "SALE", "animal_type": "Dog"}),
    ({"listing_status": "PENDING", "listing_type": "SALE"}),
])
def test_get_listings_by_filter(test_client, mock_db_connection, params):
    
    mock_connection, mock_cursor = mock_db_connection

    listings = [{
        "listing_id": str(uuid4()),
        "owner_email": "test@example.com",
        "animal_type": "Dog",
        "animal_breed": "Labrador",
        "animal_age": 2,
        "animal_name": "Buddy",
        "location": "New York",
        "listing_type": "SALE",
        "animal_price": 1000.00,
        "description": "Description"
    }]  

    fetchall_return_values = [
        [tuple(listing.values()) for listing in listings],  # First fetchall call
        None 
    ]

    def mock_fetchall(*args, **kwargs):
        return fetchall_return_values.pop(0)

    mock_cursor.fetchall.side_effect = mock_fetchall

    mock_connection.cursor.return_value = mock_cursor

    with patch('main.connection', mock_connection):

        response = test_client.get("/listings/", params=params)

    print(f"Response JSON: {response.json()}")

    for listing in listings:
        listing.update({"images": []})
    assert response.status_code == 200
    assert response.json() == {
        "listings": [listing for listing in listings]
    }


def test_get_listings_by_filter_no_results(test_client, mock_db_connection):
    
    mock_connection, mock_cursor = mock_db_connection

    mock_cursor.fetchall.return_value = []
    mock_connection.cursor.return_value = mock_cursor

    with patch('main.connection', mock_connection):

        response = test_client.get("/listings/?listing_status=PENDING&listing_type=SALE&animal_type=Dog")

    print(f"Response JSON: {response.json()}")

    assert response.status_code == 200
    assert response.json() == {
        "listings": []
    }

def test_get_user_listings(test_client, mock_db_connection):
        
    mock_connection, mock_cursor = mock_db_connection

    user_email = "test@example.com"
    listings = [{
        "listing_id": str(uuid4()),
        "owner_email": user_email,
        "animal_type": "Dog",
        "animal_breed": "Labrador",
        "animal_age": 2,
        "animal_name": "Buddy",
        "location": "New York",
        "listing_type": "SALE",
        "animal_price": 1000.00,
        "description": "Description"
    }]  

    fetchall_return_values = [
        [tuple(listing.values()) for listing in listings], 
        None 
    ]

    def mock_fetchall(*args, **kwargs):
        return fetchall_return_values.pop(0)

    mock_cursor.fetchall.side_effect = mock_fetchall

    mock_connection.cursor.return_value = mock_cursor

    with patch('main.connection', mock_connection):

        response = test_client.get("/listings/user/test@example.com?listing_status=PENDING&listing_type=SALE")

    print(f"Response JSON: {response.json()}")

    for listing in listings:
        listing.update({"images": []})
    assert response.status_code == 200
    assert response.json() == {
        "user_listings": [listing for listing in listings]
    }

def test_get_listings_by_id(test_client, mock_db_connection):
    
    mock_connection, mock_cursor = mock_db_connection

    listing_id = str(uuid4())

    listing = {
        "listing_id": listing_id,
        "owner_email": "test@example.com",
        "animal_type": "Dog",
        "animal_breed": "Labrador",
        "animal_age": 2,
        "animal_name": "Buddy",
        "location": "New York",
        "listing_type": "SALE",
        "animal_price": 1000.00,
        "description": "Description"
    }

    mock_cursor.fetchone.return_value = tuple(listing.values())
    mock_cursor.fetchall.return_value = []
    mock_connection.cursor.return_value = mock_cursor

    with patch('main.connection', mock_connection):

        response = test_client.get(f"/listings/id/{listing_id}")

    listing.update({"images": []})
    assert response.status_code == 200
    assert response.json() == {
        "listing": listing
    }
