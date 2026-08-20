from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import SessionLocal, init_db
from routers import auth_router, booking_router, parking_router
from seed import seed_all


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed_all(db)
    finally:
        db.close()
    yield


app = FastAPI(title="Parking Lot Management API", version="1.0.0", lifespan=lifespan)

# Allow all origins (JWT is sent via Authorization header, not cookies)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(parking_router.router)
app.include_router(booking_router.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
