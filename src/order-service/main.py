from fastapi import FastAPI, HTTPException, Header, Depends
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import httpx
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration from environment variables
db_host = os.getenv("DB_HOST", "yugabyte-yugabyte-ysql.task2.svc.cluster.local")
db_port = os.getenv("DB_PORT", "5433")
db_name = os.getenv("DB_NAME", "yugabyte")
db_user = os.getenv("DB_USER", "yugabyte")
db_password = os.getenv("DB_PASSWORD", "yugabyte")

DB_URL = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
INVENTORY_URL = os.getenv("INVENTORY_URL", "http://inventory-service.task2.svc.cluster.local:8001")

# For debugging
safe_db_url = f"postgresql://{db_user}:***@{db_host}:{db_port}/{db_name}"
logger.info(f"Connecting to database: {safe_db_url}")
logger.info(f"Inventory service URL: {INVENTORY_URL}")

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

app = FastAPI(title="Order Service")

def verify_auth(authorization: str = Header(None)):
    """Simple authentication middleware - in production use proper JWT validation"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    if authorization != "Bearer valid-token":
        raise HTTPException(status_code=403, detail="Invalid token")

@app.get("/health")
def health():
    return {"status": "ok", "service": "order"}

@app.post("/order/{item}/{qty}")
async def create_order(item: str, qty: int, authorization: str = Depends(verify_auth)):
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    
    db = SessionLocal()
    try:
        # Check inventory via HTTP call to inventory service
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                logger.info(f"Checking inventory for {item}, quantity {qty}")
                response = await client.get(f"{INVENTORY_URL}/stock/{item}")
                
                if response.status_code == 404:
                    raise HTTPException(status_code=400, detail="Item not found in inventory")
                elif response.status_code != 200:
                    raise HTTPException(status_code=500, detail="Inventory service error")
                
                inventory_data = response.json()
                available_stock = inventory_data.get("stock", 0)
                
                if available_stock < qty:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Insufficient stock. Available: {available_stock}, Requested: {qty}"
                    )
                    
            except httpx.RequestError as e:
                logger.error(f"Inventory service request failed: {e}")
                raise HTTPException(status_code=503, detail="Inventory service unavailable")
        
        # Create order and update inventory in a transaction
        db.execute(
            text("INSERT INTO orders (item, quantity) VALUES (:item, :qty)"), 
            {"item": item, "qty": qty}
        )
        db.execute(
            text("UPDATE inventory SET stock = stock - :qty WHERE item = :item"), 
            {"item": item, "qty": qty}
        )
        db.commit()
        
        logger.info(f"Order created successfully for {item}, quantity {qty}")
        return {
            "status": "order_created", 
            "item": item, 
            "quantity": qty,
            "message": "Order placed successfully"
        }
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Order creation failed: {e}")
        raise HTTPException(status_code=500, detail="Order creation failed")
    finally:
        db.close()

@app.get("/orders")
def get_orders(authorization: str = Depends(verify_auth)):
    db = SessionLocal()
    try:
        result = db.execute(text("SELECT order_id, item, quantity, created_at FROM orders ORDER BY created_at DESC"))
        orders = [
            {
                "order_id": row[0],
                "item": row[1], 
                "quantity": row[2],
                "created_at": row[3].isoformat() if row[3] else None
            }
            for row in result.fetchall()
        ]
        return {"orders": orders}
    except Exception as e:
        logger.error(f"Error retrieving orders: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        db.close()