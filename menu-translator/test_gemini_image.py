from google import genai

client = genai.Client(vertexai=True, project="qwiklabs-gcp-03-4ff0aed0ccd7", location="global")
result = client.models.generate_content(
    model='gemini-3.1-flash-lite-image',
    contents='A delicious, photorealistic plate of Mango Chicken',
)
print(result)
