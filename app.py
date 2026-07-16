"""
PocketVectorDB Production Application

Unified server orchestrating all services:
- Vector database API (api_server.py)
- User dashboard (dashboard.py)
- Admin panel (admin.py)
- Billing system (billing.py)
"""

import os
import sys
import logging
import argparse
import multiprocessing
from pathlib import Path
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def start_api_server(port: int = 5000, storage_dir: str = "./databases"):
    """Start vector database API server"""
    logger.info(f"Starting API server on port {port}...")
    try:
        from api_server import PocketVectorDBAPI
        api = PocketVectorDBAPI(storage_dir=storage_dir)
        api.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        logger.error(f"API server failed: {e}")
        sys.exit(1)


def start_dashboard(port: int = 5001, storage_dir: str = "./databases"):
    """Start user dashboard"""
    logger.info(f"Starting dashboard on port {port}...")
    try:
        from dashboard import DashboardManager
        dashboard = DashboardManager(storage_dir=storage_dir)
        dashboard.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        logger.error(f"Dashboard failed: {e}")
        sys.exit(1)


def start_admin_panel(port: int = 5002):
    """Start admin panel"""
    logger.info(f"Starting admin panel on port {port}...")
    try:
        from admin import AdminPanel
        admin = AdminPanel()
        admin.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        logger.error(f"Admin panel failed: {e}")
        sys.exit(1)


def verify_dependencies():
    """Verify all required dependencies are installed"""
    dependencies = {
        'flask': 'Flask web framework',
        'numpy': 'NumPy for linear algebra',
        'sqlite3': 'SQLite database (built-in)',
    }

    optional_dependencies = {
        'stripe': 'Stripe payment processing',
        'jwt': 'JWT authentication',
    }

    missing = []
    for package, description in dependencies.items():
        try:
            __import__(package)
            logger.info(f"✓ {description}")
        except ImportError:
            logger.error(f"✗ {package} - {description}")
            missing.append(package)

    if missing:
        logger.error(f"\nMissing required dependencies: {', '.join(missing)}")
        logger.error("Install with: pip install " + " ".join(missing))
        return False

    logger.info("\nOptional dependencies:")
    for package, description in optional_dependencies.items():
        try:
            __import__(package)
            logger.info(f"✓ {description}")
        except ImportError:
            logger.warning(f"- {description} (pip install {package})")

    return True


def create_app_config() -> dict:
    """Create application configuration from environment"""
    config = {
        'debug': os.environ.get('DEBUG', 'false').lower() == 'true',
        'host': os.environ.get('HOST', '0.0.0.0'),
        'api_port': int(os.environ.get('API_PORT', 5000)),
        'dashboard_port': int(os.environ.get('DASHBOARD_PORT', 5001)),
        'admin_port': int(os.environ.get('ADMIN_PORT', 5002)),
        'storage_dir': os.environ.get('STORAGE_DIR', './databases'),
        'stripe_key': os.environ.get('STRIPE_SECRET_KEY'),
        'stripe_webhook': os.environ.get('STRIPE_WEBHOOK_SECRET'),
        'smtp_host': os.environ.get('SMTP_HOST', 'localhost'),
        'smtp_from': os.environ.get('SMTP_FROM', 'noreply@pocketvectordb.com'),
    }

    return config


def setup_databases(storage_dir: str) -> bool:
    """Initialize all databases"""
    logger.info("Setting up databases...")

    storage_path = Path(storage_dir)
    storage_path.mkdir(parents=True, exist_ok=True)

    try:
        # Initialize billing database
        from billing import BillingManager
        billing = BillingManager()
        logger.info("✓ Billing database initialized")

        # Initialize dashboard database
        from dashboard import DashboardManager
        dashboard = DashboardManager(storage_dir=storage_dir)
        logger.info("✓ Dashboard database initialized")

        return True

    except Exception as e:
        logger.error(f"Failed to setup databases: {e}")
        return False


class ProductionApp:
    """Production application orchestrator"""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or create_app_config()
        self.processes = []

    def run_single_service(self, service: str):
        """Run single service (useful for containerization)"""
        services = {
            'api': lambda: start_api_server(
                self.config['api_port'],
                self.config['storage_dir']
            ),
            'dashboard': lambda: start_dashboard(
                self.config['dashboard_port'],
                self.config['storage_dir']
            ),
            'admin': lambda: start_admin_panel(
                self.config['admin_port']
            ),
        }

        if service not in services:
            logger.error(f"Unknown service: {service}")
            logger.error(f"Available services: {', '.join(services.keys())}")
            sys.exit(1)

        logger.info(f"Starting {service} service...")
        services[service]()

    def run_all_services(self):
        """Run all services in separate processes"""
        logger.info("Starting PocketVectorDB production application...")
        logger.info(f"Configuration:")
        logger.info(f"  Storage: {self.config['storage_dir']}")
        logger.info(f"  API Port: {self.config['api_port']}")
        logger.info(f"  Dashboard Port: {self.config['dashboard_port']}")
        logger.info(f"  Admin Port: {self.config['admin_port']}")

        # Setup databases
        if not setup_databases(self.config['storage_dir']):
            logger.error("Failed to setup databases")
            sys.exit(1)

        # Start services in separate processes
        services = [
            ('API Server', start_api_server, (self.config['api_port'], self.config['storage_dir'])),
            ('Dashboard', start_dashboard, (self.config['dashboard_port'], self.config['storage_dir'])),
            ('Admin Panel', start_admin_panel, (self.config['admin_port'],)),
        ]

        for name, func, args in services:
            try:
                p = multiprocessing.Process(target=func, args=args, name=name)
                p.start()
                self.processes.append(p)
                logger.info(f"✓ Started {name}")
            except Exception as e:
                logger.error(f"Failed to start {name}: {e}")

        logger.info("\n" + "="*60)
        logger.info("PocketVectorDB is now running!")
        logger.info("="*60)
        logger.info(f"API:       http://localhost:{self.config['api_port']}/health")
        logger.info(f"Dashboard: http://localhost:{self.config['dashboard_port']}/login")
        logger.info(f"Admin:     http://localhost:{self.config['admin_port']}/admin")
        logger.info("="*60)

        try:
            # Wait for processes
            for p in self.processes:
                p.join()
        except KeyboardInterrupt:
            logger.info("\nShutting down...")
            for p in self.processes:
                p.terminate()
            for p in self.processes:
                p.join()
            logger.info("Shutdown complete")


def main():
    parser = argparse.ArgumentParser(
        description='PocketVectorDB Production Application',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all services
  python app.py

  # Run single service (for Docker/containerization)
  python app.py --service api
  python app.py --service dashboard
  python app.py --service admin

  # Custom configuration
  python app.py --api-port 8000 --dashboard-port 8001 --storage ./data

Environment variables:
  DEBUG=true                    Enable debug mode
  API_PORT=5000                 API server port
  DASHBOARD_PORT=5001           Dashboard port
  ADMIN_PORT=5002               Admin panel port
  STORAGE_DIR=./databases       Vector database storage
  STRIPE_SECRET_KEY=sk_...      Stripe API key
  STRIPE_WEBHOOK_SECRET=whsec_  Stripe webhook secret
  SMTP_HOST=smtp.gmail.com      SMTP server
  SMTP_FROM=noreply@...         Sender email address
        """
    )

    parser.add_argument(
        '--service',
        choices=['api', 'dashboard', 'admin'],
        help='Run single service (useful for containerization)'
    )
    parser.add_argument('--api-port', type=int, default=5000, help='API server port')
    parser.add_argument('--dashboard-port', type=int, default=5001, help='Dashboard port')
    parser.add_argument('--admin-port', type=int, default=5002, help='Admin panel port')
    parser.add_argument('--storage', default='./databases', help='Storage directory')
    parser.add_argument('--no-verify-deps', action='store_true', help='Skip dependency verification')

    args = parser.parse_args()

    # Verify dependencies
    if not args.no_verify_deps:
        if not verify_dependencies():
            sys.exit(1)

    # Create configuration
    config = create_app_config()
    config['api_port'] = args.api_port
    config['dashboard_port'] = args.dashboard_port
    config['admin_port'] = args.admin_port
    config['storage_dir'] = args.storage

    # Create and run app
    app = ProductionApp(config)

    if args.service:
        app.run_single_service(args.service)
    else:
        app.run_all_services()


if __name__ == "__main__":
    main()
