from google import genai

client = genai.Client(vertexai=True, project="qwiklabs-gcp-03-4ff0aed0ccd7", location="us-central1")
result = client.models.generate_images(
    model='imagen-3.0-generate-001',
    prompt='A delicious Pad Thai, photorealistic',
    config=dict(
        number_of_images=1,
        output_mime_type="image/jpeg",
    )
)
for generated_image in result.generated_images:
  print("Got image bytes")
