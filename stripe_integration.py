"""
Stripe Payment Integration for PocketVectorDB

Handles payment processing, webhook validation, and billing automation.
"""

import os
import json
import logging
import hashlib
import hmac
from typing import Optional, Dict
import time

logger = logging.getLogger(__name__)

try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False
    logger.warning("Stripe not installed. Install with: pip install stripe")


class StripeManager:
    """Manages Stripe payments and billing webhooks"""

    def __init__(self, api_key: Optional[str] = None, webhook_secret: Optional[str] = None):
        """
        Initialize Stripe manager.

        Args:
            api_key: Stripe secret API key
            webhook_secret: Stripe webhook secret for signature verification
        """
        self.api_key = api_key or os.environ.get('STRIPE_SECRET_KEY')
        self.webhook_secret = webhook_secret or os.environ.get('STRIPE_WEBHOOK_SECRET')

        if self.api_key and STRIPE_AVAILABLE:
            stripe.api_key = self.api_key
            self.enabled = True
            logger.info("Stripe integration enabled")
        else:
            self.enabled = False
            logger.warning("Stripe not configured or not available")

    def create_customer(self, email: str, user_id: str) -> Optional[str]:
        """Create Stripe customer"""
        if not self.enabled:
            return None

        try:
            customer = stripe.Customer.create(
                email=email,
                metadata={'user_id': user_id}
            )
            return customer.id
        except Exception as e:
            logger.error(f"Failed to create Stripe customer: {e}")
            return None

    def create_subscription(self, customer_id: str, price_id: str) -> Optional[str]:
        """Create Stripe subscription"""
        if not self.enabled:
            return None

        try:
            subscription = stripe.Subscription.create(
                customer=customer_id,
                items=[{'price': price_id}],
                payment_behavior='default_incomplete',
                expand=['latest_invoice.payment_intent']
            )
            return subscription.id
        except Exception as e:
            logger.error(f"Failed to create subscription: {e}")
            return None

    def charge_customer(self, customer_id: str, amount_cents: int, description: str = None) -> Optional[str]:
        """Charge customer one-time"""
        if not self.enabled:
            return None

        try:
            charge = stripe.Charge.create(
                amount=amount_cents,
                currency='usd',
                customer=customer_id,
                description=description
            )
            return charge.id
        except Exception as e:
            logger.error(f"Failed to charge customer: {e}")
            return None

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        """Verify Stripe webhook signature"""
        if not self.webhook_secret:
            return False

        try:
            expected_sig = hmac.new(
                self.webhook_secret.encode(),
                body,
                hashlib.sha256
            ).hexdigest()

            received_sig = signature.split('=')[1] if '=' in signature else ''
            return hmac.compare_digest(expected_sig, received_sig)
        except Exception as e:
            logger.error(f"Failed to verify webhook signature: {e}")
            return False

    def handle_webhook_event(self, event: Dict) -> bool:
        """Handle Stripe webhook event"""
        if not self.enabled:
            return False

        try:
            event_type = event.get('type')

            if event_type == 'customer.subscription.created':
                return self._handle_subscription_created(event)
            elif event_type == 'customer.subscription.updated':
                return self._handle_subscription_updated(event)
            elif event_type == 'customer.subscription.deleted':
                return self._handle_subscription_deleted(event)
            elif event_type == 'invoice.payment_succeeded':
                return self._handle_invoice_paid(event)
            elif event_type == 'invoice.payment_failed':
                return self._handle_invoice_failed(event)
            elif event_type == 'charge.refunded':
                return self._handle_charge_refunded(event)
            else:
                logger.debug(f"Unhandled webhook event type: {event_type}")
                return True

        except Exception as e:
            logger.error(f"Failed to handle webhook event: {e}")
            return False

    def _handle_subscription_created(self, event: Dict) -> bool:
        """Handle subscription.created event"""
        subscription = event.get('data', {}).get('object', {})
        logger.info(f"Subscription created: {subscription.get('id')}")
        return True

    def _handle_subscription_updated(self, event: Dict) -> bool:
        """Handle subscription.updated event"""
        subscription = event.get('data', {}).get('object', {})
        logger.info(f"Subscription updated: {subscription.get('id')}")
        return True

    def _handle_subscription_deleted(self, event: Dict) -> bool:
        """Handle subscription.deleted event"""
        subscription = event.get('data', {}).get('object', {})
        logger.info(f"Subscription deleted: {subscription.get('id')}")
        return True

    def _handle_invoice_paid(self, event: Dict) -> bool:
        """Handle invoice.payment_succeeded event"""
        invoice = event.get('data', {}).get('object', {})
        logger.info(f"Invoice paid: {invoice.get('id')} (${invoice.get('amount_paid')/100})")
        return True

    def _handle_invoice_failed(self, event: Dict) -> bool:
        """Handle invoice.payment_failed event"""
        invoice = event.get('data', {}).get('object', {})
        logger.warning(f"Invoice payment failed: {invoice.get('id')}")
        return True

    def _handle_charge_refunded(self, event: Dict) -> bool:
        """Handle charge.refunded event"""
        charge = event.get('data', {}).get('object', {})
        logger.info(f"Charge refunded: {charge.get('id')}")
        return True

    def list_prices(self) -> Dict[str, str]:
        """List available product prices (for testing)"""
        if not self.enabled:
            return {}

        try:
            prices = stripe.Price.list(limit=100)
            return {
                price.get('nickname', price.get('id')): price.get('id')
                for price in prices.get('data', [])
            }
        except Exception as e:
            logger.error(f"Failed to list prices: {e}")
            return {}


class StripePriceManager:
    """Manages Stripe prices and products for billing tiers"""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize price manager"""
        self.api_key = api_key or os.environ.get('STRIPE_SECRET_KEY')

        if self.api_key and STRIPE_AVAILABLE:
            stripe.api_key = self.api_key
            self.enabled = True
        else:
            self.enabled = False

    def get_or_create_price(self, product_name: str, amount_cents: int, interval: str = 'month') -> Optional[str]:
        """Get or create a recurring price"""
        if not self.enabled:
            return None

        try:
            # Get or create product
            products = stripe.Product.list(limit=100)
            product = None

            for p in products.get('data', []):
                if p.get('name') == product_name:
                    product = p
                    break

            if not product:
                product = stripe.Product.create(name=product_name)

            # Get or create price
            prices = stripe.Price.list(product=product.id, limit=100)

            for price in prices.get('data', []):
                if (price.get('recurring', {}).get('interval') == interval and
                    price.get('unit_amount') == amount_cents):
                    return price.id

            # Create new price
            price = stripe.Price.create(
                product=product.id,
                unit_amount=amount_cents,
                currency='usd',
                recurring={'interval': interval}
            )

            return price.id

        except Exception as e:
            logger.error(f"Failed to get/create price: {e}")
            return None


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Example usage
    manager = StripeManager()

    if not manager.enabled:
        print("Stripe not configured. Set STRIPE_SECRET_KEY environment variable.")
        sys.exit(1)

    # Create price manager and set up pricing
    price_manager = StripePriceManager()

    print("Setting up Stripe pricing...")
    pro_price_id = price_manager.get_or_create_price('Pro Tier', 999, 'month')
    team_price_id = price_manager.get_or_create_price('Team Tier', 2999, 'month')

    print(f"Pro price ID: {pro_price_id}")
    print(f"Team price ID: {team_price_id}")

    print("\nAvailable prices:")
    for name, pid in manager.list_prices().items():
        print(f"  {name}: {pid}")
