from sqlalchemy import create_engine
from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True,
                       pool_size=20, max_overflow=20, pool_timeout=10)