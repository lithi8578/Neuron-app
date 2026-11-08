"""Google 登入（只允許 ALLOWED_EMAILS 裡的信箱）＋ 本機開發模式登入。"""

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .config import settings
from .templating import templates

oauth = OAuth()
if settings.google_configured:
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

router = APIRouter()


class LoginRequired(Exception):
    """未登入時丟出，由 main.py 轉成導向登入頁。"""


def current_user(request: Request) -> str:
    """FastAPI 依賴：回傳登入者的 email，沒登入就導去登入頁。"""
    email = request.session.get("user")
    if not email:
        raise LoginRequired()
    return email


def _login_page(request: Request, error: str = "", status_code: int = 200):
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": error,
            "google_configured": settings.google_configured,
            "dev_login": settings.dev_login,
        },
        status_code=status_code,
    )


@router.get("/login")
def login(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/", status_code=303)
    return _login_page(request)


@router.get("/auth/google")
async def auth_google(request: Request):
    if not settings.google_configured:
        raise HTTPException(404)
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, str(redirect_uri))


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request):
    if not settings.google_configured:
        raise HTTPException(404)
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError:
        return _login_page(request, "Google 登入失敗，請再試一次。", 400)

    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower()
    if not info.get("email_verified") or email not in settings.allowed_emails:
        return _login_page(request, f"{email or '這個帳號'} 沒有使用權限。", 403)

    request.session.clear()
    request.session["user"] = email
    return RedirectResponse("/", status_code=303)


@router.post("/auth/dev")
def auth_dev(request: Request):
    if not settings.dev_login:
        raise HTTPException(404)
    request.session["user"] = "dev@localhost"
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
