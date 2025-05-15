# IC NetProbe
<img width="685" alt="Screenshot 2025-05-15 at 5 36 10 PM" src="https://github.com/user-attachments/assets/ad7a368a-2d3c-4237-aaae-1587d973fd36" />

A monitoring tool for Internet Computer nodes that performs network measurements and provides real-time notifications.

## Features

- Performs ping measurements from multiple regions (EU, NA, ASIA)
- Monitors specific node provider's nodes
- Real-time Google Chat notifications for measurement results
- Daily email reports with detailed statistics
- Rich CLI output with detailed measurement results
- Automatic retry mechanism for failed measurements
- Rate limit handling with exponential backoff

## Prerequisites

- Python 3.8 or higher
- Virtual environment (recommended)
- Globalping API key
- Google Chat webhook URL (for notifications)
- SMTP server access (for email reports)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/ic-netprobe.git
cd ic-netprobe
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file from the template:
```bash
cp .env.example .env
```

5. Configure your environment variables in `.env`:
```env
# Globalping API Key
GLOBALPING_API_KEY=your_api_key_here

# Node Provider ID
PROVIDER_ID=your_provider_id_here

# Email Configuration
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_specific_password
ALERT_EMAIL_RECIPIENTS=recipient1@example.com,recipient2@example.com

# Google Chat Webhook URL
GOOGLE_CHAT_WEBHOOK_URL=your_webhook_url_here
```

## Usage

### Running the Monitor

Start the monitoring service:
```bash
python ic_netprobe.py
```

The service will:
- Run measurements every 4 hours
- Send email reports every 6 hours
- Send real-time Google Chat notifications for measurement results

### Command Line Options

Send an immediate report and exit:
```bash
python ic_netprobe.py --send-report
```

## Measurement Details

- **Frequency**: Every 4 hours
- **Regions**: EU, NA, ASIA
- **Probes per Region**: 4
- **Packet Count**: 16
- **Measurement Type**: IPv6 Ping

## Notifications

### Google Chat Notifications

The tool sends two types of notifications:

1. **Healthy Node Summary**:
```
✅ *IC Node Measurement Summary*

*Node ID:* `node_id`
*Timestamp:* YYYY-MM-DD HH:MM:SS UTC

*Status:* All probes successful
*Average Latency:* XXXms
```

2. **Alert for Issues**:
```
⚠️ *IC Node Measurement Alert*

*Node ID:* `node_id`
*Timestamp:* YYYY-MM-DD HH:MM:SS UTC

*Summary:*
- Total Probes: X
- Failed Probes: X
- Average Latency: XXXms

*Issues Detected:*
[Details of failed probes and high latency]
```

### Email Reports

Daily email reports include:
- Overall statistics
- Node-specific measurements
- Failure rates
- Average latencies
- Detailed probe results

## Database

The tool uses SQLite to store:
- Node information
- Measurement results
- Historical data

Database file: `ic_netprobe.db`

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details. 
