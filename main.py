from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
from routers.pets import router as pets_router
from routers.chat import router as chat_router
from routers.timeline import router as timeline_router
from routers.vet_report import router as vet_report_router
from routers.chat_history import router as chat_history_router

from config import SUPABASE_URL, SUPABASE_KEY

app = FastAPI()

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
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase client
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# For production:
# uvicorn main:app --host 0.0.0.0 --port 8000


@app.get("/health")
def health():
    return {"status": "ok"}
