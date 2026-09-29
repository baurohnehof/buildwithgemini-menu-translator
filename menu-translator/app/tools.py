import datetime
import logging
import os
import uuid
import requests
from google import genai
from google.cloud import storage
from google.cloud import firestore

logger = logging.getLogger(__name__)

PROJECT_ID = "qwiklabs-gcp-03-4ff0aed0ccd7"
BUCKET_NAME = "qwiklabs-gcp-03-4ff0aed0ccd7-menu-images"


def _get_firestore_client() -> firestore.Client:
    """Returns a Firestore client with the hardcoded GCP project ID."""
    return firestore.Client(project=PROJECT_ID)


def _get_storage_client() -> storage.Client:
    """Returns a Cloud Storage client with the hardcoded GCP project ID."""
    return storage.Client(project=PROJECT_ID)


def save_uploaded_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """Saves an image uploaded by the user to the configured Google Cloud Storage bucket.

    Args:
        image_bytes: Raw bytes of the uploaded image.
        mime_type: MIME type of the image (e.g., 'image/jpeg', 'image/png').

    Returns:
        The public HTTPS URL of the uploaded image in Cloud Storage.
    """
    ext = "jpg"
    if "png" in mime_type.lower():
        ext = "png"
    elif "webp" in mime_type.lower():
        ext = "webp"

    blob_name = f"uploaded_images/{uuid.uuid4()}.{ext}"
    try:
        storage_client = _get_storage_client()
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{blob_name}"
        logger.info(f"Saved uploaded image to Cloud Storage: {public_url}")
        return public_url
    except Exception as e:
        logger.error(f"Failed to upload image to GCS: {e}")
        return ""


def save_chat_history(
    session_id: str,
    user_text: str,
    uploaded_images: list[str] | None = None,
    agent_text: str = "",
    generated_images: list[str] | None = None,
    user_id: str = "",
) -> None:
    """Saves a conversation turn to the Firestore chat_history and chat_sessions collections.

    Args:
        session_id: ID of the chat session.
        user_text: The user's input message text.
        uploaded_images: List of public GCS URLs for images uploaded by the user.
        agent_text: The agent's response text / payload.
        generated_images: List of public GCS URLs for images generated during the turn.
        user_id: Optional ID of the user.
    """
    try:
        db = _get_firestore_client()
        timestamp = datetime.datetime.now(datetime.timezone.utc)
        safe_session_id = session_id or "default_session"

        # 1. Save flat record in chat_history collection
        turn_data = {
            "session_id": safe_session_id,
            "user_id": user_id or "anonymous",
            "timestamp": timestamp,
            "user_message": user_text or "",
            "uploaded_images": uploaded_images or [],
            "agent_response": agent_text or "",
            "generated_images": generated_images or [],
        }
        db.collection("chat_history").add(turn_data)

        # 2. Also record in chat_sessions/{session_id}/messages for structured session retrieval
        session_ref = db.collection("chat_sessions").document(safe_session_id)
        session_ref.set({"last_updated": timestamp, "user_id": user_id or "anonymous"}, merge=True)
        
        messages_col = session_ref.collection("messages")
        messages_col.add({
            "role": "user",
            "content": user_text or "",
            "images": uploaded_images or [],
            "timestamp": timestamp,
        })
        messages_col.add({
            "role": "model",
            "content": agent_text or "",
            "images": generated_images or [],
            "timestamp": timestamp,
        })
        logger.info(f"Saved chat turn to Firestore for session: {safe_session_id}")
    except Exception as e:
        logger.error(f"Failed to save chat history to Firestore: {e}")


def search_google_custom_search(dish_name: str) -> str | None:
    """Attempts to find a photo of the dish using Google Custom Search API if credentials exist."""
    api_key = os.getenv("GOOGLE_SEARCH_API_KEY") or os.getenv("GOOGLE_API_KEY")
    cx = os.getenv("GOOGLE_CSE_ID") or os.getenv("GOOGLE_SEARCH_CX")
    if not api_key or not cx:
        return None

    try:
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": api_key,
            "cx": cx,
            "q": f"{dish_name} food dish",
            "searchType": "image",
            "num": 1,
            "safe": "active",
        }
        res = requests.get(url, params=params, timeout=5)
        if res.status_code == 200:
            items = res.json().get("items", [])
            if items and "link" in items[0]:
                return items[0]["link"]
    except Exception as e:
        logger.warning(f"Google Custom Search query failed for {dish_name}: {e}")
    return None


def generate_dish_image_gemini(dish_name: str) -> str:
    """Generates a photo of a dish using Gemini 3.1 Flash Lite Image and uploads it to GCS."""
    project_id = PROJECT_ID
    bucket_name = BUCKET_NAME
    
    try:
        client = genai.Client(vertexai=True, project=project_id, location="global")
        result = client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=f"A delicious, appetizing, high-resolution authentic restaurant plate of {dish_name}",
        )
        
        if not result.candidates or not result.candidates[0].content.parts:
            return ""
            
        image_part = result.candidates[0].content.parts[0]
        if not image_part.inline_data or not image_part.inline_data.data:
            return ""
            
        image_bytes = image_part.inline_data.data
        
        storage_client = _get_storage_client()
        bucket = storage_client.bucket(bucket_name)
        
        blob_name = f"dish_images/{uuid.uuid4()}.jpg"
        blob = bucket.blob(blob_name)
        blob.upload_from_string(image_bytes, content_type="image/jpeg")
        
        public_url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}"
        return public_url
    except Exception as e:
        logger.error(f"Gemini image generation failed for {dish_name}: {e}")
        return ""


def get_dish_image(dish_name: str) -> str:
    """Retrieves an authentic image for a dish.
    
    First tries Google Custom Search (if configured with GOOGLE_SEARCH_API_KEY & GOOGLE_CSE_ID).
    Otherwise, generates a high-quality, photorealistic image of the dish using Gemini 3.1 Flash Lite Image.
    
    Args:
        dish_name: The name of the dish.
        
    Returns:
        A string containing a public image URL or a message if none found.
    """
    logger.info(f"Retrieving image for dish: '{dish_name}'")

    # 1. Try Google Custom Search (if configured)
    cse_url = search_google_custom_search(dish_name)
    if cse_url:
        logger.info(f"Found image via Google Custom Search: {cse_url}")
        return cse_url

    # 2. Generate authentic dish image using Gemini
    logger.info(f"Generating image with Gemini 3.1 Flash Lite Image for '{dish_name}'...")
    gemini_url = generate_dish_image_gemini(dish_name)
    if gemini_url:
        logger.info(f"Successfully generated dish image with Gemini: {gemini_url}")
        return gemini_url

    return "No image found."
