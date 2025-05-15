import os
import time
import json
import sqlite3
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint
import sys
import argparse

# Load environment variables
load_dotenv()

class ICNetProbe:
    def __init__(self, node_provider_id: str):
        self.db_path = "ic_netprobe.db"
        self.globalping_api_key = os.getenv("GLOBALPING_API_KEY")
        self.ic_api_url = f"https://ic-api.internetcomputer.org/api/v3/nodes?node_provider_id={node_provider_id}"
        self.globalping_url = "https://api.globalping.io/v1/measurements"
        self.console = Console()
        self.google_chat_webhook = os.getenv("GOOGLE_CHAT_WEBHOOK_URL")
        
        # Email configuration
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER")
        self.smtp_password = os.getenv("SMTP_PASSWORD")
        self.alert_recipients = os.getenv("ALERT_EMAIL_RECIPIENTS", "").split(",")
        
        # Initialize Jinja2 environment
        self.template_env = Environment(loader=FileSystemLoader('templates'))
        
        self.init_db()

    def init_db(self):
        """Initialize SQLite database with required tables."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create nodes table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS nodes (
            node_id TEXT PRIMARY KEY,
            ipv6 TEXT NOT NULL,
            region TEXT,
            dc_name TEXT
        )
        """)
        
        # Create measurements table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS measurements (
            id TEXT PRIMARY KEY,
            node_id TEXT NOT NULL,
            target TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT,
            result JSON,
            FOREIGN KEY (node_id) REFERENCES nodes (node_id)
        )
        """)
        
        conn.commit()
        conn.close()

    def fetch_nodes(self) -> List[Dict]:
        """Fetch nodes from IC API."""
        try:
            provider_id = self.ic_api_url.split('=')[-1]
            self.console.print(f"[yellow]Fetching nodes for provider ID: {provider_id}[/yellow]")
            
            response = requests.get(self.ic_api_url)
            response.raise_for_status()
            
            # Parse the JSON response
            data = response.json()
            
            # Check if we have the expected data structure
            if not isinstance(data, dict) or 'nodes' not in data:
                self.console.print(f"[red]Unexpected API response format. Expected dict with 'nodes' key[/red]")
                return []
            
            # Extract node information from the 'nodes' array
            nodes = []
            for node in data['nodes']:
                if isinstance(node, dict) and 'node_id' in node and 'ip_address' in node:
                    nodes.append({
                        'node_id': node['node_id'],
                        'ipv6': node['ip_address'],
                        'region': node.get('region'),
                        'dc_name': node.get('dc_name'),
                        'status': node.get('status'),
                        'node_type': node.get('node_type')
                    })
            
            # Log detailed information about the nodes
            self.console.print(f"\n[bold cyan]Provider Information:[/bold cyan]")
            self.console.print(f"Total Nodes: {len(nodes)}")
            
            # Count nodes by status
            status_counts = {}
            for node in nodes:
                status = node.get('status', 'UNKNOWN')
                status_counts[status] = status_counts.get(status, 0) + 1
            
            self.console.print("\n[bold cyan]Node Status Summary:[/bold cyan]")
            for status, count in status_counts.items():
                self.console.print(f"{status}: {count} nodes")
            
            # Count nodes by type
            type_counts = {}
            for node in nodes:
                node_type = node.get('node_type', 'UNKNOWN')
                type_counts[node_type] = type_counts.get(node_type, 0) + 1
            
            self.console.print("\n[bold cyan]Node Type Summary:[/bold cyan]")
            for node_type, count in type_counts.items():
                self.console.print(f"{node_type}: {count} nodes")
            
            return nodes
            
        except requests.exceptions.RequestException as e:
            self.console.print(f"[red]Error fetching nodes from API: {str(e)}[/red]")
            return []
        except json.JSONDecodeError as e:
            self.console.print(f"[red]Error parsing API response: {str(e)}[/red]")
            return []
        except Exception as e:
            self.console.print(f"[red]Unexpected error in fetch_nodes: {str(e)}[/red]")
            return []

    def store_nodes(self, nodes: List[Dict]):
        """Store or update nodes in the database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for node in nodes:
            cursor.execute("""
            INSERT OR REPLACE INTO nodes (node_id, ipv6, region, dc_name)
            VALUES (?, ?, ?, ?)
            """, (
                node['node_id'],
                node['ipv6'],
                node.get('region'),
                node.get('dc_name')
            ))
        
        conn.commit()
        conn.close()

    def create_measurement(self, target: str) -> str:
        """Create a new ping measurement via Globalping API."""
        headers = {
            "Authorization": f"Bearer {self.globalping_api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "type": "ping",
            "target": target,
            "locations": [
                {
                    "continent": "EU",
                    "limit": 4
                },
                {
                    "continent": "NA",
                    "limit": 4
                },
                {
                    "continent": "AS",
                    "limit": 4
                }
            ],
            "measurementOptions": {
                "packets": 16
            },
            "inProgressUpdates": True  # Get real-time updates
        }
        
        try:
            response = requests.post(
                self.globalping_url,
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            return response.json()['id']
        except requests.exceptions.RequestException as e:
            self.console.print(f"[red]Error creating measurement: {str(e)}[/red]")
            if hasattr(e.response, 'text'):
                self.console.print(f"[red]API Response: {e.response.text}[/red]")
            raise

    def poll_measurement(self, measurement_id: str) -> Dict:
        """Poll measurement status until complete."""
        headers = {
            "Authorization": f"Bearer {self.globalping_api_key}"
        }
        
        while True:
            response = requests.get(
                f"{self.globalping_url}/{measurement_id}",
                headers=headers
            )
            response.raise_for_status()
            result = response.json()
            
            if result['status'] == 'finished':
                return result
            
            time.sleep(1)

    def store_measurement(self, measurement_id: str, node_id: str, target: str, result: Dict):
        """Store measurement result in database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
        INSERT INTO measurements (id, node_id, target, status, result)
        VALUES (?, ?, ?, ?, ?)
        """, (
            measurement_id,
            node_id,
            target,
            result['status'],
            json.dumps(result)
        ))
        
        conn.commit()
        conn.close()

    async def send_google_chat_notification(self, node_id: str, result: Dict, attempt: int = 1) -> None:
        """Send measurement results to Google Chat."""
        if not self.google_chat_webhook:
            self.console.print("[yellow]Google Chat webhook URL not configured. Skipping notification.[/yellow]")
            return

        try:
            # Calculate statistics
            total_probes = len(result['results'])
            failed_probes = sum(1 for r in result['results'] if r.get('result', {}).get('stats', {}).get('loss', 0) > 0)
            successful_latencies = [
                r.get('result', {}).get('stats', {}).get('avg', 0)
                for r in result['results']
                if r.get('result', {}).get('stats', {}).get('loss', 0) == 0
            ]
            avg_latency = sum(successful_latencies) / len(successful_latencies) if successful_latencies else 0

            # Check for high latency probes (over 1000ms)
            high_latency_probes = [
                (r['probe'], r['result']['stats'])
                for r in result['results']
                if r.get('result', {}).get('stats', {}).get('avg', 0) > 1000
            ]

            # Format the message based on status
            if failed_probes > 0 or high_latency_probes:
                # Detailed message for issues
                message = f"""⚠️ *IC Node Measurement Alert*

*Node ID:* `{node_id}`
*Timestamp:* {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}

*Summary:*
- Total Probes: {total_probes}
- Failed Probes: {failed_probes}
- Average Latency: {avg_latency:.2f}ms

*Issues Detected:*"""

                # Add failed probes
                if failed_probes > 0:
                    message += "\n\n*Failed Probes:*"
                    for probe_result in result['results']:
                        if probe_result.get('result', {}).get('stats', {}).get('loss', 0) > 0:
                            probe = probe_result['probe']
                            stats = probe_result['result']['stats']
                            message += f"\n❌ {probe.get('continent', 'N/A')} - {probe.get('country', 'N/A')}: {stats.get('loss', 0)}% packet loss"

                # Add high latency probes
                if high_latency_probes:
                    message += "\n\n*High Latency Probes:*"
                    for probe, stats in high_latency_probes:
                        message += f"\n⚠️ {probe.get('continent', 'N/A')} - {probe.get('country', 'N/A')}: {stats.get('avg', 'N/A')}ms"
            else:
                # Simple summary for healthy nodes
                message = f"""✅ *IC Node Measurement Summary*

*Node ID:* `{node_id}`
*Timestamp:* {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}

*Status:* All probes successful
*Average Latency:* {avg_latency:.2f}ms"""

            # Send to Google Chat
            response = requests.post(
                self.google_chat_webhook,
                json={"text": message},
                headers={"Content-Type": "application/json; charset=UTF-8"}
            )
            response.raise_for_status()
            self.console.print("[green]✓ Notification sent to Google Chat[/green]")

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429 and attempt < 5:  # Rate limit
                delay = (2 ** attempt) * 1000  # Exponential backoff in milliseconds
                self.console.print(f"[yellow]Rate limit exceeded. Retrying in {delay}ms...[/yellow]")
                time.sleep(delay / 1000)  # Convert to seconds
                await self.send_google_chat_notification(node_id, result, attempt + 1)
            else:
                self.console.print(f"[red]Failed to send Google Chat notification: {str(e)}[/red]")
        except Exception as e:
            self.console.print(f"[red]Error sending Google Chat notification: {str(e)}[/red]")

    def log_measurement_result(self, node_id: str, result: Dict):
        """Log measurement results to CLI with rich formatting."""
        self.console.print(f"\n[bold blue]Measurement Results for Node {node_id}[/bold blue]")
        
        # Create a table for probe results
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Probe Location")
        table.add_column("Status")
        table.add_column("Packets Sent")
        table.add_column("Packets Lost")
        table.add_column("Min RTT")
        table.add_column("Avg RTT")
        table.add_column("Max RTT")
        
        if 'results' in result:
            for probe_result in result['results']:
                if 'probe' in probe_result and 'result' in probe_result:
                    probe = probe_result['probe']
                    stats = probe_result['result'].get('stats', {})
                    
                    # Determine status color
                    status = "OK"
                    status_style = "green"
                    if stats.get('loss', 0) > 0:
                        status = "Failed"
                        status_style = "red"
                    elif stats.get('avg', 0) > 1000:
                        status = "High Latency"
                        status_style = "yellow"
                    
                    # Add row to table
                    table.add_row(
                        f"{probe.get('continent', 'N/A')} - {probe.get('country', 'N/A')}",
                        f"[{status_style}]{status}[/{status_style}]",
                        str(stats.get('total', 'N/A')),
                        f"{stats.get('loss', 0)}",
                        f"{stats.get('min', 'N/A')}ms",
                        f"{stats.get('avg', 'N/A')}ms",
                        f"{stats.get('max', 'N/A')}ms"
                    )
        
        # Print the table
        self.console.print(table)
        
        # Print summary statistics
        if 'results' in result:
            total_probes = len(result['results'])
            failed_probes = sum(1 for r in result['results'] if r.get('result', {}).get('stats', {}).get('loss', 0) > 0)
            
            # Calculate average latency only from successful probes
            successful_latencies = [
                r.get('result', {}).get('stats', {}).get('avg', 0)
                for r in result['results']
                if r.get('result', {}).get('stats', {}).get('loss', 0) == 0
            ]
            avg_latency = sum(successful_latencies) / len(successful_latencies) if successful_latencies else 0
            
            summary = Panel(
                f"[bold]Summary:[/bold]\n"
                f"Total Probes: {total_probes}\n"
                f"Failed Probes: {failed_probes}\n"
                f"Average Latency: {avg_latency:.2f}ms",
                title="Measurement Summary",
                border_style="blue"
            )
            self.console.print(summary)

            # Send Google Chat notification
            import asyncio
            asyncio.run(self.send_google_chat_notification(node_id, result))

    def run_measurement_cycle(self):
        """Run a complete measurement cycle."""
        try:
            # Fetch and store nodes
            nodes = self.fetch_nodes()
            self.store_nodes(nodes)
            
            # Get stored nodes from DB
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT node_id, ipv6 FROM nodes")
            stored_nodes = cursor.fetchall()
            conn.close()
            
            total_nodes = len(stored_nodes)
            self.console.print(f"\n[bold cyan]Starting measurement cycle for {total_nodes} nodes[/bold cyan]")
            
            # Run measurements for each node sequentially
            for index, (node_id, ipv6) in enumerate(stored_nodes, 1):
                try:
                    self.console.print(f"\n[bold cyan]Processing node {index}/{total_nodes}[/bold cyan]")
                    self.console.print(f"Node ID: {node_id}")
                    self.console.print(f"Target IPv6: {ipv6}")
                    
                    # Create measurement
                    measurement_id = self.create_measurement(ipv6)
                    self.console.print(f"[yellow]Created measurement {measurement_id}[/yellow]")
                    
                    # Poll for results
                    self.console.print("[yellow]Waiting for measurement results...[/yellow]")
                    result = self.poll_measurement(measurement_id)
                    
                    # Log results before storing
                    self.log_measurement_result(node_id, result)
                    
                    # Store results
                    self.store_measurement(measurement_id, node_id, ipv6, result)
                    self.console.print(f"[green]✓ Completed measurement for node {node_id}[/green]")
                    
                    # Add a small delay between nodes to avoid rate limiting
                    if index < total_nodes:
                        self.console.print("[yellow]Waiting 2 seconds before next measurement...[/yellow]")
                        time.sleep(2)
                    
                except Exception as e:
                    self.console.print(f"[bold red]Error measuring node {node_id}: {str(e)}[/bold red]")
                    continue
            
            self.console.print(f"\n[bold green]✓ Completed measurement cycle for all {total_nodes} nodes[/bold green]")
                
        except Exception as e:
            self.console.print(f"[bold red]Error in measurement cycle: {str(e)}[/bold red]")

    def generate_daily_report(self) -> str:
        """Generate HTML report for the last 24 hours."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get measurements from last 24 hours
        cutoff_time = datetime.utcnow() - timedelta(hours=24)
        
        cursor.execute("""
        SELECT n.node_id, n.region, n.dc_name, m.result, m.created_at
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
            nodes[node_id]['measurements'].append({
                'timestamp': row['created_at'],
                'result': result
            })
        
        # Calculate statistics
        for node in nodes.values():
            total_measurements = len(node['measurements'])
            failed_measurements = 0
            total_latency = 0
            latency_count = 0
            
            for measurement in node['measurements']:
                result = measurement['result']
                if 'results' in result:
                    for probe_result in result['results']:
                        if 'stats' in probe_result:
                            stats = probe_result['stats']
                            if stats.get('loss', 0) > 0:
                                failed_measurements += 1
                            if 'avg' in stats:
                                total_latency += stats['avg']
                                latency_count += 1
            
            node['stats'] = {
                'total_measurements': total_measurements,
                'failed_measurements': failed_measurements,
                'failure_rate': (failed_measurements / total_measurements * 100) if total_measurements > 0 else 0,
                'avg_latency': (total_latency / latency_count) if latency_count > 0 else 0
            }
        
        # Load and render template
        template = self.template_env.get_template('email_report.html')
        
        total_nodes = len(nodes)
        failing_nodes = sum(1 for node in nodes.values() if node['stats']['failure_rate'] > 0)
        avg_latency = sum(node['stats']['avg_latency'] for node in nodes.values()) / total_nodes if total_nodes > 0 else 0
        
        html = template.render(
            timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            total_nodes=total_nodes,
            failing_nodes=failing_nodes,
            avg_latency=round(avg_latency, 2),
            nodes=nodes.values()
        )
        
        conn.close()
        return html

    def send_email_report(self):
        """Send daily report via email."""
        if not all([self.smtp_user, self.smtp_password, self.alert_recipients]):
            print("Email configuration incomplete. Skipping report.")
            return
        
        try:
            msg = MIMEMultipart()
            msg['From'] = self.smtp_user
            msg['To'] = ", ".join(self.alert_recipients)
            msg['Subject'] = f"IC Node Monitoring Report - {datetime.utcnow().strftime('%Y-%m-%d')}"
            
            html_content = self.generate_daily_report()
            msg.attach(MIMEText(html_content, 'html'))
            
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            
            print("Daily report sent successfully")
            
        except Exception as e:
            print(f"Error sending email report: {str(e)}")

def main():
    # Get node provider ID from environment variable
    node_provider_id = os.getenv("PROVIDER_ID")
    if not node_provider_id:
        print("Error: PROVIDER_ID environment variable is required")
        sys.exit(1)
        
    probe = ICNetProbe(node_provider_id)
    last_report_time = None
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='IC Network Probe')
    parser.add_argument('--send-report', action='store_true', help='Send report immediately')
    args = parser.parse_args()
    
    while True:
        current_time = datetime.utcnow()
        
        # Run measurements every 4 hours
        probe.run_measurement_cycle()
        
        # Send report every 6 hours or if --send-report flag is used
        if args.send_report or (last_report_time is None or 
            (current_time - last_report_time).total_seconds() >= 6 * 60 * 60):
            probe.send_email_report()
            last_report_time = current_time
            if args.send_report:
                # Exit after sending report if --send-report flag was used
                break
        
        # Sleep until next measurement cycle (4 hours)
        time.sleep(6 * 60 * 60)  # 4 hours in seconds

if __name__ == "__main__":
    main() 