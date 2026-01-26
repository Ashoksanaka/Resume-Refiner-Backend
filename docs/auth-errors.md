# Authentication Error Codes

This document describes the error codes and error response format for authentication endpoints.

## Error Response Format

All authentication error responses follow this standard format:

```json
{
  "code": "ERROR_CODE",
  "message": "Human-readable message",
  "errors": [
    {"field": "field_name", "code": "FIELD_ERROR_CODE"}
  ]
}
```

The `errors` array is only present for validation errors (400 responses).

## Error Codes

### Signup Errors

#### `INVALID_PAYLOAD` (400)
Returned when signup request has validation errors.

**Response:**
```json
{
  "code": "INVALID_PAYLOAD",
  "errors": [
    {"field": "email", "code": "INVALID_EMAIL_FORMAT"},
    {"field": "password", "code": "PASSWORD_TOO_WEAK"},
    {"field": "confirm_password", "code": "PASSWORD_MISMATCH"}
  ]
}
```

**Field-level error codes:**
- `INVALID_EMAIL_FORMAT`: Email format is invalid
- `PASSWORD_TOO_WEAK`: Password doesn't meet policy requirements (min 10 chars, uppercase, number, symbol)
- `PASSWORD_MISMATCH`: Password and confirm_password don't match

#### `EMAIL_ALREADY_REGISTERED` (409)
Returned when attempting to signup with an email that already exists.

**Response:**
```json
{
  "code": "EMAIL_ALREADY_REGISTERED",
  "message": "Account already exists. Try logging in."
}
```

### Login Errors

#### `INVALID_CREDENTIALS` (401)
Default error code for all login failures when `AUTH_DETAILED_ERRORS=false` (default).

**Response:**
```json
{
  "code": "INVALID_CREDENTIALS",
  "message": "Invalid email or password."
}
```

This generic error prevents account enumeration attacks.

#### Detailed Login Errors (401)
When `AUTH_DETAILED_ERRORS=true`, specific error codes are returned:

**`EMAIL_NOT_VERIFIED`**
```json
{
  "code": "EMAIL_NOT_VERIFIED",
  "message": "Email verification is required."
}
```

**`INVALID_PASSWORD`**
```json
{
  "code": "INVALID_PASSWORD",
  "message": "Invalid password."
}
```

**`ACCOUNT_LOCKED`**
```json
{
  "code": "ACCOUNT_LOCKED",
  "message": "Account is locked."
}
```

## Configuration

### Environment Variable

`AUTH_DETAILED_ERRORS` (default: `false`)

Controls whether login endpoints return detailed error messages. When `false` (default), all login failures return a generic `INVALID_CREDENTIALS` error to prevent account enumeration. When `true`, specific error codes are returned for better UX.

**Security Note:** Only enable detailed errors in development or when account enumeration is not a concern. In production, keep this disabled unless you have specific requirements.

## Password Policy

The password policy requirements are:

- **Minimum length**: 10 characters
- **Require uppercase**: Yes
- **Require number**: Yes
- **Require symbol**: Yes

You can retrieve the current policy via `GET /api/v1/auth/password-policy`.

## Password Strength Check

Use `POST /api/v1/auth/password-strength` to check password strength without storing it.

**Request:**
```json
{
  "password": "YourPassword123!"
}
```

**Response:**
```json
{
  "score": 70,
  "valid": true
}
```

- `score`: Integer from 0-100 indicating password strength
- `valid`: Boolean indicating if password meets policy requirements

**Security:** The password is evaluated in-memory only and never logged or persisted.

## Usage Examples

### Signup with Validation Errors

```bash
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "invalid-email",
    "password": "weak",
    "confirm_password": "different"
  }'
```

**Response (400):**
```json
{
  "code": "INVALID_PAYLOAD",
  "errors": [
    {"field": "email", "code": "INVALID_EMAIL_FORMAT"},
    {"field": "password", "code": "PASSWORD_TOO_WEAK"},
    {"field": "confirm_password", "code": "PASSWORD_MISMATCH"}
  ]
}
```

### Signup with Duplicate Email

```bash
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "existing@example.com",
    "password": "SecurePass123!",
    "confirm_password": "SecurePass123!"
  }'
```

**Response (409):**
```json
{
  "code": "EMAIL_ALREADY_REGISTERED",
  "message": "Account already exists. Try logging in."
}
```

### Login (Default - Generic Error)

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "wrongpassword"
  }'
```

**Response (401):**
```json
{
  "code": "INVALID_CREDENTIALS",
  "message": "Invalid email or password."
}
```

### Login (Detailed Errors Enabled)

When `AUTH_DETAILED_ERRORS=true`:

**Unverified Email:**
```json
{
  "code": "EMAIL_NOT_VERIFIED",
  "message": "Email verification is required."
}
```

**Wrong Password:**
```json
{
  "code": "INVALID_PASSWORD",
  "message": "Invalid password."
}
```

**Locked Account:**
```json
{
  "code": "ACCOUNT_LOCKED",
  "message": "Account is locked."
}
```
