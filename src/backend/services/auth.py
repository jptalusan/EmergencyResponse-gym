"""Services for user authentication routes.

This submodule defines the service functions for authentication routes.

Functions:
    hash_password(password):
        Hash a password using bcrypt with a randomly generated salt.

    verify_password(password, password_hash):
        Verify a password against a bcrypt hash.

    create_token(user_id):
        Create a JWT access token for a user.

    get_current_user(request, credentials):
        Extract and verify user ID from a bearer token.

Attributes:
    bearer_scheme (HTTPBearer): HTTP Bearer scheme for API routes.
        'auto_error=False' allows manual handling of missing or invalid tokens.
"""

from typing import Optional

from datetime import datetime, timedelta, timezone
import bcrypt
from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from backend.config import settings

bearer_scheme = HTTPBearer(auto_error=False)


def _normalize_password(secret: str | bytes) -> bytes:
    """Normalize a password string for secure storage or hashing.

    This function ensures the password is a UTF-8 encoded byte string,
    truncates it to a maximum of 72 bytes (suitable for bcrypt), and
    raises a 'TypeError' if the input is not a string or bytes.

    Args:
        secret (str or bytes): The password to normalize.
            If 'bytes' are provided, they will be decoded as UTF-8,
            ignoring invalid bytes.

    Returns:
        (bytes): The UTF-8 encoded and truncated password.

    Raises:
        TypeError: If 'secret' is not a string or bytes.
    """
    if isinstance(secret, bytes):
        secret = secret.decode("utf-8", errors="ignore")
    if not isinstance(secret, str):
        raise TypeError("Password must be a string")

    encoded = secret.encode("utf-8")
    if len(encoded) > 72:
        encoded = encoded[:72]
    return encoded


def hash_password(password: str | bytes):
    """Hash a password using bcrypt with a randomly generated salt.

    This function normalizes the password using '_normalize_password', 
    then hashes it using bcrypt and returns the hash as a UTF-8 string.

    Args:
        password (str or bytes): The password to hash.

    Returns:
        (str): The bcrypt hash of the password encoded as a UTF-8 string.

    Raises:
        TypeError: If 'password' is not a string or bytes.
            (raised by '_normalize_password')
    """
    password = _normalize_password(password)
    return bcrypt.hashpw(password, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str | bytes, password_hash: str):
    """Verify a password against a bcrypt hash.

    This function normalizes the password using '_normalize_password',
    then checks it against the bcrypt hash encoded as a UTF-8 string.

    Args:
        password (str or bytes): The password to verify.
        password_hash (str): The bcrypt hash to verify against.

    Returns:
        (bool): 'True' if the password matches the hash, 'False' otherwise.

    Raises:
        TypeError: If 'password' is not a string or bytes.
            (raised by '_normalize_password')
    """
    password = _normalize_password(password)
    return bcrypt.checkpw(password, password_hash.encode("utf-8"))


def create_token(user_id: int | str):
    """Create a JWT access token for a user.

    This function generates a JSON Web Token (JWT) containing the user's ID as
    the subject ('sub') and an expiration time of 1 hour from its creation. The
    token is signed using the HS256 algorithm with the application's secret key.

    Args:
        user_id (int or str): The unique identifier of the user for whom
            the token is created.

    Returns:
        (str): The encoded JWT as a string.
    """
    return jwt.encode(
        {
            "sub": str(user_id),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1)
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )


def _extract_token(authorization: Optional[str]) -> Optional[str]:
    """Extract a bearer token from an HTTP Authorization header.

    This function parses the provided 'Authorization' header string and returns
    the token if the scheme is "Bearer". Leading and trailing whitespace are
    removed. If the header is empty, missing, or uses a different scheme, 'None'
    is returned.

    Args:
        authorization (Optional[str]): The value of the HTTP 'Authorization'
            header, or 'None'.

    Returns:
        Optional[str]: The extracted token string if a valid Bearer token
        is present, otherwise 'None'.
    """
    if not authorization:
        return None

    authorization = authorization.strip()
    if not authorization:
        return None

    scheme, _, credentials = authorization.partition(" ")
    if credentials:
        if scheme.lower() != "bearer":
            return None
        return credentials.strip() or None

    return authorization


def _decode_user_id(token: str) -> int:
    """Decode a JWT and extract the user ID from its payload.

    This function decodes a JSON Web Token (JWT) using the application's
    secret key and the HS256 algorithm. It retrieves the 'sub' (subject)
    field from the payload and converts it to an integer. Raises an error
    if the subject is missing.

    Args:
        token (str): A JWT encoded as a string.

    Returns:
        int: The user ID extracted from the token's subject ('sub') field.

    Raises:
        ValueError: If the token payload does not contain a 'sub' field.
        jwt.PyJWTError: If the token is invalid, expired, or cannot be decoded.
    """
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    subject = payload.get("sub")
    if subject is None:
        raise ValueError("Token missing subject")
    return int(subject)


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> int:
    """Retrieve and verify the current user's ID from a bearer token.

    This function tries to extract a JWT from the HTTP 'Authorization' header,
    the security credentials, or an 'auth_token' cookie. Then it decodes the
    token to obtain the user's ID. If no token is provided, or if the token is
    invalid, it raises an HTTP 401 Unauthorized error.

    Args:
        request (Request): The incoming HTTP request.
        credentials (Optional[HTTPAuthorizationCredentials], optional): 
            Security credentials from FastAPI's dependency injection,
            typically obtained from a bearer token. Defaults to
            'Security(bearer_scheme)'.

    Returns:
        int: The user ID extracted from the JWT.

    Raises:
        HTTPException: If no token is provided or if the token is invalid.
    """    
    token = (
        credentials.credentials
        if credentials
        else _extract_token(request.headers.get("Authorization"))
        or request.cookies.get("auth_token")
    )

    if not token:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail = "Missing authorization header or auth cookie",
            headers = {"WWW-Authenticate": "Bearer"},
        )

    try:
        return _decode_user_id(token)
    except (JWTError, TypeError, ValueError):
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail = "Invalid token",
            headers = {"WWW-Authenticate": "Bearer"},
        )
