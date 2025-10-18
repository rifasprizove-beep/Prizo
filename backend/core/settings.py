from pydantic import BaseModel
from supabase import create_client, Client
from os import getenv

class Settings(BaseModel):
    supabase_url: str = getenv("SUPABASE_URL", "")
    supabase_service_key: str = getenv("SUPABASE_SERVICE_KEY", "")
    public_anon_key: str = getenv("PUBLIC_SUPABASE_ANON_KEY", "")

    # Tasa por defecto si todo falla (respaldo)
    default_usdves_rate: float = float(getenv("USDVES_RATE", "38.0"))

    # Texto por defecto de métodos locales
    pagomovil_info: str = getenv("PAYMENT_METHODS_INFO", "Pago Móvil no configurado")

    payments_bucket: str = getenv("PAYMENTS_BUCKET", "payments")
    admin_api_key: str = getenv("ADMIN_API_KEY", "")

    # Cloudinary (opcional) - configurar via env vars
    cloudinary_cloud_name: str = getenv("CLOUDINARY_CLOUD_NAME", "")
    cloudinary_api_key: str = getenv("CLOUDINARY_API_KEY", "")
    cloudinary_api_secret: str = getenv("CLOUDINARY_API_SECRET", "")
    # Interval (seconds) for automatic server-side cleanup of expired reservations
    cleanup_interval_seconds: int = int(getenv("CLEANUP_INTERVAL_SECONDS", "60"))

    # Forzar una API (opcional)
    bcv_api_url: str = getenv("BCV_API_URL", "")

settings = Settings()

def make_client() -> Client:
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_SERVICE_KEY")
    return create_client(settings.supabase_url, settings.supabase_service_key)
