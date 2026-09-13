from pydantic import BaseModel


class LoginRequest(BaseModel):
    identifier: str  # employee_code or email
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserProfile(BaseModel):
    id: str
    employee_code: str
    full_name: str
    # Plain str, not EmailStr: hospitals commonly use internal-only domains
    # (.local, .internal, .lan) that email-validator's reserved-name check
    # would otherwise reject when echoing back already-stored data.
    email: str
    role: str
    permissions: dict

    model_config = {"from_attributes": True}
