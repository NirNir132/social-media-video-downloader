import os
import uuid
import urllib.parse
import re
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
from dotenv import load_dotenv

app = FastAPI()

# Load environment variables from .env file
load_dotenv()

def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to be safe for filesystem and HTTP headers.
    Preserves UTF-8 characters while removing/replacing unsafe characters.
    """
    # Remove or replace characters that are problematic for filenames
    # Keep UTF-8 characters but replace path separators and other unsafe chars
    filename = re.sub(r'[<>:"/\\|?*]', '-', filename)
    # Remove control characters
    filename = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', filename)
    # Remove leading/trailing whitespace and dots
    filename = filename.strip(' .')
    # Ensure filename is not empty
    if not filename:
        filename = "video"
    # Limit length to avoid filesystem issues
    if len(filename) > 200:
        filename = filename[:200]
    return filename

# CORS configuration
app.add_middleware(CORSMiddleware,
    allow_origins=[os.getenv("ALLOWED_ORIGIN")],  # Adjust this to your needs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/download")
async def download_video(url: str = Query(...), format: str = Query("best")):
    try:
        # Ensure URL is properly decoded
        url = urllib.parse.unquote(url)
        
        # Extract metadata
        with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True, 'encoding': 'utf-8'}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "video")
            # Properly sanitize the title while preserving UTF-8 characters
            title = sanitize_filename(title)
            extension = "mp4"  # fallback extension
            filename = f"{title}.{extension}"

        # Create a unique output template
        uid = uuid.uuid4().hex[:8]
        output_template = f"/tmp/{uid}.%(ext)s"

        ydl_opts = {
            'format': format,
            'outtmpl': output_template,
            'quiet': True,
            'merge_output_format': 'mp4',
            'encoding': 'utf-8',  # Ensure UTF-8 encoding for all text operations
        }

        # Download the video using yt-dlp Python API
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.download([url])

        # Find actual downloaded file
        actual_file_path = None
        for f in os.listdir("/tmp"):
            if f.startswith(uid):
                actual_file_path = os.path.join("/tmp", f)
                break

        if not actual_file_path or not os.path.exists(actual_file_path):
            raise HTTPException(status_code=500, detail="Download failed or file not found.")

        # Stream file
        def iterfile():
            with open(actual_file_path, "rb") as f:
                yield from f
            os.unlink(actual_file_path)  # clean up after stream

        # Properly encode filename for Content-Disposition header
        # Use RFC 5987 encoding for UTF-8 filenames
        encoded_filename = urllib.parse.quote(filename.encode('utf-8'))
        content_disposition = f'attachment; filename*=UTF-8\'\'{encoded_filename}'
        
        return StreamingResponse(
            iterfile(),
            media_type="application/octet-stream",
            headers={"Content-Disposition": content_disposition}
        )

    except Exception as e:
        # Ensure error message is properly encoded
        error_message = str(e)
        # Handle potential encoding issues in error messages
        try:
            # Try to encode as UTF-8 to catch any encoding issues
            error_message.encode('utf-8')
        except UnicodeEncodeError:
            # If there are encoding issues, use a safe fallback
            error_message = "Error during download: Unable to process request due to encoding issues"
        raise HTTPException(status_code=500, detail=f"Error during download: {error_message}")

@app.get("/")
async def root():
    return {"message": "Welcome to the Social Media Video Downloader API. Use /download?url=<video_url>&format=<video_format> to download videos."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)