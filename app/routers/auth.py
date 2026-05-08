from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Header, Query
import json
from google.oauth2 import id_token
from google.auth.transport import requests
from jose import jwt, JWTError
from datetime import datetime, timedelta
from asyncpg import Connection
from app.database import get_db
from app.config import settings
from pydantic import BaseModel
from typing import Optional, Annotated

router = APIRouter(tags=["Auth"])

class TokenRequest(BaseModel):
    token: str

class UserOut(BaseModel):
    id: int
    email: str
    name: Optional[str]
    picture: Optional[str]

async def get_token(
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query()] = None
):
    if authorization and authorization.startswith("Bearer "):
        return authorization.split(" ")[1]
    if token:
        return token
    raise HTTPException(status_code=401, detail="Missing or invalid token")

async def get_current_user(token: str, db: Connection = Depends(get_db)):
    """Dependency that returns the current authenticated user."""
    # Local development bypass is opt-in and must use a caller-provided token.
    if settings.dev_mode and settings.dev_auth_token and token == settings.dev_auth_token:
        # Ensure dev user exists in DB
        user = await db.fetchrow(
            """INSERT INTO users (google_id, email, name, picture) VALUES ($1, $2, $3, $4)
               ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name, picture = EXCLUDED.picture, google_id = EXCLUDED.google_id
               RETURNING id, email, name, picture""",
            "dev_google_id", "dev@example.com", "Developer User", ""
        )
        return dict(user)

    try:
        # Normal flow: decode and verify JWT
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
            
        # Optional: handle dev email even in JWT if it escaped here
        if settings.dev_mode and email == "dev@example.com":
             return {"id": 1, "email": "dev@example.com", "name": "Developer User", "picture": ""}
             
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = await db.fetchrow("SELECT id, email, name, picture FROM users WHERE email = $1", email)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return dict(user)

@router.post("/auth/google")
async def google_auth(req: TokenRequest, db: Connection = Depends(get_db)):
    """Endpoint to handle Google OAuth or Developer bypass."""
    
    # Local development bypass is opt-in and must use a caller-provided token.
    if settings.dev_mode and settings.dev_auth_token and req.token == settings.dev_auth_token:
        # Ensure dev user exists in DB
        user = await db.fetchrow(
            """INSERT INTO users (google_id, email, name, picture) VALUES ($1, $2, $3, $4)
               ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name
               RETURNING id, email, name, picture""",
            "dev_google_id", "dev@example.com", "Developer User", ""
        )
        return {
            "access_token": settings.dev_auth_token,
            "token_type": "bearer",
            "user": dict(user)
        }

    try:
        # Standard Google verification
        idinfo = id_token.verify_oauth2_token(req.token, requests.Request(), settings.google_client_id)
        google_id = idinfo['sub']
        email = idinfo['email']
        name = idinfo.get('name', '')
        picture = idinfo.get('picture', '')

        # Upsert user in database
        user = await db.fetchrow(
            """INSERT INTO users (google_id, email, name, picture) VALUES ($1, $2, $3, $4)
               ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name, picture = EXCLUDED.picture, google_id = EXCLUDED.google_id
               RETURNING id, email, name, picture""",
            google_id, email, name, picture
        )

        # Generate local JWT
        access_token = jwt.encode({"sub": email}, settings.secret_key, algorithm="HS256")
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": dict(user)
        }
    except Exception as e:
        print(f"[Auth] ❌ Google verification failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

from app.utils import json_to_netscape

@router.post("/auth/cookies")
async def upload_cookies(
    file: UploadFile = File(...),
    db: Connection = Depends(get_db),
    token: str = Depends(get_token)
):
    user = await get_current_user(token, db)
    content = await file.read()
    try:
        raw_text = content.decode("utf-8").strip()
        
        # Robust JSON detection
        cookies_text = raw_text
        if '[' in raw_text and ']' in raw_text:
            # Try to find the actual JSON bracket range
            start = raw_text.find('[')
            end = raw_text.rfind(']') + 1
            json_blob = raw_text[start:end]
            try:
                cookies_json = json.loads(json_blob)
                cookies_text = json_to_netscape(cookies_json)
                print("[Auth] Successfully converted JSON cookies to Netscape format.")
            except (json.JSONDecodeError, ValueError, KeyError):
                # Not valid JSON after all, keep as raw text
                pass
            
        await db.execute("UPDATE users SET youtube_cookies = $1 WHERE id = $2", cookies_text, user['id'])
        return {"status": "success", "message": "Cookies uploaded and converted successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid file format: {str(e)}")
