# src/inventory-service/main.py
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import os

DB_URL = os.getenv("DB_URL", "postgresql://yugabyte:yugabyte@yugabyte-pg.task2.svc.cluster.local:5433/yugabyte")
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(bind=engine)
app = FastAPI(title="Inventory Service")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/stock/{item}")
def get_stock(item: str):
    db = SessionLocal()
    r = db.execute(text("SELECT stock FROM inventory WHERE item = :item"), {"item": item}).fetchone()
    db.close()
    if r:
        return {"item": item, "stock": r[0]}
    raise HTTPException(404, "Item not found")

@app.post("/stock/{item}/{qty}")
def reduce_stock(item: str, qty: int):
    db = SessionLocal()
    # naive update: decrement stock if enough
    res = db.execute(text("UPDATE inventory SET stock = stock - :qty WHERE item = :item AND stock >= :qty"),
                     {"item": item, "qty": qty})
    db.commit()
    db.close()
    return {"status": "updated"}

