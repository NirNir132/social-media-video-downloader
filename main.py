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

@app.get("/extract-url")
async def extract_media_url(url: str = Query(...), format: str = Query("best")):
    """
    Extract direct media URL for Gladia transcription API.
    Returns a JSON response with the direct media URL that Gladia can access.
    """
    try:
        # Ensure URL is properly decoded
        url = urllib.parse.unquote(url)
        
        # Extract metadata and get direct media URL
        with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True, 'encoding': 'utf-8'}) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Get the best format URL
            formats = info.get('formats', [])
            if not formats:
                raise HTTPException(status_code=400, detail="No video formats found")
            
            # Find the best format based on the requested format
            if format == "best":
                # Get the best quality video with audio
                best_format = None
                for f in formats:
                    if f.get('vcodec') != 'none' and f.get('acodec') != 'none':  # Has both video and audio
                        if best_format is None or f.get('height', 0) > best_format.get('height', 0):
                            best_format = f
                if not best_format:
                    # Fallback to any format with audio
                    for f in formats:
                        if f.get('acodec') != 'none':
                            best_format = f
                            break
            else:
                # Find specific format
                best_format = None
                for f in formats:
                    if f.get('format_id') == format or f.get('height') == int(format.replace('p', '')):
                        best_format = f
                        break
                if not best_format:
                    best_format = formats[0]  # Fallback to first format
            
            if not best_format:
                raise HTTPException(status_code=400, detail="No suitable format found")
            
            # Get the direct URL
            direct_url = best_format.get('url')
            if not direct_url:
                raise HTTPException(status_code=400, detail="No direct URL found for this format")
            
            # Get video metadata
            title = info.get("title", "video")
            title = sanitize_filename(title)
            duration = info.get("duration", 0)
            file_size = best_format.get('filesize', 0)
            
            return {
                "status": "success",
                "direct_url": direct_url,
                "title": title,
                "duration": duration,
                "file_size": file_size,
                "format": best_format.get('format_id', 'unknown'),
                "resolution": f"{best_format.get('width', 'unknown')}x{best_format.get('height', 'unknown')}",
                "has_audio": best_format.get('acodec') != 'none',
                "has_video": best_format.get('vcodec') != 'none',
                "gladia_compatible": True,
                "message": "Direct media URL extracted successfully for Gladia transcription"
            }
            
    except Exception as e:
        error_message = str(e)
        try:
            error_message.encode('utf-8')
        except UnicodeEncodeError:
            error_message = "Error during URL extraction: Unable to process request due to encoding issues"
        raise HTTPException(status_code=500, detail=f"Error during URL extraction: {error_message}")

@app.get("/gladia-url")
async def get_gladia_url(url: str = Query(...), language: str = Query("auto")):
    """
    Get direct media URL specifically formatted for Gladia transcription API.
    Returns the exact format Gladia expects for audio_url parameter.
    """
    try:
        # Ensure URL is properly decoded
        url = urllib.parse.unquote(url)
        
        # Extract metadata and get direct media URL
        with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True, 'encoding': 'utf-8'}) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Get formats and find the best one with audio
            formats = info.get('formats', [])
            if not formats:
                raise HTTPException(status_code=400, detail="No video formats found")
            
            # Find the best format with audio (required for transcription)
            best_format = None
            for f in formats:
                if f.get('acodec') != 'none':  # Must have audio
                    if best_format is None or f.get('height', 0) > best_format.get('height', 0):
                        best_format = f
            
            if not best_format:
                raise HTTPException(status_code=400, detail="No audio format found - required for transcription")
            
            # Get the direct URL
            direct_url = best_format.get('url')
            if not direct_url:
                raise HTTPException(status_code=400, detail="No direct URL found")
            
            # Check if URL is publicly accessible (no authentication required)
            if '?' in direct_url and ('signature=' in direct_url or 'token=' in direct_url):
                # URL might have temporary authentication - warn user
                warning = "URL contains authentication parameters that may expire"
            else:
                warning = None
            
            # Get video metadata
            title = info.get("title", "video")
            duration = info.get("duration", 0)
            file_size = best_format.get('filesize', 0)
            
            # Check Gladia limits
            duration_minutes = duration / 60 if duration else 0
            file_size_mb = file_size / (1024 * 1024) if file_size else 0
            
            gladia_compatible = True
            compatibility_issues = []
            
            if duration_minutes > 135:
                gladia_compatible = False
                compatibility_issues.append(f"Duration ({duration_minutes:.1f} min) exceeds Gladia limit (135 min)")
            
            if file_size_mb > 1000:
                gladia_compatible = False
                compatibility_issues.append(f"File size ({file_size_mb:.1f} MB) exceeds Gladia limit (1000 MB)")
            
            return {
                "audio_url": direct_url,  # This is what Gladia expects
                "title": title,
                "duration_seconds": duration,
                "duration_minutes": round(duration_minutes, 2),
                "file_size_bytes": file_size,
                "file_size_mb": round(file_size_mb, 2),
                "has_audio": True,
                "gladia_compatible": gladia_compatible,
                "compatibility_issues": compatibility_issues,
                "warning": warning,
                "suggested_language": language,
                "gladia_request_format": {
                    "audio_url": direct_url,
                    "language": language
                }
            }
            
    except Exception as e:
        error_message = str(e)
        try:
            error_message.encode('utf-8')
        except UnicodeEncodeError:
            error_message = "Error during URL extraction: Unable to process request due to encoding issues"
        raise HTTPException(status_code=500, detail=f"Error during URL extraction: {error_message}")

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
            'no_warnings': True,
            'extract_flat': False,
            'writeinfojson': False,
            'writesubtitles': False,
            'writeautomaticsub': False,
        }

        # Download the video using yt-dlp Python API
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.download([url])

        # Find actual downloaded file
        actual_file_path = None
        try:
            for f in os.listdir("/tmp"):
                if f.startswith(uid):
                    actual_file_path = os.path.join("/tmp", f)
                    break
        except FileNotFoundError:
            # /tmp directory might not exist, try current directory
            for f in os.listdir("."):
                if f.startswith(uid):
                    actual_file_path = os.path.join(".", f)
                    break

        if not actual_file_path or not os.path.exists(actual_file_path):
            # List available files for debugging
            try:
                available_files = os.listdir("/tmp")
            except FileNotFoundError:
                available_files = os.listdir(".")
            raise HTTPException(
                status_code=500, 
                detail=f"Download failed or file not found. Looking for files starting with '{uid}'. Available files: {available_files[:10]}"
            )

        # Stream file
        def iterfile():
            try:
                with open(actual_file_path, "rb") as f:
                    yield from f
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")
            finally:
                # Clean up the file
                try:
                    os.unlink(actual_file_path)
                except:
                    pass  # Ignore cleanup errors

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
    return {
        "message": "Welcome to the Social Media Video Downloader API",
        "endpoints": {
            "/gladia-url": "Get direct media URL for Gladia transcription API (RECOMMENDED for Gladia integration)",
            "/extract-url": "Extract direct media URL with detailed metadata",
            "/download": "Download and stream video file directly",
            "/debug": "System debug information",
            "/test-download": "Test yt-dlp functionality"
        },
        "gladia_integration": {
            "endpoint": "/gladia-url?url=<video_url>&language=<language_code>",
            "example": "/gladia-url?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ&language=he",
            "response_format": {
                "audio_url": "Direct URL for Gladia API",
                "gladia_request_format": "Ready-to-use JSON for Gladia POST request"
            }
        },
        "supported_platforms": ["YouTube", "TikTok", "Facebook", "Instagram", "Twitter", "and more"],
        "utf8_support": "Full UTF-8 support for international content including עברית"
    }

@app.get("/debug")
async def debug_info():
    """Debug endpoint to check system status"""
    import tempfile
    import platform
    
    return {
        "platform": platform.system(),
        "temp_dir": tempfile.gettempdir(),
        "current_dir": os.getcwd(),
        "temp_dir_exists": os.path.exists("/tmp"),
        "temp_dir_writable": os.access("/tmp", os.W_OK) if os.path.exists("/tmp") else False,
        "current_dir_writable": os.access(".", os.W_OK)
    }

@app.get("/test-download")
async def test_download():
    """Test endpoint to verify download functionality with a simple test"""
    try:
        # Test with a simple YouTube video
        test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        
        # Extract metadata only
        with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True, 'encoding': 'utf-8'}) as ydl:
            info = ydl.extract_info(test_url, download=False)
            
        return {
            "status": "success",
            "title": info.get("title", "No title"),
            "duration": info.get("duration", 0),
            "formats_available": len(info.get("formats", [])),
            "message": "yt-dlp is working correctly"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "message": "yt-dlp test failed"
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)