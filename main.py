from flask import Flask, request, jsonify
import os, io, time
import tempfile
import subprocess
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")

def get_drive_service():
    creds = Credentials(
        None,
        refresh_token=REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET
    )
    creds.refresh(Request())
    return build("drive", "v3", credentials=creds)

@app.route("/split", methods=["POST"])
def split_audio():
    file_id = request.json.get("file_id")
    service = get_drive_service()

    # Download audio
    request_drive = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request_drive)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    fh.seek(0)

    # Save to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_file:
        tmp_file.write(fh.read())
        tmp_path = tmp_file.name

    # Split using ffmpeg
    chunk_paths = []
    out_dir = tempfile.mkdtemp()
    base = os.path.splitext(os.path.basename(tmp_path))[0]

    cmd = [
        "ffmpeg", "-i", tmp_path, "-f", "segment",
        "-segment_time", "900",  # 15 minutes
        "-c", "copy", f"{out_dir}/{base}_%03d.mp3"
    ]
    subprocess.run(cmd, check=True)

    # Upload each chunk
    chunk_urls = []
    for fname in sorted(os.listdir(out_dir)):
        fpath = os.path.join(out_dir, fname)
        file_metadata = {
            "name": fname,
            "parents": [GDRIVE_FOLDER_ID],
        }
        media = MediaFileUpload(fpath, mimetype="audio/mpeg")
        uploaded = service.files().create(body=file_metadata, media_body=media, fields="id").execute()

        # Make public
        service.permissions().create(
            fileId=uploaded['id'],
            body={"type": "anyone", "role": "reader"}
        ).execute()

        url = f"https://drive.google.com/uc?id={uploaded['id']}"
        chunk_urls.append(url)

    return jsonify({"chunks": chunk_urls})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
