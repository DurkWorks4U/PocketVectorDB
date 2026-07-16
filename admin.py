"""
PocketVectorDB Admin Panel

Provides platform management, analytics, and monitoring for administrators.
Track revenue, user growth, system health, and make business decisions.
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from pathlib import Path
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

try:
    from flask import Flask, render_template_string, request, jsonify, session, redirect
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False


class AdminPanel:
    """Administrative interface for platform monitoring"""

    def __init__(self, dashboard_db: str = "./dashboard.db", billing_db: str = "./billing.db"):
        """
        Initialize admin panel.

        Args:
            dashboard_db: Path to dashboard database
            billing_db: Path to billing database
        """
        if not FLASK_AVAILABLE:
            raise RuntimeError("Flask is required. Install with: pip install flask")

        self.dashboard_db = Path(dashboard_db)
        self.billing_db = Path(billing_db)
        self.app = Flask(__name__)
        self.app.secret_key = 'admin-secret-key'  # Should use environment variable

        self._setup_routes()

    def get_platform_stats(self) -> Dict:
        """Get comprehensive platform statistics"""
        conn_dash = sqlite3.connect(self.dashboard_db)
        conn_bill = sqlite3.connect(self.billing_db)
        cursor_dash = conn_dash.cursor()
        cursor_bill = conn_bill.cursor()

        try:
            # User metrics
            cursor_dash.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
            active_users = cursor_dash.fetchone()[0] or 0

            cursor_dash.execute("SELECT COUNT(*) FROM users")
            total_users = cursor_dash.fetchone()[0] or 0

            cursor_dash.execute("""
                SELECT COUNT(*) FROM users
                WHERE created_at > ?
            """, (time.time() - 86400 * 7,))  # Last 7 days
            new_users_week = cursor_dash.fetchone()[0] or 0

            # Subscription metrics
            cursor_bill.execute("SELECT tier, COUNT(*) FROM subscriptions GROUP BY tier")
            tier_breakdown = dict(cursor_bill.fetchall())

            # Revenue metrics
            cursor_bill.execute("""
                SELECT SUM(amount) FROM invoices
                WHERE status = 'paid' AND billing_month = ?
            """, (datetime.now().strftime("%Y-%m"),))
            mrr_paid = cursor_bill.fetchone()[0] or 0.0

            cursor_bill.execute("""
                SELECT SUM(monthly_price) FROM subscriptions
                WHERE status = 'active'
            """)
            mrr_recurring = cursor_bill.fetchone()[0] or 0.0

            cursor_bill.execute("""
                SELECT COUNT(DISTINCT user_id), SUM(total_amount)
                FROM invoices
                WHERE status IN ('draft', 'paid')
            """)
            invoice_row = cursor_bill.fetchone()
            invoiced_users = invoice_row[0] or 0
            total_invoiced = invoice_row[1] or 0.0

            # Database metrics
            cursor_dash.execute("""
                SELECT COUNT(*), SUM(document_count), SUM(storage_mb)
                FROM user_databases
            """)
            db_row = cursor_dash.fetchone()
            total_databases = db_row[0] or 0
            total_documents = db_row[1] or 0
            total_storage_mb = db_row[2] or 0.0

            # Churn calculation (users inactive for 30 days)
            cursor_dash.execute("""
                SELECT COUNT(DISTINCT user_id) FROM users
                WHERE last_login < ? AND is_active = 1
            """, (time.time() - 86400 * 30,))
            churned_users = cursor_dash.fetchone()[0] or 0

            churn_rate = (churned_users / active_users * 100) if active_users > 0 else 0.0

            # API key metrics
            cursor_dash.execute("SELECT COUNT(*) FROM api_keys WHERE is_active = 1")
            active_api_keys = cursor_dash.fetchone()[0] or 0

            return {
                'users': {
                    'total': total_users,
                    'active': active_users,
                    'new_this_week': new_users_week,
                    'churned': churned_users,
                    'churn_rate': round(churn_rate, 2),
                },
                'subscriptions': {
                    'free': tier_breakdown.get('free', 0),
                    'pro': tier_breakdown.get('pro', 0),
                    'team': tier_breakdown.get('team', 0),
                    'total_paid_tiers': tier_breakdown.get('pro', 0) + tier_breakdown.get('team', 0),
                },
                'revenue': {
                    'mrr_paid': round(mrr_paid, 2),
                    'mrr_recurring': round(mrr_recurring, 2),
                    'total_invoiced': round(total_invoiced, 2),
                    'invoiced_users': invoiced_users,
                    'annual_recurring': round(mrr_recurring * 12, 2),
                },
                'databases': {
                    'total': total_databases,
                    'total_documents': total_documents,
                    'total_storage_mb': round(total_storage_mb, 2),
                    'storage_gb': round(total_storage_mb / 1024, 2),
                },
                'api': {
                    'active_keys': active_api_keys,
                },
                'timestamp': datetime.now().isoformat(),
            }

        finally:
            conn_dash.close()
            conn_bill.close()

    def get_revenue_forecast(self, months: int = 12) -> List[Dict]:
        """Project future revenue based on current trends"""
        conn = sqlite3.connect(self.billing_db)
        cursor = conn.cursor()

        try:
            forecast = []

            cursor.execute("""
                SELECT billing_month, SUM(total_amount)
                FROM invoices
                WHERE status IN ('paid', 'draft')
                GROUP BY billing_month
                ORDER BY billing_month DESC
                LIMIT 3
            """)

            historical = cursor.fetchall()

            if len(historical) < 2:
                return forecast

            # Simple linear regression on recent months
            recent_values = [row[1] for row in reversed(historical)]
            trend = (recent_values[-1] - recent_values[0]) / len(recent_values) if len(recent_values) > 1 else 0

            now = datetime.now()
            last_mrr = recent_values[-1] if recent_values else 0

            for i in range(1, months + 1):
                forecast_month = now + timedelta(days=30 * i)
                projected_mrr = last_mrr + (trend * i)

                forecast.append({
                    'month': forecast_month.strftime("%Y-%m"),
                    'projected_mrr': round(max(0, projected_mrr), 2),
                    'confidence': max(0.5, 1.0 - (i * 0.05)),  # Decrease confidence over time
                })

            return forecast

        finally:
            conn.close()

    def get_cohort_analysis(self) -> Dict:
        """Analyze user cohorts by signup month"""
        conn_dash = sqlite3.connect(self.dashboard_db)
        conn_bill = sqlite3.connect(self.billing_db)
        cursor_dash = conn_dash.cursor()
        cursor_bill = conn_bill.cursor()

        try:
            cohorts = {}

            cursor_dash.execute("""
                SELECT
                    strftime('%Y-%m', datetime(created_at, 'unixepoch')),
                    COUNT(*),
                    SUM(CASE WHEN tier != 'free' THEN 1 ELSE 0 END)
                FROM users
                GROUP BY strftime('%Y-%m', datetime(created_at, 'unixepoch'))
                ORDER BY strftime('%Y-%m', datetime(created_at, 'unixepoch'))
            """)

            for cohort_month, total, paid in cursor_dash.fetchall():
                conversion_rate = (paid / total * 100) if total > 0 else 0

                cohorts[cohort_month] = {
                    'total_users': total,
                    'paid_users': paid,
                    'free_users': total - paid,
                    'conversion_rate': round(conversion_rate, 2),
                }

            return cohorts

        finally:
            conn_dash.close()
            conn_bill.close()

    def _setup_routes(self):
        """Setup admin routes"""

        ADMIN_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>PocketVectorDB Admin</title>
    <style>
        body {
            font-family: system-ui, -apple-system, sans-serif;
            background: #1a1a1a;
            color: #fff;
            margin: 0;
            padding: 20px;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
        }

        h1 {
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .metric {
            background: #2a2a2a;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }

        .metric-value {
            font-size: 32px;
            font-weight: bold;
            color: #667eea;
        }

        .metric-label {
            color: #aaa;
            font-size: 14px;
            margin-top: 5px;
        }

        .metric.warning {
            border-left-color: #ff9800;
        }

        .metric.success {
            border-left-color: #4caf50;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            background: #2a2a2a;
            border-radius: 8px;
            overflow: hidden;
        }

        th {
            background: #1a1a1a;
            padding: 12px;
            text-align: left;
            border-bottom: 2px solid #444;
        }

        td {
            padding: 12px;
            border-bottom: 1px solid #444;
        }

        tr:hover {
            background: #333;
        }

        .alert {
            background: #ff5252;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }

        .section {
            margin-bottom: 40px;
        }

        .loading {
            text-align: center;
            color: #aaa;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Admin Dashboard</h1>

        <div id="stats" class="grid">
            <div class="metric">
                <div class="metric-value" id="active-users">-</div>
                <div class="metric-label">Active Users</div>
            </div>
            <div class="metric">
                <div class="metric-value" id="mrr">-</div>
                <div class="metric-label">MRR (Recurring)</div>
            </div>
            <div class="metric">
                <div class="metric-value" id="arr">-</div>
                <div class="metric-label">ARR (Annual)</div>
            </div>
            <div class="metric success">
                <div class="metric-value" id="conversion">-</div>
                <div class="metric-label">Conversion Rate</div>
            </div>
            <div class="metric">
                <div class="metric-value" id="total-docs">-</div>
                <div class="metric-label">Total Documents</div>
            </div>
            <div class="metric warning" id="churn-metric">
                <div class="metric-value" id="churn-rate">-</div>
                <div class="metric-label">Churn Rate (30d)</div>
            </div>
        </div>

        <div class="section">
            <h2>Tier Distribution</h2>
            <table>
                <tr>
                    <th>Tier</th>
                    <th>Users</th>
                    <th>Monthly Revenue</th>
                    <th>% of Paying</th>
                </tr>
                <tbody id="tier-table"></tbody>
            </table>
        </div>

        <div class="section">
            <h2>Revenue Forecast (Next 12 Months)</h2>
            <table>
                <tr>
                    <th>Month</th>
                    <th>Projected MRR</th>
                    <th>Confidence</th>
                </tr>
                <tbody id="forecast-table"></tbody>
            </table>
        </div>

        <div class="section">
            <h2>Cohort Analysis</h2>
            <table>
                <tr>
                    <th>Signup Month</th>
                    <th>Total Users</th>
                    <th>Paid Users</th>
                    <th>Conversion Rate</th>
                </tr>
                <tbody id="cohort-table"></tbody>
            </table>
        </div>

        <div style="text-align: center; color: #666; margin-top: 40px;">
            <p>Last updated: <span id="last-update">-</span></p>
            <p><a href="/logout" style="color: #667eea;">Logout</a></p>
        </div>
    </div>

    <script>
        async function loadAdminStats() {
            try {
                const response = await fetch('/api/admin/stats');
                const data = await response.json();

                // Update metrics
                document.getElementById('active-users').textContent = data.users.active.toLocaleString();
                document.getElementById('mrr').textContent = '$' + data.revenue.mrr_recurring.toFixed(0);
                document.getElementById('arr').textContent = '$' + data.revenue.annual_recurring.toFixed(0);
                document.getElementById('total-docs').textContent = (data.databases.total_documents / 1000000).toFixed(1) + 'M';
                document.getElementById('churn-rate').textContent = data.users.churn_rate.toFixed(1) + '%';

                const totalPaid = data.subscriptions.total_paid_tiers;
                const totalUsers = data.users.total;
                const conversion = (totalPaid / totalUsers * 100).toFixed(1);
                document.getElementById('conversion').textContent = conversion + '%';

                // Update tables
                updateTierTable(data);
                loadForecast();
                loadCohorts();

                document.getElementById('last-update').textContent = new Date().toLocaleTimeString();
            } catch (error) {
                console.error('Failed to load stats:', error);
            }
        }

        function updateTierTable(data) {
            const tbody = document.getElementById('tier-table');
            const totalPaid = data.subscriptions.total_paid_tiers;
            const tiers = [
                ['Free', data.subscriptions.free, 0],
                ['Pro', data.subscriptions.pro, 9.99],
                ['Team', data.subscriptions.team, 29.99],
            ];

            tbody.innerHTML = tiers.map(([name, users, price]) => {
                const revenue = users * price;
                const pct = totalPaid > 0 ? ((users / totalPaid) * 100).toFixed(1) : 0;
                return `
                    <tr>
                        <td>${name}</td>
                        <td>${users}</td>
                        <td>$${revenue.toFixed(2)}</td>
                        <td>${name === 'Free' ? '-' : pct + '%'}</td>
                    </tr>
                `;
            }).join('');
        }

        async function loadForecast() {
            try {
                const response = await fetch('/api/admin/forecast');
                const data = await response.json();

                const tbody = document.getElementById('forecast-table');
                tbody.innerHTML = data.map(item => `
                    <tr>
                        <td>${item.month}</td>
                        <td>$${item.projected_mrr.toFixed(2)}</td>
                        <td>${(item.confidence * 100).toFixed(0)}%</td>
                    </tr>
                `).join('');
            } catch (error) {
                console.error('Failed to load forecast:', error);
            }
        }

        async function loadCohorts() {
            try {
                const response = await fetch('/api/admin/cohorts');
                const data = await response.json();

                const tbody = document.getElementById('cohort-table');
                tbody.innerHTML = Object.entries(data).map(([month, cohort]) => `
                    <tr>
                        <td>${month}</td>
                        <td>${cohort.total_users}</td>
                        <td>${cohort.paid_users}</td>
                        <td>${cohort.conversion_rate}%</td>
                    </tr>
                `).join('');
            } catch (error) {
                console.error('Failed to load cohorts:', error);
            }
        }

        document.addEventListener('DOMContentLoaded', loadAdminStats);
        setInterval(loadAdminStats, 300000);  // Refresh every 5 minutes
    </script>
</body>
</html>"""

        @self.app.route('/admin', methods=['GET'])
        def admin_dashboard():
            return render_template_string(ADMIN_HTML)

        @self.app.route('/api/admin/stats', methods=['GET'])
        def admin_stats():
            stats = self.get_platform_stats()
            return jsonify(stats), 200

        @self.app.route('/api/admin/forecast', methods=['GET'])
        def admin_forecast():
            forecast = self.get_revenue_forecast()
            return jsonify(forecast), 200

        @self.app.route('/api/admin/cohorts', methods=['GET'])
        def admin_cohorts():
            cohorts = self.get_cohort_analysis()
            return jsonify(cohorts), 200

    def run(self, host: str = '0.0.0.0', port: int = 5002, debug: bool = False):
        """Start admin panel"""
        logger.info(f"Starting admin panel on {host}:{port}")
        self.app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PocketVectorDB Admin Panel")
    parser.add_argument('--port', type=int, default=5002, help='Admin port')
    parser.add_argument('--debug', action='store_true', help='Debug mode')

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    admin = AdminPanel()
    admin.run(port=args.port, debug=args.debug)
