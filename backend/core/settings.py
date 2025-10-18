from os import getenv, path
from pydantic import BaseModel
from supabase import create_client, Client
from dotenv import load_dotenv

# =====================================================
# Cargar archivo .env desde la carpeta backend/
# =====================================================
BASE_DIR = path.dirname(path.abspath(__file__))        # backend/core
ROOT_DIR = path.dirname(BASE_DIR)                      # backend/
ENV_PATH = path.join(ROOT_DIR, ".env")                 # backend/.env
load_dotenv(ENV_PATH)                                  # 👈 Carga el .env correcto
# =====================================================

class Settings(BaseModel):
    supabase_url: str = getenv("SUPABASE_URL", "")
    supabase_service_key: str = getenv("SUPABASE_SERVICE_KEY", "")
    public_anon_key: str = getenv("PUBLIC_SUPABASE_ANON_KEY", "")

    default_usdves_rate: float = float(getenv("USDVES_RATE", "38.0"))
    pagomovil_info: str = getenv("PAYMENT_METHODS_INFO", "Pago Móvil no configurado")
    payments_bucket: str = getenv("PAYMENTS_BUCKET", "payments")
    admin_api_key: str = getenv("ADMIN_API_KEY", "")

    cloudinary_cloud_name: str = getenv("CLOUDINARY_CLOUD_NAME", "")
    cloudinary_api_key: str = getenv("CLOUDINARY_API_KEY", "")
    cloudinary_api_secret: str = getenv("CLOUDINARY_API_SECRET", "")

    cleanup_interval_seconds: int = int(getenv("CLEANUP_INTERVAL_SECONDS", "60"))
    bcv_api_url: str = getenv("BCV_API_URL", "")

settings = Settings()

def make_client() -> Client:
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_SERVICE_KEY")
    return create_client(settings.supabase_url, settings.supabase_service_key)
