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

# Load environment variables
load_dotenv()

class ICNetProbe:
    def __init__(self):
        self.db_path = "ic_netprobe.db"
        self.globalping_api_key = os.getenv("GLOBALPING_API_KEY")
        self.ic_api_url = "https://ic-api.internetcomputer.org/api/v3/nodes"
        self.globalping_url = "https://api.globalping.io/v1/measurements"
        self.console = Console()
        
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
            response = requests.get(self.ic_api_url)
            response.raise_for_status()
            
            # Log the raw response for debugging
            self.console.print(f"[yellow]API Response Status: {response.status_code}[/yellow]")
            
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
                        'region': node.get('dc_name'),
                        'dc_name': node.get('dc_name')
                    })
                else:
                    self.console.print(f"[yellow]Skipping invalid node data: {node}[/yellow]")
            
            self.console.print(f"[green]Successfully fetched {len(nodes)} nodes[/green]")
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
                "packets": 16,
                "ipVersion": 6  # Explicitly use IPv6
            },
            "inProgressUpdates": True  # Get real-time updates
        }
        
        response = requests.post(
            self.globalping_url,
            headers=headers,
            json=payload
        )
        response.raise_for_status()
        
        return response.json()['id']

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
            
            time.sleep(0.5)

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
                if 'probe' in probe_result and 'stats' in probe_result:
                    probe = probe_result['probe']
                    stats = probe_result['stats']
                    
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
                        str(stats.get('packets', 'N/A')),
                        f"{stats.get('loss', 0)}%",
                        f"{stats.get('min', 'N/A')}ms",
                        f"{stats.get('avg', 'N/A')}ms",
                        f"{stats.get('max', 'N/A')}ms"
                    )
        
        # Print the table
        self.console.print(table)
        
        # Print summary statistics
        if 'results' in result:
            total_probes = len(result['results'])
            failed_probes = sum(1 for r in result['results'] if r.get('stats', {}).get('loss', 0) > 0)
            avg_latency = sum(r.get('stats', {}).get('avg', 0) for r in result['results']) / total_probes if total_probes > 0 else 0
            
            summary = Panel(
                f"[bold]Summary:[/bold]\n"
                f"Total Probes: {total_probes}\n"
                f"Failed Probes: {failed_probes}\n"
                f"Average Latency: {avg_latency:.2f}ms",
                title="Measurement Summary",
                border_style="blue"
            )
            self.console.print(summary)

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
    probe = ICNetProbe()
    last_report_time = None
    
    while True:
        current_time = datetime.utcnow()
        
        # Run measurements every 4 hours
        probe.run_measurement_cycle()
        
        # Send daily report at the end of each day (UTC)
        if last_report_time is None or current_time.date() > last_report_time.date():
            probe.send_email_report()
            last_report_time = current_time
        
        # Sleep until next measurement cycle (4 hours)
        time.sleep(4 * 60 * 60)  # 4 hours in seconds

if __name__ == "__main__":
    main() 