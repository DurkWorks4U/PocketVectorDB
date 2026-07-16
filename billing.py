"""
Billing and Monetization System for PocketVectorDB

Manages tier enforcement, usage tracking, billing calculations, and payment handling.
Integrated with Stripe for production billing.
"""

import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
import sqlite3

logger = logging.getLogger(__name__)

# Try to import Stripe (optional for real payments)
try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False
    logger.info("Stripe not installed. Install with: pip install stripe")


@dataclass
class Subscription:
    """User subscription details"""
    user_id: str
    tier: str  # free, pro, team
    status: str  # active, canceled, past_due
    created_at: float
    billing_cycle_start: float
    billing_cycle_end: float
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    monthly_price: float = 0.0
    auto_renew: bool = True

    def is_active(self) -> bool:
        """Check if subscription is currently active"""
        return self.status == "active" and time.time() < self.billing_cycle_end

    def days_until_renewal(self) -> int:
        """Days until next billing cycle"""
        days = (self.billing_cycle_end - time.time()) / 86400
        return max(0, int(days))

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class UsageCharge:
    """Individual usage-based charge"""
    user_id: str
    charge_type: str  # "queries", "storage", "api_calls"
    amount: float
    quantity: int
    unit_price: float
    timestamp: float
    billing_month: str

    def to_dict(self) -> dict:
        return asdict(self)


class BillingManager:
    """Manages billing, subscriptions, and usage tracking"""

    def __init__(self, db_path: str = "./billing.db", stripe_key: Optional[str] = None):
        """
        Initialize billing manager.

        Args:
            db_path: Path to billing database
            stripe_key: Stripe API key for payment processing
        """
        self.db_path = Path(db_path)
        self.stripe_key = stripe_key or os.environ.get('STRIPE_SECRET_KEY')

        if self.stripe_key and STRIPE_AVAILABLE:
            stripe.api_key = self.stripe_key
            self.stripe_enabled = True
        else:
            self.stripe_enabled = False
            logger.warning("Stripe not configured. Billing features limited.")

        self._initialize_db()

        logger.info(f"Billing manager initialized. Stripe: {self.stripe_enabled}")

    def _initialize_db(self):
        """Create billing database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Subscriptions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    user_id TEXT PRIMARY KEY,
                    tier TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    billing_cycle_start REAL NOT NULL,
                    billing_cycle_end REAL NOT NULL,
                    stripe_customer_id TEXT,
                    stripe_subscription_id TEXT,
                    monthly_price REAL DEFAULT 0.0,
                    auto_renew BOOLEAN DEFAULT 1
                )
            """)

            # Usage charges table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usage_charges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    charge_type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit_price REAL NOT NULL,
                    timestamp REAL NOT NULL,
                    billing_month TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES subscriptions(user_id)
                )
            """)

            # Invoices table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS invoices (
                    invoice_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    billing_month TEXT NOT NULL,
                    base_amount REAL,
                    usage_charges REAL,
                    total_amount REAL,
                    status TEXT,
                    created_at REAL,
                    due_date REAL,
                    paid_date REAL,
                    stripe_invoice_id TEXT,
                    FOREIGN KEY(user_id) REFERENCES subscriptions(user_id)
                )
            """)

            # Payment methods table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS payment_methods (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    type TEXT,
                    last_four TEXT,
                    exp_month INTEGER,
                    exp_year INTEGER,
                    is_default BOOLEAN,
                    created_at REAL,
                    stripe_payment_method_id TEXT,
                    FOREIGN KEY(user_id) REFERENCES subscriptions(user_id)
                )
            """)

            conn.commit()
            logger.debug("Billing database initialized")

        except Exception as e:
            logger.error(f"Failed to initialize billing database: {e}")
            raise
        finally:
            conn.close()

    def create_subscription(self, user_id: str, tier: str, stripe_customer_id: Optional[str] = None) -> Subscription:
        """
        Create a new subscription for a user.

        Args:
            user_id: Unique user ID
            tier: Subscription tier (free, pro, team)
            stripe_customer_id: Optional Stripe customer ID for billing

        Returns:
            Subscription object
        """
        # Pricing
        pricing = {
            'free': 0.0,
            'pro': 9.99,
            'team': 29.99,
        }

        if tier not in pricing:
            raise ValueError(f"Invalid tier: {tier}")

        now = time.time()
        billing_cycle_end = now + (30 * 86400)  # 30 days from now

        subscription = Subscription(
            user_id=user_id,
            tier=tier,
            status='active',
            created_at=now,
            billing_cycle_start=now,
            billing_cycle_end=billing_cycle_end,
            stripe_customer_id=stripe_customer_id,
            monthly_price=pricing[tier],
            auto_renew=True,
        )

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                """INSERT OR REPLACE INTO subscriptions
                   (user_id, tier, status, created_at, billing_cycle_start, billing_cycle_end,
                    stripe_customer_id, monthly_price, auto_renew)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (subscription.user_id, subscription.tier, subscription.status,
                 subscription.created_at, subscription.billing_cycle_start,
                 subscription.billing_cycle_end, stripe_customer_id,
                 subscription.monthly_price, subscription.auto_renew)
            )
            conn.commit()
            logger.info(f"Created subscription for {user_id}: tier={tier}")
            return subscription

        finally:
            conn.close()

    def get_subscription(self, user_id: str) -> Optional[Subscription]:
        """Get subscription for user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return Subscription(
                user_id=row[0],
                tier=row[1],
                status=row[2],
                created_at=row[3],
                billing_cycle_start=row[4],
                billing_cycle_end=row[5],
                stripe_customer_id=row[6],
                stripe_subscription_id=row[7],
                monthly_price=row[8],
                auto_renew=row[9],
            )

        finally:
            conn.close()

    def upgrade_tier(self, user_id: str, new_tier: str, stripe_payment_method_id: Optional[str] = None) -> bool:
        """
        Upgrade user to a higher tier.

        Args:
            user_id: User ID
            new_tier: New tier (pro, team)
            stripe_payment_method_id: Optional Stripe payment method for billing

        Returns:
            True if upgrade successful
        """
        subscription = self.get_subscription(user_id)
        if not subscription:
            return False

        pricing = {
            'free': 0.0,
            'pro': 9.99,
            'team': 29.99,
        }

        new_price = pricing.get(new_tier, 0.0)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Calculate prorated amount if upgrading mid-cycle
            days_remaining = subscription.days_until_renewal()
            prorated_charge = (new_price - subscription.monthly_price) * (days_remaining / 30)

            # Charge prorated amount if positive
            if prorated_charge > 0 and self.stripe_enabled and subscription.stripe_customer_id:
                try:
                    stripe.Charge.create(
                        amount=int(prorated_charge * 100),  # Convert to cents
                        currency='usd',
                        customer=subscription.stripe_customer_id,
                        description=f"Upgrade to {new_tier} tier"
                    )
                except Exception as e:
                    logger.error(f"Stripe charge failed: {e}")
                    return False

            # Update subscription
            cursor.execute(
                """UPDATE subscriptions
                   SET tier = ?, monthly_price = ?
                   WHERE user_id = ?""",
                (new_tier, new_price, user_id)
            )
            conn.commit()

            logger.info(f"Upgraded {user_id} to {new_tier} (prorated: ${prorated_charge:.2f})")
            return True

        finally:
            conn.close()

    def record_usage_charge(self, user_id: str, charge_type: str, quantity: int, unit_price: float) -> UsageCharge:
        """
        Record a usage-based charge.

        Args:
            user_id: User ID
            charge_type: Type of charge (queries, storage, api_calls)
            quantity: Quantity used
            unit_price: Price per unit

        Returns:
            UsageCharge object
        """
        now = time.time()
        billing_month = datetime.fromtimestamp(now).strftime("%Y-%m")
        amount = quantity * unit_price

        charge = UsageCharge(
            user_id=user_id,
            charge_type=charge_type,
            amount=amount,
            quantity=quantity,
            unit_price=unit_price,
            timestamp=now,
            billing_month=billing_month,
        )

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                """INSERT INTO usage_charges
                   (user_id, charge_type, amount, quantity, unit_price, timestamp, billing_month)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (charge.user_id, charge.charge_type, charge.amount, charge.quantity,
                 charge.unit_price, charge.timestamp, charge.billing_month)
            )
            conn.commit()
            logger.debug(f"Recorded usage charge for {user_id}: {charge_type}={quantity}")
            return charge

        finally:
            conn.close()

    def calculate_monthly_bill(self, user_id: str, billing_month: Optional[str] = None) -> Dict[str, float]:
        """
        Calculate monthly bill for a user.

        Args:
            user_id: User ID
            billing_month: Month to calculate for (YYYY-MM format, defaults to current)

        Returns:
            Dictionary with base_amount, usage_charges, total_amount
        """
        if not billing_month:
            billing_month = datetime.now().strftime("%Y-%m")

        subscription = self.get_subscription(user_id)
        if not subscription:
            return {'base_amount': 0.0, 'usage_charges': 0.0, 'total_amount': 0.0}

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Get base subscription amount
            base_amount = subscription.monthly_price

            # Get usage charges for the month
            cursor.execute(
                "SELECT SUM(amount) FROM usage_charges WHERE user_id = ? AND billing_month = ?",
                (user_id, billing_month)
            )
            row = cursor.fetchone()
            usage_charges = row[0] if row[0] else 0.0

            total_amount = base_amount + usage_charges

            return {
                'base_amount': base_amount,
                'usage_charges': usage_charges,
                'total_amount': total_amount,
            }

        finally:
            conn.close()

    def generate_invoice(self, user_id: str, billing_month: Optional[str] = None) -> Optional[str]:
        """
        Generate invoice for a user.

        Args:
            user_id: User ID
            billing_month: Month for invoice (defaults to current)

        Returns:
            Invoice ID if successful
        """
        if not billing_month:
            billing_month = datetime.now().strftime("%Y-%m")

        bill = self.calculate_monthly_bill(user_id, billing_month)
        subscription = self.get_subscription(user_id)

        if not subscription:
            return None

        invoice_id = f"inv_{user_id}_{billing_month}"
        now = time.time()
        due_date = now + (14 * 86400)  # Due in 14 days

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                """INSERT OR REPLACE INTO invoices
                   (invoice_id, user_id, billing_month, base_amount, usage_charges,
                    total_amount, status, created_at, due_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (invoice_id, user_id, billing_month, bill['base_amount'],
                 bill['usage_charges'], bill['total_amount'], 'draft', now, due_date)
            )
            conn.commit()
            logger.info(f"Generated invoice {invoice_id} for {user_id}: ${bill['total_amount']:.2f}")
            return invoice_id

        finally:
            conn.close()

    def get_billing_summary(self, user_id: str) -> Dict[str, any]:
        """Get complete billing summary for a user"""
        subscription = self.get_subscription(user_id)
        current_bill = self.calculate_monthly_bill(user_id)

        if not subscription:
            return {}

        return {
            'subscription': subscription.to_dict(),
            'current_billing_month': datetime.now().strftime("%Y-%m"),
            'base_amount': current_bill['base_amount'],
            'usage_charges': current_bill['usage_charges'],
            'total_amount': current_bill['total_amount'],
            'days_until_renewal': subscription.days_until_renewal(),
            'auto_renew': subscription.auto_renew,
        }


# Pricing configuration for easy adjustment
PRICING_CONFIG = {
    'tiers': {
        'free': {
            'monthly_price': 0.0,
            'max_documents': 10_000,
            'max_monthly_queries': 100_000,
            'max_storage_mb': 500,
        },
        'pro': {
            'monthly_price': 9.99,
            'max_documents': 1_000_000,
            'max_monthly_queries': 10_000_000,
            'max_storage_mb': 10_000,
        },
        'team': {
            'monthly_price': 29.99,
            'max_documents': 100_000_000,
            'max_monthly_queries': 1_000_000_000,
            'max_storage_mb': None,  # Unlimited
        },
    },
    'usage_charges': {
        'overage_queries': 0.0001,  # $0.0001 per 1K queries over limit
        'storage': 0.10,  # $0.10 per GB per month over limit
        'api_calls': 0.001,  # $0.001 per API call for enterprise
    },
}
