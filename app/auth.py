import secrets

from fastapi import Depends
from fastapi import HTTPException
from fastapi import status
from fastapi.security import HTTPBasic
from fastapi.security import HTTPBasicCredentials

from app.config import Settings
from app.config import get_settings


security = HTTPBasic(auto_error=False)


def require_admin(
    credentials: HTTPBasicCredentials | None = Depends(security),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.admin_password:
        return
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required.",
            headers={"WWW-Authenticate": "Basic"},
        )
    if credentials.username != "admin" or not secrets.compare_digest(
        credentials.password,
        settings.admin_password,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )
