import os
import sys

# Ensure project root is in sys.path when running as a direct script
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api.routes import auth as auth_routes, chat, security_console

app = FastAPI(
    title="AI-Powered Threat Detection API",
    description="Multi-layered defense firewall for conversational agents (Prompt Injection, Jailbreak, Policy Bypass)",
    version="1.0.0"
)

# Enable CORS for Next.js frontend demo and console
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router, prefix="/auth", tags=["Authentication"])
app.include_router(chat.router, prefix="/chat", tags=["Chat & Threat Detection"])
app.include_router(security_console.router, prefix="/console", tags=["Security Console"])

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", tags=["Dashboard UI"])
def serve_dashboard():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "AI Firewall API is running. Documentation at /docs"}

@app.get("/health", tags=["Health"])
def health_check():
    engine = chat.orchestrator.health()
    return {
        "status": engine["status"],
        "service": "ai-firewall-api",
        "degraded_layers": engine["degraded_layers"],
        "engine": engine["layers"],
        "layers": {
            "layer1": "Regex + Vector Prefilter",
            "layer2": "XGBoost Feature Classifier",
            "layer3": "DistilBERT Sequence Classifier",
            "layer4": "Pydantic Policy Validator"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=True)
