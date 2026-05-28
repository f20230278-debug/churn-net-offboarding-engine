import sqlite3
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any

# 1. Initialize the FastAPI application object (This defines 'app'!)
app = FastAPI(
    title="The Churn Net: Automated Offboarding Engine", version="1.0.0")

DB_FILE = "churn_net.db"

# 2. Relational Database Initialization


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS billing_tiers (
        tier_id INTEGER PRIMARY KEY AUTOINCREMENT,
        tier_name TEXT NOT NULL,
        monthly_price REAL NOT NULL
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        tier_id INTEGER,
        account_status TEXT DEFAULT 'active',
        discount_applied REAL DEFAULT 0.0,
        FOREIGN KEY (tier_id) REFERENCES billing_tiers(tier_id)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS feature_usage (
        usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        feature_name TEXT NOT NULL,
        clicks_past_30_days INTEGER DEFAULT 0,
        days_since_last_active INTEGER NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    );
    """)

    cursor.execute("SELECT COUNT(*) FROM billing_tiers;")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("INSERT INTO billing_tiers (tier_name, monthly_price) VALUES (?, ?);", [
            ('Basic', 19.99), ('Professional', 49.99), ('Enterprise', 199.99)
        ])

        cursor.executemany("INSERT INTO users (email, tier_id, account_status) VALUES (?, ?, ?);", [
            ('user_active@example.com', 2, 'active'),
            ('user_at_risk@example.com', 2, 'active'),
            ('user_churned@example.com', 1, 'cancelled')
        ])

        cursor.executemany("INSERT INTO feature_usage (user_id, feature_name, clicks_past_30_days, days_since_last_active) VALUES (?, ?, ?, ?);", [
            (1, 'Dashboard Analytics', 150, 2),
            (1, 'Export Reports', 25, 4),
            (2, 'Dashboard Analytics', 2, 35),
            (2, 'Export Reports', 0, 42),
            (3, 'Dashboard Analytics', 0, 90)
        ])

    conn.commit()
    conn.close()


init_db()

# 3. Pydantic Data Schema


class OffboardRequest(BaseModel):
    user_id: int
    reason: str

# 4. GET Analytics Endpoint


@app.get("/api/v1/analytics/at-risk", tags=["Data Analytics"])
def get_at_risk_users() -> Dict[str, Any]:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT 
            u.user_id, 
            u.email, 
            b.tier_name, 
            b.monthly_price,
            AVG(f.days_since_last_active) as avg_days_inactive,
            SUM(f.clicks_past_30_days) as total_clicks_30_days
        FROM users u
        INNER JOIN billing_tiers b ON u.tier_id = b.tier_id
        INNER JOIN feature_usage f ON u.user_id = f.user_id
        WHERE u.account_status = 'active'
        GROUP BY u.user_id
        HAVING avg_days_inactive > 30 AND total_clicks_30_days < 10;
    """

    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()

    at_risk_list = [dict(row) for row in rows]
    return {
        "status": "success",
        "total_at_risk_detected": len(at_risk_list),
        "data": at_risk_list
    }

# 5. POST Offboarding Intercept Endpoint


@app.post("/api/v1/offboard/initiate", tags=["Offboarding Engine"])
def initiate_offboarding(request: OffboardRequest) -> Dict[str, Any]:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT account_status FROM users WHERE user_id = ?;", (request.user_id,))
    user_res = cursor.fetchone()

    if not user_res:
        conn.close()
        raise HTTPException(
            status_code=404, detail="User account profile not found.")

    current_status = user_res[0]
    if current_status == 'cancelled':
        conn.close()
        return {"status": "ignored", "message": "Account has already been fully decommissioned."}

    cursor.execute("""
        SELECT AVG(days_since_last_active), SUM(clicks_past_30_days) 
        FROM feature_usage WHERE user_id = ?;
    """, (request.user_id,))
    avg_inactive, total_clicks = cursor.fetchone()

    if avg_inactive and avg_inactive > 30:
        retention_action = "AUTOMATED_DISCOUNT_50"
        cursor.execute("""
            UPDATE users 
            SET discount_applied = 0.50 
            WHERE user_id = ?;
        """, (request.user_id,))
        message = "High-risk structural drop-off detected. Triggering an automated 50% financial discount retention offer."

    else:
        retention_action = "AUTOMATED_ACCOUNT_PAUSE"
        cursor.execute("""
            UPDATE users 
            SET account_status = 'paused' 
            WHERE user_id = ?;
        """, (request.user_id,))
        message = "Healthy product engagement verified. Converting cancellation attempt to temporary billing freeze/pause state."

    conn.commit()

    cursor.execute(
        "SELECT account_status, discount_applied FROM users WHERE user_id = ?;", (request.user_id,))
    updated_status, updated_discount = cursor.fetchone()
    conn.close()

    return {
        "status": "intercepted",
        "action_taken": retention_action,
        "system_rationale": message,
        "current_state": {
            "user_id": request.user_id,
            "account_status": updated_status,
            "discount_applied": updated_discount
        }
    }


# 6. Server Execution Engine
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
