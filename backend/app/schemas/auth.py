from pydantic import BaseModel


class LoginRequest(BaseModel):
    identifier: str  # employee_code or email
    password: str


class ChangePasswordRequest(BaseModel):
    # Deliberately plain `str`, with the policy enforced in one place
    # (auth_service.validate_new_password) rather than half here as a
    # Field(min_length=...) and half there -- two half-expressions of a
    # rule drift apart, and the error the operator sees should come from
    # the same code the rule lives in.
    current_password: str
    new_password: str


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
    # True while this account is still using a password somebody else set
    # (the bootstrap one-time password, or an Administrator reset). The
    # frontend keeps the user on the change-password screen until it clears.
    must_change_password: bool = False

    model_config = {"from_attributes": True}
