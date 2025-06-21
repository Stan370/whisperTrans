# import whisper

# model = whisper.load_model("turbo")
# result = model.transcribe("audio.mp3")
# print(result["text"])
import requests
# multipart/form-data init files
files = [
    ("files", ("1.mp3", open("temp/1.mp3", "rb"), "audio/mpeg")),
    ("files", ("2.mp3", open("temp/uploads/2.mp3", "rb"), "audio/mpeg")),
    ("files", ("3.mp3", open("temp/uploads/3.mp3", "rb"), "audio/mpeg")),
    ("files", ("text.json", open("temp/uploads/text.json", "rb"), "application/json")),
]
data = {"source_language": "en", "target_languages": "zh"}

r = requests.post(
    "http://localhost:8000/api/v1/upload",
    files=files,
    data=data
)
print(r.status_code, r.text)