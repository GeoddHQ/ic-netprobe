# IC NetProbe

A monitoring system for Internet Computer (IC) nodes that measures IPv6 connectivity using Globalping probes and stores results in SQLite for reporting and analysis.

## Features

- Automatic discovery of IC nodes
- IPv6 connectivity testing via Globalping
- SQLite storage for historical data
- REST API for accessing measurement results
- Detection of failing or high-latency nodes

## Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/ic-netprobe.git
cd ic-netprobe
```

2. Create a virtual environment and install dependencies:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

3. Create a `.env` file with your configuration:
```bash
cp .env.example .env
```

Edit `.env` and add your Globalping API key:
```
GLOBALPING_API_KEY=your_api_key_here
```

## Usage

### Running the Monitor

Start the monitoring service:
```bash
python ic_netprobe.py
```

This will:
- Fetch IC nodes every 5 minutes
- Create ping measurements for each node
- Store results in SQLite database

### Running the API

Start the FastAPI server:
```bash
python api.py
```

The API will be available at `http://localhost:8000` with the following endpoints:

- `GET /api/measurements` - List recent measurements
- `GET /api/measurements/{id}` - Get specific measurement
- `GET /api/nodes/failing` - Show nodes with recent failures
- `GET /api/nodes` - List all monitored nodes

API documentation is available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Database Schema

### Nodes Table
```sql
CREATE TABLE nodes (
    node_id TEXT PRIMARY KEY,
    ipv6 TEXT NOT NULL,
    region TEXT,
    dc_name TEXT
);
```

### Measurements Table
```sql
CREATE TABLE measurements (
    id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL,
    target TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT,
    result JSON,
    FOREIGN KEY (node_id) REFERENCES nodes (node_id)
);
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

MIT License 