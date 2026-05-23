"""Bob Manager — Auth API routes."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies import create_access_token
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenRequest(BaseModel):
    """Login request with shared secret."""
    secret: str


class TokenResponse(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"


@router.post("/token", response_model=TokenResponse)
async def get_token(request: TokenRequest) -> TokenResponse:
    """Exchange a shared secret for a JWT token.

    For production, replace with proper user auth.
    """
    if request.secret != settings.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid secret",
        )

    token = create_access_token({"sub": "admin", "role": "admin"})
    return TokenResponse(access_token=token)
