# My agent: Menu Translator
One-liner: A conversational agent that helps travelers analyze restaurant menus, understand unfamiliar dishes, dietary details (vegetarian/vegan), and preview photos with all knowledge extracted directly via LLM.

Architecture & Storage:
- LLM Reasoning: All menu translation, dish extraction, descriptions, and dietary classifications ([Non-Vegetarian], [Vegetarian], [Vegan]) are derived directly from the multimodal Gemini model calls.
- Tools: `get_dish_image` (generates dish image visuals using Gemini and uploads to Google Cloud Storage)
- Google Cloud Storage (`gs://qwiklabs-gcp-03-4ff0aed0ccd7-menu-images`):
  - `dish_images/`: Generated dish images
  - `uploaded_images/`: Uploaded user images (e.g., menu photos)
- Firebase / Firestore (`PROJECT_ID = "qwiklabs-gcp-03-4ff0aed0ccd7"`):
  - `chat_history`: Stores all conversation turns with user messages, uploaded images, agent responses, and generated images
  - `chat_sessions`: Stores session index and structured messages per session
