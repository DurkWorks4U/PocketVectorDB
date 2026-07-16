"""
PocketVectorDB Web Dashboard and User Account Management

Provides user authentication, subscription management, database visualization, and billing portal.
"""

import os
import json
import sqlite3
import hashlib
import secrets
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
from pathlib import Path
from dataclasses import dataclass, asdict
import time

logger = logging.getLogger(__name__)

try:
    from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    logger.warning("Flask not installed. Install with: pip install flask")


@dataclass
class User:
    """User account information"""
    user_id: str
    email: str
    password_hash: str
    tier: str  # free, pro, team
    created_at: float
    last_login: float
    is_active: bool = True

    def to_dict(self):
        return asdict(self)


class DashboardManager:
    """Manages dashboard, user accounts, and subscription portal"""

    def __init__(self, db_path: str = "./dashboard.db", storage_dir: str = "./databases"):
        """
        Initialize dashboard manager.

        Args:
            db_path: Path to dashboard database
            storage_dir: Path to vector databases
        """
        if not FLASK_AVAILABLE:
            raise RuntimeError("Flask is required. Install with: pip install flask")

        self.db_path = Path(db_path)
        self.storage_dir = Path(storage_dir)
        self.app = Flask(__name__)
        self.app.secret_key = os.environ.get('DASHBOARD_SECRET_KEY', secrets.token_hex(32))

        # Configure session
        self.app.config['SESSION_COOKIE_SECURE'] = True
        self.app.config['SESSION_COOKIE_HTTPONLY'] = True
        self.app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
        self.app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

        self._initialize_db()
        self._setup_routes()

        logger.info(f"Dashboard manager initialized with storage: {storage_dir}")

    def _initialize_db(self):
        """Create dashboard database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    tier TEXT NOT NULL DEFAULT 'free',
                    created_at REAL NOT NULL,
                    last_login REAL,
                    is_active BOOLEAN DEFAULT 1
                )
            """)

            # User sessions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    ip_address TEXT,
                    user_agent TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)

            # API keys table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    api_key TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT,
                    created_at REAL NOT NULL,
                    last_used REAL,
                    rate_limit INTEGER,
                    is_active BOOLEAN DEFAULT 1,
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)

            # User databases table (metadata)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_databases (
                    db_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    document_count INTEGER DEFAULT 0,
                    storage_mb REAL DEFAULT 0.0,
                    is_public BOOLEAN DEFAULT 0,
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)

            # Billing events for analytics
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS billing_events (
                    event_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    amount REAL,
                    description TEXT,
                    timestamp REAL NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)

            # Feature flags and user preferences
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id TEXT PRIMARY KEY,
                    theme TEXT DEFAULT 'light',
                    notifications_email BOOLEAN DEFAULT 1,
                    notifications_queries BOOLEAN DEFAULT 1,
                    notifications_storage BOOLEAN DEFAULT 1,
                    preferred_timezone TEXT,
                    updated_at REAL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)

            # Tier limits tracking (enforced on database side too)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tier_limits (
                    tier TEXT PRIMARY KEY,
                    max_documents INTEGER,
                    max_monthly_queries INTEGER,
                    max_storage_mb INTEGER,
                    max_databases INTEGER,
                    api_calls_per_month INTEGER,
                    monthly_price REAL
                )
            """)

            # Insert tier limits
            tier_limits = [
                ('free', 10_000, 100_000, 500, 1, 10_000, 0.0),
                ('pro', 1_000_000, 10_000_000, 10_000, 10, 1_000_000, 9.99),
                ('team', 100_000_000, 1_000_000_000, None, 100, None, 29.99),
            ]

            for tier, docs, queries, storage, dbs, api_calls, price in tier_limits:
                cursor.execute("""
                    INSERT OR REPLACE INTO tier_limits
                    (tier, max_documents, max_monthly_queries, max_storage_mb,
                     max_databases, api_calls_per_month, monthly_price)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (tier, docs, queries, storage, dbs, api_calls, price))

            conn.commit()
            logger.debug("Dashboard database initialized")

        except Exception as e:
            logger.error(f"Failed to initialize dashboard database: {e}")
            raise
        finally:
            conn.close()

    def _hash_password(self, password: str) -> str:
        """Hash password with salt"""
        salt = secrets.token_hex(16)
        password_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return f"{salt}${password_hash.hex()}"

    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify password against hash"""
        try:
            salt, stored_hash = password_hash.split('$')
            password_check = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
            return password_check.hex() == stored_hash
        except Exception:
            return False

    def create_user(self, email: str, password: str) -> Optional[User]:
        """Create new user account"""
        if not email or not password or len(password) < 8:
            return None

        user_id = f"user_{secrets.token_hex(8)}"
        password_hash = self._hash_password(password)
        now = time.time()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO users (user_id, email, password_hash, tier, created_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, email, password_hash, 'free', now, True))

            # Create user preferences
            cursor.execute("""
                INSERT INTO user_preferences (user_id, updated_at)
                VALUES (?, ?)
            """, (user_id, now))

            conn.commit()
            logger.info(f"Created new user: {user_id} ({email})")

            return User(
                user_id=user_id,
                email=email,
                password_hash=password_hash,
                tier='free',
                created_at=now,
                last_login=now,
                is_active=True
            )

        except sqlite3.IntegrityError:
            logger.warning(f"Email already registered: {email}")
            return None
        finally:
            conn.close()

    def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """Authenticate user and update last login"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            row = cursor.fetchone()

            if not row:
                return None

            user_id, email_stored, password_hash, tier, created_at, last_login, is_active = row

            if not is_active or not self._verify_password(password, password_hash):
                return None

            # Update last login
            now = time.time()
            cursor.execute("UPDATE users SET last_login = ? WHERE user_id = ?", (now, user_id))
            conn.commit()

            return User(
                user_id=user_id,
                email=email_stored,
                password_hash=password_hash,
                tier=tier,
                created_at=created_at,
                last_login=now,
                is_active=bool(is_active)
            )

        finally:
            conn.close()

    def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()

            if not row:
                return None

            user_id, email, password_hash, tier, created_at, last_login, is_active = row

            return User(
                user_id=user_id,
                email=email,
                password_hash=password_hash,
                tier=tier,
                created_at=created_at,
                last_login=last_login,
                is_active=bool(is_active)
            )

        finally:
            conn.close()

    def generate_api_key(self, user_id: str, name: str = None) -> Optional[str]:
        """Generate new API key for user"""
        user = self.get_user(user_id)
        if not user:
            return None

        api_key = f"pk_{secrets.token_urlsafe(32)}"
        now = time.time()

        # Tier-based rate limits
        rate_limits = {
            'free': 100,
            'pro': 10_000,
            'team': 100_000,
        }

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO api_keys (api_key, user_id, name, created_at, rate_limit, is_active)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (api_key, user_id, name or 'Default', now, rate_limits.get(user.tier, 100), True))

            conn.commit()
            logger.info(f"Generated API key for {user_id}")
            return api_key

        finally:
            conn.close()

    def get_user_billing_summary(self, user_id: str) -> Dict:
        """Get comprehensive billing summary for user dashboard"""
        from billing import BillingManager

        user = self.get_user(user_id)
        if not user:
            return {}

        billing = BillingManager()
        subscription = billing.get_subscription(user_id)
        current_bill = billing.calculate_monthly_bill(user_id)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Get user databases
            cursor.execute("""
                SELECT COUNT(*), SUM(storage_mb) FROM user_databases
                WHERE user_id = ?
            """, (user_id,))
            db_row = cursor.fetchone()
            db_count = db_row[0] if db_row[0] else 0
            total_storage = db_row[1] if db_row[1] else 0.0

            # Get tier limits
            cursor.execute("""
                SELECT max_documents, max_monthly_queries, max_storage_mb, max_databases
                FROM tier_limits WHERE tier = ?
            """, (user.tier,))
            limits_row = cursor.fetchone()

            limits = {
                'max_documents': limits_row[0] if limits_row else None,
                'max_queries': limits_row[1] if limits_row else None,
                'max_storage_mb': limits_row[2] if limits_row else None,
                'max_databases': limits_row[3] if limits_row else None,
            }

            return {
                'user_id': user_id,
                'email': user.email,
                'tier': user.tier,
                'tier_name': user.tier.upper(),
                'subscription_active': subscription.is_active() if subscription else False,
                'days_until_renewal': subscription.days_until_renewal() if subscription else 0,
                'auto_renew': subscription.auto_renew if subscription else False,
                'base_amount': current_bill.get('base_amount', 0.0),
                'usage_charges': current_bill.get('usage_charges', 0.0),
                'total_amount': current_bill.get('total_amount', 0.0),
                'databases': db_count,
                'storage_mb': total_storage,
                'limits': limits,
                'storage_percentage': (total_storage / limits['max_storage_mb'] * 100) if limits['max_storage_mb'] else 0,
                'created_at': datetime.fromtimestamp(user.created_at).isoformat(),
            }

        finally:
            conn.close()

    def _setup_routes(self):
        """Setup dashboard routes"""

        # HTML template for dashboard
        DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PocketVectorDB Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .container {
            width: 100%;
            max-width: 1200px;
            padding: 20px;
        }

        .dashboard-header {
            background: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }

        .dashboard-header h1 {
            color: #667eea;
            margin-bottom: 10px;
        }

        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }

        .card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            border-left: 4px solid #667eea;
        }

        .card h2 {
            color: #333;
            font-size: 16px;
            margin-bottom: 15px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .card-value {
            font-size: 32px;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 5px;
        }

        .card-label {
            color: #666;
            font-size: 14px;
        }

        .progress-bar {
            width: 100%;
            height: 8px;
            background: #eee;
            border-radius: 4px;
            margin-top: 10px;
            overflow: hidden;
        }

        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #667eea, #764ba2);
            border-radius: 4px;
        }

        .tier-badge {
            display: inline-block;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 15px;
        }

        .tier-free {
            background: #e3f2fd;
            color: #1976d2;
        }

        .tier-pro {
            background: #f3e5f5;
            color: #7b1fa2;
        }

        .tier-team {
            background: #e8f5e9;
            color: #388e3c;
        }

        .action-buttons {
            display: flex;
            gap: 10px;
            margin-top: 15px;
        }

        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.3s;
        }

        .btn-primary {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
        }

        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 12px rgba(102, 126, 234, 0.4);
        }

        .btn-secondary {
            background: #f5f5f5;
            color: #333;
            border: 1px solid #ddd;
        }

        .btn-secondary:hover {
            background: #eee;
        }

        .alert {
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 15px;
            border-left: 4px solid;
        }

        .alert-warning {
            background: #fff3cd;
            border-color: #ffc107;
            color: #856404;
        }

        .alert-info {
            background: #d1ecf1;
            border-color: #17a2b8;
            color: #0c5460;
        }

        .feature-list {
            list-style: none;
            padding: 0;
        }

        .feature-list li {
            padding: 8px 0;
            border-bottom: 1px solid #eee;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .feature-list li:last-child {
            border-bottom: none;
        }

        .feature-name {
            color: #333;
        }

        .feature-value {
            font-weight: 600;
            color: #667eea;
        }

        .feature-limit {
            color: #999;
            font-size: 12px;
        }

        @media (max-width: 768px) {
            .dashboard-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="dashboard-header">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <h1>📊 PocketVectorDB Dashboard</h1>
                    <p style="color: #666; margin-top: 5px;">Welcome back! Manage your vector databases</p>
                </div>
                <button class="btn btn-secondary" onclick="logout()">Logout</button>
            </div>
        </div>

        <div class="dashboard-grid">
            <div class="card">
                <h2>Subscription</h2>
                <div class="tier-badge" id="tier-badge">FREE</div>
                <div class="card-value" id="renewal-days">30</div>
                <div class="card-label">Days until renewal</div>
                <div class="action-buttons">
                    <button class="btn btn-primary" onclick="showUpgrade()">Upgrade Plan</button>
                </div>
            </div>

            <div class="card">
                <h2>Storage Usage</h2>
                <div class="card-value" id="storage-used">0</div>
                <div class="card-label" id="storage-limit">MB / Unlimited</div>
                <div class="progress-bar">
                    <div class="progress-fill" id="storage-progress" style="width: 0%"></div>
                </div>
            </div>

            <div class="card">
                <h2>Databases</h2>
                <div class="card-value" id="db-count">0</div>
                <div class="card-label" id="db-limit">/ 1 allowed</div>
                <div class="action-buttons">
                    <button class="btn btn-primary" onclick="showNewDatabase()">+ New Database</button>
                </div>
            </div>

            <div class="card">
                <h2>Monthly Bill</h2>
                <div class="card-value" id="monthly-bill">$0.00</div>
                <div class="card-label">This month's charges</div>
                <div class="action-buttons">
                    <button class="btn btn-secondary" onclick="showBilling()">View Invoices</button>
                </div>
            </div>
        </div>

        <div id="alert-container"></div>

        <div class="dashboard-grid">
            <div class="card" style="grid-column: span 2;">
                <h2>Your Tier Limits</h2>
                <ul class="feature-list" id="tier-features">
                    <li>
                        <span class="feature-name">Max Documents</span>
                        <span class="feature-value" id="limit-docs">10,000</span>
                    </li>
                    <li>
                        <span class="feature-name">Monthly Queries</span>
                        <span class="feature-value" id="limit-queries">100,000</span>
                    </li>
                    <li>
                        <span class="feature-name">Storage</span>
                        <span class="feature-value" id="limit-storage">500 MB</span>
                    </li>
                    <li>
                        <span class="feature-name">API Access</span>
                        <span class="feature-value">Coming Soon</span>
                    </li>
                </ul>
            </div>

            <div class="card">
                <h2>Quick Actions</h2>
                <div style="display: flex; flex-direction: column; gap: 10px;">
                    <button class="btn btn-secondary" onclick="showAPIKeys()">Manage API Keys</button>
                    <button class="btn btn-secondary" onclick="showSettings()">Account Settings</button>
                    <button class="btn btn-secondary" onclick="showHelp()">Documentation</button>
                </div>
            </div>
        </div>

        <div class="card" style="margin-top: 20px;">
            <h2>Upgrade to PRO</h2>
            <p style="color: #666; margin-bottom: 15px;">Get unlimited local storage, cloud backups, REST API access, and priority support.</p>
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 15px;">
                <div style="background: #f9f9f9; padding: 15px; border-radius: 5px;">
                    <div style="font-weight: 600; margin-bottom: 5px;">10 GB Storage</div>
                    <div style="color: #999; font-size: 12px;">Cloud backup</div>
                </div>
                <div style="background: #f9f9f9; padding: 15px; border-radius: 5px;">
                    <div style="font-weight: 600; margin-bottom: 5px;">10M Queries</div>
                    <div style="color: #999; font-size: 12px;">Per month</div>
                </div>
                <div style="background: #f9f9f9; padding: 15px; border-radius: 5px;">
                    <div style="font-weight: 600; margin-bottom: 5px;">REST API</div>
                    <div style="color: #999; font-size: 12px;">Query from anywhere</div>
                </div>
            </div>
            <button class="btn btn-primary" onclick="upgradePro()" style="width: 100%;">
                Upgrade to PRO - $9.99/month
            </button>
        </div>
    </div>

    <script>
        // Load dashboard data
        async function loadDashboard() {
            try {
                const response = await fetch('/api/dashboard/summary', {
                    headers: { 'Accept': 'application/json' }
                });

                if (response.status === 401) {
                    window.location.href = '/login';
                    return;
                }

                const data = await response.json();
                updateDashboard(data);
            } catch (error) {
                console.error('Failed to load dashboard:', error);
            }
        }

        function updateDashboard(data) {
            // Update subscription info
            const tierColors = {
                'free': 'tier-free',
                'pro': 'tier-pro',
                'team': 'tier-team'
            };

            document.getElementById('tier-badge').textContent = data.tier.toUpperCase();
            document.getElementById('tier-badge').className = `tier-badge ${tierColors[data.tier]}`;
            document.getElementById('renewal-days').textContent = data.days_until_renewal;

            // Update storage
            const storageMB = Math.round(data.storage_mb * 100) / 100;
            const storageLimit = data.limits.max_storage_mb ? `${data.limits.max_storage_mb}` : '∞';
            document.getElementById('storage-used').textContent = storageMB;
            document.getElementById('storage-limit').textContent = `MB / ${storageLimit} MB`;

            const storagePercent = Math.min(data.storage_percentage, 100);
            document.getElementById('storage-progress').style.width = storagePercent + '%';

            if (storagePercent > 90) {
                showAlert('warning', '⚠️ Storage nearly full! Consider upgrading your plan.');
            }

            // Update databases
            document.getElementById('db-count').textContent = data.databases;
            document.getElementById('db-limit').textContent = `/ ${data.limits.max_databases} allowed`;

            // Update billing
            document.getElementById('monthly-bill').textContent = `$${data.total_amount.toFixed(2)}`;

            // Update limits
            document.getElementById('limit-docs').textContent = data.limits.max_documents.toLocaleString();
            document.getElementById('limit-queries').textContent = data.limits.max_queries.toLocaleString();
            const storageText = data.limits.max_storage_mb ? `${data.limits.max_storage_mb.toLocaleString()} MB` : 'Unlimited';
            document.getElementById('limit-storage').textContent = storageText;

            // Show upgrade prompts for free tier users
            if (data.tier === 'free' && data.storage_percentage > 70) {
                showAlert('info', '💡 Upgrade to PRO to unlock more storage and features.');
            }
        }

        function showAlert(type, message) {
            const alertContainer = document.getElementById('alert-container');
            const alert = document.createElement('div');
            alert.className = `alert alert-${type}`;
            alert.textContent = message;
            alertContainer.appendChild(alert);

            setTimeout(() => alert.remove(), 5000);
        }

        function upgradePro() {
            window.location.href = '/upgrade?plan=pro';
        }

        function showUpgrade() {
            window.location.href = '/upgrade';
        }

        function showNewDatabase() {
            alert('New database creation UI coming soon');
        }

        function showBilling() {
            window.location.href = '/billing';
        }

        function showAPIKeys() {
            window.location.href = '/settings/api-keys';
        }

        function showSettings() {
            window.location.href = '/settings';
        }

        function showHelp() {
            window.open('https://docs.pocketvectordb.com', '_blank');
        }

        function logout() {
            fetch('/api/auth/logout', { method: 'POST' })
                .then(() => window.location.href = '/login')
                .catch(console.error);
        }

        // Load on page load
        document.addEventListener('DOMContentLoaded', loadDashboard);
    </script>
</body>
</html>"""

        LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PocketVectorDB Login</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .login-container {
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
            width: 100%;
            max-width: 400px;
        }

        .login-container h1 {
            color: #667eea;
            margin-bottom: 10px;
            text-align: center;
        }

        .login-container p {
            color: #666;
            text-align: center;
            margin-bottom: 30px;
            font-size: 14px;
        }

        .form-group {
            margin-bottom: 20px;
        }

        .form-group label {
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: 600;
        }

        .form-group input {
            width: 100%;
            padding: 12px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 14px;
            transition: border-color 0.3s;
        }

        .form-group input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }

        .btn {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            border: none;
            border-radius: 5px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.3s;
        }

        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 12px rgba(102, 126, 234, 0.4);
        }

        .links {
            display: flex;
            justify-content: space-between;
            margin-top: 20px;
            font-size: 14px;
        }

        .links a {
            color: #667eea;
            text-decoration: none;
        }

        .links a:hover {
            text-decoration: underline;
        }

        .alert {
            padding: 12px;
            border-radius: 5px;
            margin-bottom: 20px;
            border-left: 4px solid;
        }

        .alert-error {
            background: #f8d7da;
            border-color: #f5c6cb;
            color: #721c24;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <h1>🎯 PocketVectorDB</h1>
        <p>Sign in to manage your vector databases</p>

        <form onsubmit="handleLogin(event)">
            <div id="alerts"></div>

            <div class="form-group">
                <label>Email</label>
                <input type="email" id="email" required>
            </div>

            <div class="form-group">
                <label>Password</label>
                <input type="password" id="password" required>
            </div>

            <button type="submit" class="btn">Sign In</button>

            <div class="links">
                <a href="/signup">Create Account</a>
                <a href="/forgot-password">Forgot Password?</a>
            </div>
        </form>
    </div>

    <script>
        async function handleLogin(event) {
            event.preventDefault();

            const email = document.getElementById('email').value;
            const password = document.getElementById('password').value;

            try {
                const response = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, password })
                });

                const data = await response.json();

                if (response.ok) {
                    window.location.href = '/dashboard';
                } else {
                    showError(data.error || 'Login failed');
                }
            } catch (error) {
                showError('An error occurred. Please try again.');
            }
        }

        function showError(message) {
            const alerts = document.getElementById('alerts');
            alerts.innerHTML = `<div class="alert alert-error">${message}</div>`;
        }
    </script>
</body>
</html>"""

        @self.app.route('/login', methods=['GET'])
        def login_page():
            return render_template_string(LOGIN_HTML)

        @self.app.route('/dashboard', methods=['GET'])
        def dashboard_page():
            if 'user_id' not in session:
                return redirect(url_for('login_page'))
            return render_template_string(DASHBOARD_HTML)

        @self.app.route('/api/auth/login', methods=['POST'])
        def api_login():
            data = request.get_json()
            email = data.get('email')
            password = data.get('password')

            user = self.authenticate_user(email, password)
            if not user:
                return jsonify({'error': 'Invalid email or password'}), 401

            session['user_id'] = user.user_id
            session['email'] = user.email
            session['tier'] = user.tier
            session.permanent = True

            return jsonify({
                'user_id': user.user_id,
                'email': user.email,
                'tier': user.tier,
                'message': 'Login successful'
            }), 200

        @self.app.route('/api/auth/logout', methods=['POST'])
        def api_logout():
            session.clear()
            return jsonify({'message': 'Logged out'}), 200

        @self.app.route('/api/dashboard/summary', methods=['GET'])
        def dashboard_summary():
            if 'user_id' not in session:
                return jsonify({'error': 'Not authenticated'}), 401

            summary = self.get_user_billing_summary(session['user_id'])
            return jsonify(summary), 200

    def run(self, host: str = '0.0.0.0', port: int = 5001, debug: bool = False):
        """Start the dashboard server"""
        logger.info(f"Starting dashboard on {host}:{port}")
        self.app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PocketVectorDB Dashboard")
    parser.add_argument('--port', type=int, default=5001, help='Dashboard port')
    parser.add_argument('--storage', default='./databases', help='Storage directory')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    dashboard = DashboardManager(storage_dir=args.storage)
    dashboard.run(port=args.port, debug=args.debug)
