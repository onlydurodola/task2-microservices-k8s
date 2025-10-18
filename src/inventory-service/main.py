from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Construct DB_URL from environment variables or use defaults for local development
db_host = os.getenv("DB_HOST", "yugabyte-yugabyte-ysql.task2.svc.cluster.local")
db_port = os.getenv("DB_PORT", "5433") 
db_name = os.getenv("DB_NAME", "yugabyte")
db_user = os.getenv("DB_USER", "yugabyte")
db_password = os.getenv("DB_PASSWORD", "yugabyte")

DB_URL = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

# For debugging - don't log the actual password in production
safe_db_url = f"postgresql://{db_user}:***@{db_host}:{db_port}/{db_name}"
logger.info(f"Connecting to database: {safe_db_url}")

try:
    engine = create_engine(DB_URL, pool_pre_ping=True, pool_recycle=300)
    SessionLocal = sessionmaker(bind=engine)
    
    # Test connection
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    logger.info("Database connection successful")
    
except Exception as e:
    logger.error(f"Database connection failed: {e}")
    raise

app = FastAPI(title="Inventory Service")

@app.get("/health")
def health():
    return {"status": "ok", "service": "inventory"}

@app.get("/stock/{item}")
def get_stock(item: str):
    db = SessionLocal()
    try:
        result = db.execute(text("SELECT stock FROM inventory WHERE item = :item"), {"item": item})
        row = result.fetchone()
        if row:
            return {"item": item, "stock": row[0]}
        raise HTTPException(status_code=404, detail="Item not found")
    except Exception as e:
        logger.error(f"Error getting stock for {item}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        db.close()

@app.post("/stock/{item}/{qty}")
def update_stock(item: str, qty: int):
    db = SessionLocal()
    try:
        # Check if item exists
        result = db.execute(text("SELECT stock FROM inventory WHERE item = :item"), {"item": item})
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Item not found")
        
        current_stock = row[0]
        new_stock = current_stock + qty
        
        if new_stock < 0:
            raise HTTPException(status_code=400, detail="Insufficient stock")
            
        # Update stock
        db.execute(
            text("UPDATE inventory SET stock = :new_stock WHERE item = :item"),
            {"item": item, "new_stock": new_stock}
        )
        db.commit()
        
        return {"status": "updated", "item": item, "previous_stock": current_stock, "new_stock": new_stock}
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating stock for {item}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        db.close()

@app.get("/stock")
def get_all_stock():
    db = SessionLocal()
    try:
        result = db.execute(text("SELECT item, stock FROM inventory"))
        items = [{"item": row[0], "stock": row[1]} for row in result.fetchall()]
        return {"items": items}
    except Exception as e:
        logger.error(f"Error getting all stock: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        db.close()