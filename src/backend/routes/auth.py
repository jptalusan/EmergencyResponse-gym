"""User auhtentication routes in backend.

This submodule defines the user authentication routes in backend.
It provides endpoints for registering new users and logging in
existing users using token-based authentication.

Functions:
    register(username, password):
        Register a user.
    
    login(response, username, password):
        Log in a user.
"""

from fastapi import APIRouter, Response

from backend.services.auth import hash_password, verify_password, create_token
from db import crud
from db.session import SessionLocal

# Add router with prefix "/auth" for authentication-related routes
router = APIRouter(prefix="/auth")


@router.post("/register")
def register(username: str, password: str):
    """Register a user.

    Creates a new user account if the provided username does not
    already exist in the database.

    Args:
        username (str): Username.
        password (int): Password.

    Returns:
        result (dict): User ID if 'username' is new, error if exists.
    
    Raises:
        ValueError: If 'username'/'password' combination is wrong.
    """
    db = SessionLocal()
    result = {}
    
    try:
        if not crud.get_user(db, username):
            user = crud.create_user(db, username, hash_password(password))
            result = {"id": user.id}
        else:
            result = {"error": "User already exists."}
            raise ValueError("User already exists.")
    finally:
        db.close()
        return result


@router.post("/login")
def login(response: Response, username: str, password: str):
    """Log in a user.

    Authenticates a user by validating the provided credentials.
    If authentication succeeds, an access token is generated and
    stored in an HTTP-only cookie.

    Args:
        response (Response): Request response.
        username (str): Username.
        password (int): Password.

    Returns:
        (dict): Token information (token, access token, token type).
    """
    db = SessionLocal()
    result = {}

    try:
        user = crud.get_user(db, username)

        if not user or not verify_password(password, user.password_hash):
            result = {"error": "Invalid username/password combination."}
            raise ValueError("Invalid username/password combination.")
        else:
            token = create_token(user.id)
            response.set_cookie(
                key="auth_token",
                value=token,
                httponly=True,
                max_age=1 * 60 * 60,
                samesite="lax",
            )
            result = {
                "token": token,
                "access_token": token,
                "token_type": "bearer"
            }
    finally:
        db.close()
        return result
