# import whisper

# model = whisper.load_model("turbo")
# result = model.transcribe("audio.mp3")
# print(result["text"])
import requests

with open("temp/uploads/Tilly's Lost Balloon.zip", "rb") as f:
    r = requests.post(
        "http://localhost:8000/api/v1/upload",
        files=[("files", ("Tilly's Lost Balloon.zip", f, "application/zip"))],
        data={"source_language": "en", "target_languages": "zh"}
    )
    print(r.status_code, r.text)

files = [
    ("files", ("Tilly's Lost Balloon.zip", open("temp/uploads/Tilly's Lost Balloon.zip", "rb"), "application/zip")),
]
data = {"source_language": "en", "target_languages": "zh"}

r = requests.post(
    "http://localhost:8000/api/v1/upload",
    files=files,
    data=data
)
print(r.status_code, r.text)