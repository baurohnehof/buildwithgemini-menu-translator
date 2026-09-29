import requests
import json
import base64

# Base64 encode the image
with open("/config/.gemini/antigravity/brain/dc186dc3-1f64-4366-be9a-ea8ec36e7d52/.user_uploaded/media_1790681340015.jpg", "rb") as image_file:
    encoded_string = base64.b64encode(image_file.read()).decode('utf-8')

# The adk web expects multipart/form-data for the image to upload, 
# but it's easier to just test the agent via `agents-cli run` directly 
# wait, agents-cli run doesn't take images.
