"""
Email Notifications System for PocketVectorDB

Sends transactional emails for billing events, usage alerts, and account updates.
"""

import os
import logging
from typing import List, Optional
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

try:
    import smtplib
    SMTP_AVAILABLE = True
except ImportError:
    SMTP_AVAILABLE = False


class EmailNotifier:
    """Sends transactional emails"""

    def __init__(self, smtp_host: Optional[str] = None, smtp_port: int = 587,
                 from_address: Optional[str] = None, smtp_user: Optional[str] = None,
                 smtp_password: Optional[str] = None):
        """
        Initialize email notifier.

        Args:
            smtp_host: SMTP server hostname
            smtp_port: SMTP port
            from_address: Sender email address
            smtp_user: SMTP username
            smtp_password: SMTP password
        """
        self.smtp_host = smtp_host or os.environ.get('SMTP_HOST', 'localhost')
        self.smtp_port = smtp_port
        self.from_address = from_address or os.environ.get('SMTP_FROM', 'noreply@pocketvectordb.com')
        self.smtp_user = smtp_user or os.environ.get('SMTP_USER')
        self.smtp_password = smtp_password or os.environ.get('SMTP_PASSWORD')

        self.enabled = SMTP_AVAILABLE and self.smtp_host != 'localhost'
        if self.enabled:
            logger.info(f"Email notifications enabled ({self.smtp_host})")
        else:
            logger.info("Email notifications disabled (use environment variables to enable)")

    def send_welcome_email(self, email: str, user_id: str) -> bool:
        """Send welcome email to new user"""
        subject = "Welcome to PocketVectorDB! 🎉"

        html = f"""
        <html>
            <body style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
                <h1 style="color: #667eea;">Welcome to PocketVectorDB!</h1>

                <p>Hi there! 👋</p>

                <p>Your account has been created successfully. You're ready to start using PocketVectorDB to store and query your vector embeddings.</p>

                <h2 style="color: #333; margin-top: 30px;">Getting Started</h2>

                <p>Here are the next steps:</p>

                <ol>
                    <li><strong>Install PocketVectorDB:</strong> <code>pip install pocketvectordb</code></li>
                    <li><strong>Create your first database:</strong> <a href="https://docs.pocketvectordb.com">View Tutorial</a></li>
                    <li><strong>Access the cloud features:</strong> <a href="https://dashboard.pocketvectordb.com">Go to Dashboard</a></li>
                </ol>

                <h2 style="color: #333; margin-top: 30px;">Your Account</h2>

                <ul>
                    <li>Tier: <strong>Free</strong></li>
                    <li>Storage: <strong>500 MB</strong></li>
                    <li>Monthly Queries: <strong>100,000</strong></li>
                </ul>

                <p style="margin-top: 30px; color: #666; font-size: 12px;">
                    Questions? Check out our <a href="https://docs.pocketvectordb.com">documentation</a> or reply to this email.
                </p>
            </body>
        </html>
        """

        return self._send_email(email, subject, html)

    def send_storage_warning(self, email: str, storage_mb: float, limit_mb: float) -> bool:
        """Send storage quota warning"""
        percentage = int((storage_mb / limit_mb) * 100)
        subject = f"⚠️ Storage {percentage}% Full"

        html = f"""
        <html>
            <body style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
                <h1 style="color: #ff9800;">Storage Quota Warning</h1>

                <p>Hi,</p>

                <p>Your PocketVectorDB account is using <strong>{storage_mb:.1f} MB of {limit_mb:.0f} MB</strong> ({percentage}%).</p>

                <p style="background: #fff3cd; padding: 15px; border-radius: 5px; border-left: 4px solid #ff9800;">
                    <strong>Action needed:</strong> Upgrade to a higher tier to continue storing data.
                </p>

                <h2 style="color: #333; margin-top: 30px;">Upgrade Options</h2>

                <ul>
                    <li><strong>Pro Tier:</strong> 10 GB storage, $9.99/month</li>
                    <li><strong>Team Tier:</strong> Unlimited storage, $29.99/month</li>
                </ul>

                <p>
                    <a href="https://dashboard.pocketvectordb.com/upgrade"
                       style="background: #667eea; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; display: inline-block;">
                        Upgrade Now
                    </a>
                </p>

                <p style="margin-top: 30px; color: #666; font-size: 12px;">
                    Need help? <a href="mailto:support@pocketvectordb.com">Contact support</a>
                </p>
            </body>
        </html>
        """

        return self._send_email(email, subject, html)

    def send_upgrade_confirmation(self, email: str, tier: str, monthly_price: float) -> bool:
        """Send upgrade confirmation"""
        subject = f"✅ Welcome to PocketVectorDB {tier.upper()}!"

        tier_benefits = {
            'pro': [
                '10 GB cloud storage',
                '10 million monthly queries',
                'REST API access',
                'Query analytics',
                'Priority email support'
            ],
            'team': [
                'Unlimited cloud storage',
                '1 billion monthly queries',
                'REST API + WebSocket',
                'Advanced analytics',
                '1-hour priority support',
                'Team collaboration (5 users)'
            ]
        }

        benefits = '<br>'.join([f'✓ {b}' for b in tier_benefits.get(tier, [])])

        html = f"""
        <html>
            <body style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
                <h1 style="color: #4caf50;">Upgrade Successful!</h1>

                <p>Hi,</p>

                <p>Your account has been upgraded to <strong>{tier.upper()} tier</strong>.</p>

                <h2 style="color: #333; margin-top: 30px;">Your New Benefits</h2>

                <p style="line-height: 1.8;">{benefits}</p>

                <h2 style="color: #333; margin-top: 30px;">Billing</h2>

                <p>
                    <strong>Monthly charge:</strong> ${monthly_price:.2f}<br>
                    <strong>Billing cycle:</strong> Renews on the same day next month<br>
                    <strong>Cancel anytime:</strong> No long-term commitment
                </p>

                <p style="margin-top: 30px; color: #666; font-size: 12px;">
                    Thank you for supporting PocketVectorDB! Questions? <a href="mailto:support@pocketvectordb.com">Contact us</a>
                </p>
            </body>
        </html>
        """

        return self._send_email(email, subject, html)

    def send_invoice(self, email: str, invoice_id: str, amount: float, due_date: str) -> bool:
        """Send invoice email"""
        subject = f"Invoice {invoice_id}"

        html = f"""
        <html>
            <body style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
                <h1>Invoice</h1>

                <p>Invoice ID: <strong>{invoice_id}</strong></p>

                <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                    <tr style="border-bottom: 2px solid #ddd;">
                        <td style="padding: 10px; font-weight: bold;">Amount Due</td>
                        <td style="padding: 10px; text-align: right; font-size: 20px; color: #667eea;">${amount:.2f}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px;">Due Date</td>
                        <td style="padding: 10px; text-align: right;">{due_date}</td>
                    </tr>
                </table>

                <p>
                    <a href="https://dashboard.pocketvectordb.com/billing"
                       style="background: #667eea; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; display: inline-block;">
                        Pay Now
                    </a>
                </p>

                <p style="margin-top: 30px; color: #666; font-size: 12px;">
                    Questions? <a href="mailto:billing@pocketvectordb.com">Contact billing support</a>
                </p>
            </body>
        </html>
        """

        return self._send_email(email, subject, html)

    def send_query_quota_warning(self, email: str, queries_used: int, queries_limit: int) -> bool:
        """Send query quota warning"""
        percentage = int((queries_used / queries_limit) * 100)
        subject = f"⚠️ Monthly Query Quota {percentage}% Used"

        html = f"""
        <html>
            <body style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
                <h1 style="color: #ff9800;">Query Quota Alert</h1>

                <p>Hi,</p>

                <p>Your PocketVectorDB account has used <strong>{queries_used:,} of {queries_limit:,}</strong> monthly queries ({percentage}%).</p>

                <p style="background: #fff3cd; padding: 15px; border-radius: 5px; border-left: 4px solid #ff9800;">
                    <strong>Note:</strong> When you reach your monthly limit, queries will be rate-limited until your next billing cycle.
                </p>

                <p style="margin-top: 30px;">
                    <a href="https://dashboard.pocketvectordb.com"
                       style="background: #667eea; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; display: inline-block;">
                        View Usage Details
                    </a>
                </p>

                <p style="margin-top: 30px; color: #666; font-size: 12px;">
                    Need more queries? Upgrade to a higher tier or <a href="mailto:support@pocketvectordb.com">contact support</a>
                </p>
            </body>
        </html>
        """

        return self._send_email(email, subject, html)

    def _send_email(self, to_address: str, subject: str, html_body: str) -> bool:
        """Send email"""
        if not self.enabled:
            logger.warning(f"Email disabled, would send to {to_address}: {subject}")
            return True

        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.from_address
            msg['To'] = to_address

            # Attach HTML body
            part = MIMEText(html_body, 'html')
            msg.attach(part)

            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                if self.smtp_user and self.smtp_password:
                    server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            logger.info(f"Email sent to {to_address}: {subject}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email to {to_address}: {e}")
            return False


# Singleton instance
_notifier = None


def get_notifier() -> EmailNotifier:
    """Get email notifier singleton"""
    global _notifier
    if _notifier is None:
        _notifier = EmailNotifier()
    return _notifier


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    notifier = EmailNotifier()

    # Test email sending
    test_email = os.environ.get('TEST_EMAIL', 'test@example.com')
    print(f"Sending test email to {test_email}...")
    notifier.send_welcome_email(test_email, 'test_user_123')
