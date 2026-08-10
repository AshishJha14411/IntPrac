"""Auth request/response contracts."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

MIN_PASSWORD_LENGTH = 12


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)
    display_name: str = Field(min_length=1, max_length=160)

    @field_validator("password")
    @classmethod
    def _not_trivial(cls, value: str) -> str:
        # Length is the lever that actually matters; a composition rule would
        # push people toward "Password1!" and buy nothing.
        if value.strip() != value:
            raise ValueError("Password must not start or end with whitespace.")
        if len(set(value)) < 5:
            raise ValueError("Password is too repetitive.")
        return value


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - an OAuth token type, not a secret
    expires_in: int


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: str
    email_verified: bool
    organization_id: uuid.UUID
    role: str
