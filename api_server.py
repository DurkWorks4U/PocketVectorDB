"""
PocketVectorDB Cloud API Server

Provides REST API access to PocketVectorDB with authentication, rate limiting, and analytics.
Allows users to query and manage their vector databases from anywhere.

Run with:
    python api_server.py --port 5000 --storage ./databases

Environment variables:
    POCKETVECTORDB_PORT: API port (default: 5000)
    POCKETVECTORDB_STORAGE: Storage directory (default: ./databases)
    POCKETVECTORDB_SECRET_KEY: JWT secret key for auth
"""

import os
import json
import logging
import time
from typing import Dict, Any, Optional, List
from functools import wraps
from datetime import datetime, timedelta
import hashlib
import hmac

import numpy as np

logger = logging.getLogger(__name__)

# Try to import Flask (required for API)
try:
    from flask import Flask, request, jsonify
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    logger.warning("Flask not installed. Install with: pip install flask")

# Try to import JWT (optional for auth)
try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False


class APIKey:
    """Simple API key management for tier-based access control"""

    def __init__(self, api_key: str, user_id: str, tier: str, rate_limit: int):
        self.api_key = api_key
        self.user_id = user_id
        self.tier = tier
        self.rate_limit = rate_limit  # queries per minute
        self.created_at = datetime.now()
        self.last_reset = datetime.now()
        self.query_count = 0

    def is_valid(self) -> bool:
        """Check if API key is still valid"""
        # Check rate limit (reset every minute)
        now = datetime.now()
        if (now - self.last_reset).seconds > 60:
            self.query_count = 0
            self.last_reset = now

        if self.query_count >= self.rate_limit:
            return False

        self.query_count += 1
        return True

    def to_dict(self) -> dict:
        return {
            'api_key': self.api_key,
            'user_id': self.user_id,
            'tier': self.tier,
            'rate_limit': self.rate_limit,
            'created_at': self.created_at.isoformat(),
        }


class PocketVectorDBAPI:
    """REST API server for PocketVectorDB"""

    def __init__(self, storage_dir: str = "./databases", secret_key: Optional[str] = None):
        """
        Initialize API server.

        Args:
            storage_dir: Directory to store databases
            secret_key: Secret key for JWT tokens
        """
        if not FLASK_AVAILABLE:
            raise RuntimeError("Flask is required for API server. Install with: pip install flask")

        self.storage_dir = storage_dir
        self.secret_key = secret_key or os.urandom(32)
        self.app = Flask(__name__)

        # Store API keys and databases in memory (for production, use database)
        self.api_keys: Dict[str, APIKey] = {}
        self.databases: Dict[str, Any] = {}

        # Setup routes
        self._setup_routes()

        logger.info(f"PocketVectorDB API initialized with storage: {storage_dir}")

    def _setup_routes(self):
        """Setup API routes"""

        @self.app.route('/health', methods=['GET'])
        def health():
            """Health check endpoint"""
            return jsonify({
                'status': 'healthy',
                'version': '2.0.0',
                'timestamp': datetime.now().isoformat()
            })

        @self.app.route('/api/v1/auth/generate-key', methods=['POST'])
        def generate_api_key():
            """Generate new API key for user"""
            data = request.get_json()
            user_id = data.get('user_id')
            tier = data.get('tier', 'free')  # free, pro, team

            if not user_id:
                return jsonify({'error': 'user_id required'}), 400

            # Simple API key generation
            api_key = hashlib.sha256(f"{user_id}{time.time()}".encode()).hexdigest()

            # Tier-based rate limits
            rate_limits = {
                'free': 100,      # 100 queries/minute
                'pro': 10_000,    # 10K queries/minute
                'team': 100_000,  # 100K queries/minute
            }

            key_obj = APIKey(api_key, user_id, tier, rate_limits.get(tier, 100))
            self.api_keys[api_key] = key_obj

            return jsonify({
                'api_key': api_key,
                'tier': tier,
                'rate_limit': rate_limits.get(tier, 100),
                'message': 'Keep this API key secret!'
            }), 201

        @self.app.route('/api/v1/query', methods=['POST'])
        def query():
            """Query vector database"""
            api_key = request.headers.get('X-API-Key')

            if not api_key or api_key not in self.api_keys:
                return jsonify({'error': 'Invalid API key'}), 401

            # Check rate limit
            key_obj = self.api_keys[api_key]
            if not key_obj.is_valid():
                return jsonify({'error': 'Rate limit exceeded'}), 429

            data = request.get_json()
            database_id = data.get('database_id')
            embedding = data.get('embedding')
            n_results = data.get('n_results', 10)
            where = data.get('where')

            if not database_id or not embedding:
                return jsonify({'error': 'database_id and embedding required'}), 400

            try:
                # Get database
                from pocketvectordb import VectorDB
                db = VectorDB(f"{self.storage_dir}/{key_obj.user_id}/{database_id}", tier=key_obj.tier)

                # Convert embedding to numpy
                query_emb = np.array(embedding, dtype=np.float32)

                # Perform query
                start = time.time()
                results = db.query(query_emb, n_results=n_results, where=where)
                query_time_ms = (time.time() - start) * 1000

                return jsonify({
                    'results': {
                        'ids': results['ids'],
                        'documents': results['documents'],
                        'metadatas': results['metadatas'],
                        'distances': results['distances'],
                    },
                    'query_time_ms': query_time_ms,
                    'tier': key_obj.tier,
                }), 200

            except Exception as e:
                logger.error(f"Query failed: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/v1/add', methods=['POST'])
        def add_document():
            """Add document to database"""
            api_key = request.headers.get('X-API-Key')

            if not api_key or api_key not in self.api_keys:
                return jsonify({'error': 'Invalid API key'}), 401

            key_obj = self.api_keys[api_key]

            data = request.get_json()
            database_id = data.get('database_id')
            embedding = data.get('embedding')
            text = data.get('text')
            metadata = data.get('metadata')

            if not database_id or not embedding:
                return jsonify({'error': 'database_id and embedding required'}), 400

            try:
                from pocketvectordb import VectorDB
                db = VectorDB(f"{self.storage_dir}/{key_obj.user_id}/{database_id}", tier=key_obj.tier)

                query_emb = np.array(embedding, dtype=np.float32)
                doc_id = db.add(query_emb, text=text, metadata=metadata)
                db.save()

                return jsonify({
                    'doc_id': doc_id,
                    'message': 'Document added'
                }), 201

            except Exception as e:
                logger.error(f"Add failed: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/v1/stats', methods=['GET'])
        def stats():
            """Get database statistics"""
            api_key = request.headers.get('X-API-Key')

            if not api_key or api_key not in self.api_keys:
                return jsonify({'error': 'Invalid API key'}), 401

            database_id = request.args.get('database_id')
            if not database_id:
                return jsonify({'error': 'database_id required'}), 400

            try:
                from pocketvectordb import VectorDB
                key_obj = self.api_keys[api_key]
                db = VectorDB(f"{self.storage_dir}/{key_obj.user_id}/{database_id}", tier=key_obj.tier)

                stats = db.get_stats()

                return jsonify({
                    'tier': key_obj.tier,
                    'documents': stats.documents_stored,
                    'documents_limit': stats.documents_limit,
                    'storage_mb': stats.storage_mb,
                    'storage_limit_mb': stats.storage_limit_mb,
                    'queries_this_month': stats.queries_this_month,
                    'queries_limit': stats.queries_limit,
                    'query_percentage': stats.query_percentage,
                    'storage_percentage': stats.storage_percentage,
                }), 200

            except Exception as e:
                logger.error(f"Stats failed: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.errorhandler(404)
        def not_found(error):
            return jsonify({'error': 'Endpoint not found'}), 404

        @self.app.errorhandler(500)
        def server_error(error):
            return jsonify({'error': 'Internal server error'}), 500

    def run(self, host: str = '0.0.0.0', port: int = 5000, debug: bool = False):
        """Start the API server"""
        logger.info(f"Starting API server on {host}:{port}")
        self.app.run(host=host, port=port, debug=debug)


def create_app(storage_dir: str = "./databases", secret_key: Optional[str] = None) -> Flask:
    """Create Flask app for deployment"""
    api = PocketVectorDBAPI(storage_dir, secret_key)
    return api.app


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PocketVectorDB Cloud API Server")
    parser.add_argument('--port', type=int, default=5000, help='API port')
    parser.add_argument('--host', default='0.0.0.0', help='API host')
    parser.add_argument('--storage', default='./databases', help='Storage directory')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    api = PocketVectorDBAPI(storage_dir=args.storage)
    api.run(host=args.host, port=args.port, debug=args.debug)
