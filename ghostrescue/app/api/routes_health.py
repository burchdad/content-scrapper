from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.core.config import get_settings

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": "1.0.0",
        "disclaimer": settings.disclaimer,
    }


@router.get("/", response_class=HTMLResponse)
async def root():
    """Root endpoint with info and redirect."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>GhostRescue AI</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                margin: 0;
                padding: 40px;
                background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
                color: #f1f5f9;
                min-height: 100vh;
            }
            .container {
                max-width: 600px;
                margin: 0 auto;
                text-align: center;
            }
            h1 {
                font-size: 2.5em;
                margin-bottom: 10px;
                color: #60a5fa;
            }
            p {
                font-size: 1.1em;
                color: #cbd5e1;
                margin: 16px 0;
            }
            .buttons {
                display: flex;
                gap: 16px;
                justify-content: center;
                margin-top: 32px;
                flex-wrap: wrap;
            }
            a {
                display: inline-block;
                padding: 12px 24px;
                background: #2563eb;
                color: white;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 600;
                transition: all 0.2s;
            }
            a:hover {
                background: #1e40af;
                transform: translateY(-2px);
            }
            .link-secondary {
                background: #475569;
            }
            .link-secondary:hover {
                background: #64748b;
            }
            .disclaimer {
                margin-top: 40px;
                padding: 16px;
                background: rgba(255, 193, 7, 0.1);
                border-left: 4px solid #fbbf24;
                border-radius: 4px;
                font-size: 0.9em;
                color: #fca5a5;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎯 GhostRescue AI</h1>
            <p>Intelligence Platform for Identifying Trafficking Patterns</p>
            <p style="color: #10b981; font-weight: 600;">● System Online</p>
            
            <div class="buttons">
                <a href="/dashboard">📊 Go to Dashboard</a>
                <a href="/docs" class="link-secondary">📖 API Docs</a>
                <a href="/health" class="link-secondary">✓ Health Check</a>
            </div>
            
            <div class="disclaimer">
                ⚠️ <strong>Disclaimer:</strong> Outputs are intelligence leads, not verified conclusions. All data is sourced from public, legally permitted records only. This system does not generate accusations or legal determinations. Human review is required before any action is taken.
            </div>
        </div>
    </body>
    </html>
    """
