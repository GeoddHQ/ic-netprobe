from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import json
from typing import List, Dict
from datetime import datetime, timedelta

app = FastAPI(title="IC NetProbe API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    conn = sqlite3.connect("ic_netprobe.db")
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/api/measurements")
async def list_measurements(limit: int = 100, offset: int = 0):
    """List recent measurements with pagination."""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT m.*, n.region, n.dc_name
    FROM measurements m
    JOIN nodes n ON m.node_id = n.node_id
    ORDER BY m.created_at DESC
    LIMIT ? OFFSET ?
    """, (limit, offset))
    
    measurements = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return measurements

@app.get("/api/measurements/{measurement_id}")
async def get_measurement(measurement_id: str):
    """Get specific measurement result."""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT m.*, n.region, n.dc_name
    FROM measurements m
    JOIN nodes n ON m.node_id = n.node_id
    WHERE m.id = ?
    """, (measurement_id,))
    
    measurement = cursor.fetchone()
    conn.close()
    
    if not measurement:
        raise HTTPException(status_code=404, detail="Measurement not found")
    
    return dict(measurement)

@app.get("/api/nodes/failing")
async def get_failing_nodes(hours: int = 24):
    """Get nodes with recent failures or high latency."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Get measurements from the last N hours
    cutoff_time = datetime.utcnow() - timedelta(hours=hours)
    
    cursor.execute("""
    SELECT n.node_id, n.region, n.dc_name, m.result
    FROM nodes n
    JOIN measurements m ON n.node_id = m.node_id
    WHERE m.created_at > ?
    ORDER BY m.created_at DESC
    """, (cutoff_time.isoformat(),))
    
    nodes = {}
    for row in cursor.fetchall():
        node_id = row['node_id']
        if node_id not in nodes:
            nodes[node_id] = {
                'node_id': node_id,
                'region': row['region'],
                'dc_name': row['dc_name'],
                'measurements': []
            }
        
        result = json.loads(row['result'])
        nodes[node_id]['measurements'].append(result)
    
    # Filter for failing nodes
    failing_nodes = []
    for node in nodes.values():
        has_failure = False
        for measurement in node['measurements']:
            if 'results' in measurement:
                for result in measurement['results']:
                    if 'stats' in result:
                        stats = result['stats']
                        if stats.get('loss', 0) > 0 or stats.get('avg', 0) > 1000:  # 1000ms threshold
                            has_failure = True
                            break
        
        if has_failure:
            failing_nodes.append(node)
    
    conn.close()
    return failing_nodes

@app.get("/api/nodes")
async def list_nodes():
    """List all nodes being monitored."""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM nodes")
    nodes = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return nodes

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 