# src/order-service/main.py
from fastapi import FastAPI, HTTPException, Header, Depends
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import httpx
import os

DB_URL = os.getenv("DB_URL", "postgresql://yugabyte:yugabyte@yugabyte-pg.task2.svc.cluster.local:5433/yugabyte")
INVENTORY_URL = os.getenv("INVENTORY_URL", "http://inventory-service.task2.svc.cluster.local:8001")
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(bind=engine)
app = FastAPI(title="Order Service")

def verify_auth(authorization: str = Header(None)):
    # simple token-check for demo; in real life use JWT / proper auth
    if authorization != "Bearer valid-token":
        raise HTTPException(status_code=403, detail="Unauthorized")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/order/{item}/{qty}")
async def create_order(item: str, qty: int, auth: str = Depends(verify_auth)):
    async with httpx.AsyncClient() as client:
        res = await client.get(f"{INVENTORY_URL}/stock/{item}")
        if res.status_code != 200:
            raise HTTPException(400, "Item not found")
        stock = res.json().get("stock", 0)
        if stock < qty:
            raise HTTPException(400, "Insufficient stock")
    # store order in DB and update inventory
    db = SessionLocal()
    db.execute(text("INSERT INTO orders (item, quantity) VALUES (:item, :qty)"), {"item": item, "qty": qty})
    db.execute(text("UPDATE inventory SET stock = stock - :qty WHERE item = :item"), {"item": item, "qty": qty})
    db.commit()
    db.close()
    return {"status": "order created", "item": item, "qty": qty}

