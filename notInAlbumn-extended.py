import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/photoslibrary',
    'https://www.googleapis.com/auth/photoslibrary.sharing'
]

# Authenticate and get Google Photos service
def authenticate_google_photos():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    # Explicitly set the discoveryServiceUrl for Google Photos API
    service = build(
        'photoslibrary',
        'v1',
        credentials=creds,
        discoveryServiceUrl='https://photoslibrary.googleapis.com/$discovery/rest?version=v1'
    )
    return service

def get_all_photos(service):
    """Retrieve all photos in the user's library using pagination."""
    all_photos = []
    page_token = None

    # Use a loop to go through all media items
    while True:
        # List media items with mediaType PHOTO to filter out non-photo items
        results = service.mediaItems().list(
            pageSize=100, 
            pageToken=page_token, 
            fields="mediaItems(id,filename,mimeType),nextPageToken"
        ).execute()

        # Check for missing attributes and filter photos only
        media_items = results.get('mediaItems', [])
        photos = [item for item in media_items if 'mimeType' in item and item['mimeType'].startswith("image/") and 'filename' in item]

        # Add photos to the main list
        all_photos.extend(photos)

        # Check for the next page of results
        page_token = results.get('nextPageToken')
        if not page_token:
            break

    return all_photos

def get_album_item_ids(service):
    """Retrieve the IDs of all media items in every album."""
    album_item_ids = set()
    page_token = None

    # Retrieve all albums in the library
    while True:
        albums = service.albums().list(pageSize=50, pageToken=page_token).execute().get('albums', [])
        
        # For each album, collect media item IDs
        for album in albums:
            album_id = album['id']
            album_page_token = None

            while True:
                # Use the search method to get media items in the album
                album_items = service.mediaItems().search(body={
                    "albumId": album_id,
                    "pageSize": 50,
                    "pageToken": album_page_token
                }).execute()
                items = album_items.get('mediaItems', [])
                album_item_ids.update(item['id'] for item in items if 'id' in item)
                
                # Check for next page within the album
                album_page_token = album_items.get('nextPageToken')
                if not album_page_token:
                    break

        # Check for next page of albums
        page_token = service.albums().list(pageSize=50, pageToken=page_token).execute().get('nextPageToken')
        if not page_token:
            break

    return album_item_ids

def get_items_no_album(service, batch_size=10):
    """List up to 'batch_size' photos not in any album."""
    # Retrieve all photo media items in the user's library
    all_photos = get_all_photos(service)

    # Retrieve all item IDs in existing albums
    album_item_ids = get_album_item_ids(service)

    # Filter photos that are not in any album
    no_album_photos = [photo for photo in all_photos if photo['id'] not in album_item_ids]

    # Return only the specified batch size of photos not in any album
    return no_album_photos[:batch_size]


def get_and_move_items_no_album(service, album_id, batch_size=10):
    """List up to 'batch_size' photos not in any album and move them to the specified album."""
    # Retrieve all photo media items in the user's library
    all_photos = get_all_photos(service)

    # Retrieve all item IDs in existing albums
    album_item_ids = get_album_item_ids(service)

    # Filter photos that are not in any album
    no_album_photos = [photo for photo in all_photos if photo['id'] not in album_item_ids]

    # Get the batch of photos to move
    photos_to_move = no_album_photos[:batch_size]

    print(f"Listing up to {batch_size} photos that are not in any album:\n")
    for photo in photos_to_move:
        print(f"Filename: {photo['filename']} | ID: {photo['id']}")

    # Move photos to the specified album using its album_id
    if photos_to_move:
        # Collect media item IDs and validate them
        media_item_ids = [photo['id'] for photo in photos_to_move]

        # Check validity of each media item ID
        valid_ids = []
        for media_id in media_item_ids:
            try:
                # Check if the media item is accessible and valid
                media_item = service.mediaItems().get(mediaItemId=media_id).execute()
                if media_item:
                    print(f"Valid Media Item ID: {media_id} | Filename: {media_item.get('filename', 'Unknown')}")
                    valid_ids.append(media_id)
                else:
                    print(f"Media item not found or invalid: {media_id}")
            except Exception as e:
                print(f"Invalid or inaccessible media item ID: {media_id}, Error: {e}")

        if valid_ids:
            # Move each media item one by one to pinpoint issues
            for valid_id in valid_ids:
                try:
                    service.albums().batchAddMediaItems(albumId=album_id, body={"mediaItemIds": [valid_id]}).execute()
                    print(f"Successfully moved item with ID: {valid_id} to album with ID: {album_id}")
                except Exception as e:
                    print(f"Error adding item with ID: {valid_id} to album: {e}")
        else:
            print("No valid media item IDs found to add to the album.")
    else:
        print("No photos without an album were found.")

    return photos_to_move



def create_shareable_album(service, album_title):
    """Create a shareable album and enable write access."""
    # Step 1: Create the album
    album_body = {
        "album": {
            "title": album_title
        }
    }
    
    created_album = service.albums().create(body=album_body).execute()
    album_id = created_album['id']

    # Step 2: Share the album to make it accessible and writable
    share_body = {
        "sharedAlbumOptions": {
            "isCollaborative": True,
            "isCommentable": True
        }
    }

    shared_album = service.albums().share(albumId=album_id, body=share_body).execute()
    shareable_url = shared_album['shareInfo']['shareableUrl']
    print(f"Created shareable album '{album_title}' with ID: {album_id}")
    return album_id, shareable_url


def find_album(service, album_name):
    next_page_token = None
    while True:
        response = service.albums().list(pageSize=50, excludeNonAppCreatedData=False, pageToken=next_page_token).execute()
        for album in response.get('albums', []):
            if album['title'] == album_name:
                return album
        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break
    return None

def get_album_by_id(service, album_id):
    try:
        album = service.albums().get(albumId=album_id).execute()
        return album
    except Exception as e:
        print(f"Error fetching album: {e}")
        return None



# Usage
if __name__ == '__main__':
    service = authenticate_google_photos()

    # Retrieve the first batch of 10 photos not in any album and print their filenames and IDs
    # photos_not_in_album = get_items_no_album(service, batch_size=10)
    # print(f"Listing up to 10 photos that are not in any album:\n")
    # for photo in photos_not_in_album:
    #     print(f"Filename: {photo['filename']} | ID: {photo['id']}")
    # create_shareable_album(service, album_name)

    # album id of '1-Non-Albumn-API' - created through API
    album_id = 'AFibLfnite48_8Ub0_rw6p4srku_YNOLQQ9pw9ADWM9AdzsnwKB-jDN_3p_hhdEL86a8UYilbvg3'
    get_and_move_items_no_album(service, album_id)