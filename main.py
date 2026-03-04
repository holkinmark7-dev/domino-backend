from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from supabase import create_client
from dependencies.limiter import limiter
from routers.pets import router as pets_router
from routers.chat import router as chat_router
from routers.timeline import router as timeline_router
from routers.vet_report import router as vet_report_router
from routers.chat_history import router as chat_history_router

from config import SUPABASE_URL, SUPABASE_KEY

app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Routers
app.include_router(pets_router)
app.include_router(chat_router)
app.include_router(timeline_router, prefix="/api")
app.include_router(vet_report_router)
app.include_router(chat_history_router)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8081",
        "http://127.0.0.1:8081",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Security headers
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

app.add_middleware(SecurityHeadersMiddleware)

# Supabase client
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# For production:
# uvicorn main:app --host 0.0.0.0 --port 8000


@app.get("/health")
def health():
    return {"status": "ok"}
