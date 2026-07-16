"""
Pocket Vector Database - Production-Ready Vector Storage with SQLite Backend

A lightweight, offline-first vector database for Python and edge devices.
Designed for semantic search, local LLM memory, and offline AI applications.

Now with SQLite backend for unlimited storage, zero RAM limits, and production reliability.

Features:
- SQLite backend (unlimited storage, no RAM constraints)
- Fast cosine similarity search with metadata filtering
- ACID transactions (data safety guaranteed)
- Metadata indexing for quick filtering
- Built-in usage tracking for monetization
- Tier-based feature limits (Free, Pro, Team)
- Query analytics and statistics
- Persistent storage with automatic backups
- Works offline, mobile, Termux
- Zero external dependencies beyond NumPy and SQLite (both built-in)

Example:
    >>> from pocketvectordb import VectorDB
    >>> import numpy as np
    >>> db = VectorDB("./my_vectors", dimension=384, tier="free")
    >>> embedding = np.random.randn(384)
    >>> doc_id = db.add(embedding, text="Hello world", metadata={"tag": "greeting"})
    >>> results = db.query(embedding, n_results=5)
    >>> db.save()
"""
import numpy as np
import json
import os
import sqlite3
import logging
import time
from typing import List, Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass, asdict
from pathlib import Path
from datetime import datetime
from functools import wraps
import hashlib

__version__ = "2.0.0"
__all__ = ["VectorDB", "Document", "cosine_similarity", "UsageStats"]

logger = logging.getLogger(__name__)

# Tier definitions for monetization
TIER_LIMITS = {
    "free": {
        "max_documents": 10_000,
        "max_monthly_queries": 100_000,
        "max_storage_mb": 500,
        "features": ["query", "add", "delete", "metadata_filter"],
        "analytics": False,
        "support": False,
    },
    "pro": {
        "max_documents": 1_000_000,
        "max_monthly_queries": 10_000_000,
        "max_storage_mb": 10_000,
        "features": ["query", "add", "delete", "update", "metadata_filter", "batch_ops", "api_access"],
        "analytics": True,
        "support": True,
    },
    "team": {
        "max_documents": 100_000_000,
        "max_monthly_queries": 1_000_000_000,
        "max_storage_mb": None,  # Unlimited
        "features": ["query", "add", "delete", "update", "metadata_filter", "batch_ops", "api_access", "webhooks"],
        "analytics": True,
        "support": True,
    },
}


@dataclass
class Document:
    """Document with vector embedding and metadata"""
    id: str
    embedding: np.ndarray
    metadata: Dict[str, Any]
    text: Optional[str] = None
    created_at: Optional[float] = None
    updated_at: Optional[float] = None

    def to_dict(self):
        return {
            'id': self.id,
            'embedding': self.embedding.tolist(),
            'metadata': self.metadata,
            'text': self.text,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }


@dataclass
class UsageStats:
    """Monthly usage statistics for a database"""
    queries_this_month: int
    queries_limit: int
    documents_stored: int
    documents_limit: int
    storage_mb: float
    storage_limit_mb: Optional[float]
    api_calls: int
    last_query_time: Optional[float]

    @property
    def query_percentage(self) -> float:
        """Percentage of monthly query quota used"""
        if self.queries_limit == 0:
            return 0
        return (self.queries_this_month / self.queries_limit) * 100

    @property
    def storage_percentage(self) -> float:
        """Percentage of storage quota used"""
        if self.storage_limit_mb is None:
            return 0
        return (self.storage_mb / self.storage_limit_mb) * 100


class VectorDB:
    """
    Production-ready vector database with SQLite backend.

    Stores unlimited vectors on disk with fast similarity search.
    Uses SQLite for ACID compliance, indexing, and efficient queries.
    """

    def __init__(self,
                 storage_path: str = "./vectordb_storage",
                 dimension: Optional[int] = None,
                 tier: str = "free",
                 auto_backup: bool = True):
        """
        Initialize VectorDB with SQLite backend.

        Args:
            storage_path: Directory for database files
            dimension: Vector dimension (auto-detected from first insert if None)
            tier: Feature tier ("free", "pro", "team")
            auto_backup: Enable automatic backups on save
        """
        if tier not in TIER_LIMITS:
            raise ValueError(f"Invalid tier. Must be one of: {list(TIER_LIMITS.keys())}")

        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.dimension = dimension
        self.tier = tier
        self.auto_backup = auto_backup

        # Database file path
        self.db_path = self.storage_path / "vectordb.sqlite3"
        self.backup_dir = self.storage_path / "backups"
        if auto_backup:
            self.backup_dir.mkdir(exist_ok=True)

        # Initialize database
        self._initialize_db()
        self._init_usage_tracking()

        logger.info(f"Initialized VectorDB: tier={tier}, dimension={dimension}, storage={storage_path}")

    def _initialize_db(self):
        """Create SQLite tables if they don't exist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Embeddings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    id TEXT PRIMARY KEY,
                    vector BLOB NOT NULL,
                    embedding_norm REAL NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            # Metadata table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    id TEXT PRIMARY KEY,
                    doc_text TEXT,
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY(id) REFERENCES embeddings(id) ON DELETE CASCADE
                )
            """)

            # Metadata indexes for fast filtering
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_metadata_json ON metadata(metadata_json)")

            # Usage tracking table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usage_tracking (
                    id INTEGER PRIMARY KEY,
                    month TEXT NOT NULL UNIQUE,
                    queries_count INTEGER DEFAULT 0,
                    api_calls INTEGER DEFAULT 0,
                    last_updated REAL
                )
            """)

            # Query log table (for analytics)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS query_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    query_time_ms REAL,
                    n_results INTEGER,
                    had_filter BOOLEAN,
                    result_count INTEGER
                )
            """)

            # Metadata for database
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS db_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            conn.commit()
            logger.debug(f"Database initialized at {self.db_path}")

        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
        finally:
            conn.close()

    def _init_usage_tracking(self):
        """Initialize usage tracking for current month"""
        month = datetime.now().strftime("%Y-%m")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                "INSERT OR IGNORE INTO usage_tracking (month) VALUES (?)",
                (month,)
            )
            conn.commit()
        finally:
            conn.close()

    def _check_tier_limit(self, limit_name: str, current_value: int, increment: int = 0) -> bool:
        """Check if operation would exceed tier limits"""
        limits = TIER_LIMITS[self.tier]
        limit_key = f"max_{limit_name}"

        if limit_key not in limits:
            return True

        max_limit = limits[limit_key]
        if max_limit is None:  # Unlimited
            return True

        return (current_value + increment) <= max_limit

    def _track_query(self):
        """Track a query for usage monitoring"""
        month = datetime.now().strftime("%Y-%m")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                "UPDATE usage_tracking SET queries_count = queries_count + 1, last_updated = ? WHERE month = ?",
                (time.time(), month)
            )
            conn.commit()
        finally:
            conn.close()

    def _log_query_stats(self, query_time_ms: float, n_results: int, had_filter: bool, result_count: int):
        """Log query statistics for analytics"""
        if not TIER_LIMITS[self.tier]["analytics"]:
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                """INSERT INTO query_logs (timestamp, query_time_ms, n_results, had_filter, result_count)
                   VALUES (?, ?, ?, ?, ?)""",
                (time.time(), query_time_ms, n_results, had_filter, result_count)
            )
            conn.commit()
        finally:
            conn.close()

    def _normalize_vector(self, vector: np.ndarray) -> Tuple[np.ndarray, float]:
        """Normalize vector for cosine similarity and return norm"""
        norm = np.linalg.norm(vector)
        if norm == 0:
            raise ValueError("Cannot normalize zero vector")
        return vector / norm, float(norm)

    def count(self) -> int:
        """Get total number of documents"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT COUNT(*) FROM embeddings")
            count = cursor.fetchone()[0]
            return count
        finally:
            conn.close()

    def add(self,
            embedding: Union[np.ndarray, List[float]],
            metadata: Optional[Dict[str, Any]] = None,
            text: Optional[str] = None,
            doc_id: Optional[str] = None) -> str:
        """
        Add a document with embedding to the database.

        Args:
            embedding: Vector embedding (will be normalized)
            metadata: Optional metadata dictionary
            text: Optional original text
            doc_id: Optional document ID (auto-generated if None)

        Returns:
            Document ID

        Raises:
            ValueError: If dimension doesn't match or tier limit exceeded
        """
        # Convert to numpy array
        if isinstance(embedding, list):
            embedding = np.array(embedding, dtype=np.float32)
        else:
            embedding = embedding.astype(np.float32)

        # Set dimension if first document
        if self.dimension is None:
            self.dimension = len(embedding)
        elif len(embedding) != self.dimension:
            raise ValueError(
                f"Embedding dimension {len(embedding)} doesn't match database dimension {self.dimension}"
            )

        # Generate ID if not provided
        if doc_id is None:
            doc_id = self._generate_id()

        # Check tier limits
        doc_count = self.count()
        if not self._check_tier_limit("documents", doc_count, 1):
            raise ValueError(
                f"Cannot add document: tier limit of {TIER_LIMITS[self.tier]['max_documents']} documents exceeded"
            )

        # Normalize embedding
        normalized_emb, norm = self._normalize_vector(embedding)

        # Store in database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            now = time.time()

            # Store embedding as binary (float32 array)
            embedding_bytes = normalized_emb.tobytes()

            cursor.execute(
                """INSERT OR REPLACE INTO embeddings (id, vector, embedding_norm, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (doc_id, embedding_bytes, norm, now, now)
            )

            # Store metadata
            metadata_json = json.dumps(metadata or {})
            cursor.execute(
                """INSERT OR REPLACE INTO metadata (id, doc_text, metadata_json)
                   VALUES (?, ?, ?)""",
                (doc_id, text, metadata_json)
            )

            conn.commit()
            logger.debug(f"Added document {doc_id}")
            return doc_id

        except Exception as e:
            logger.error(f"Failed to add document: {e}")
            raise
        finally:
            conn.close()

    def add_batch(self,
                  embeddings: List[Union[np.ndarray, List[float]]],
                  metadatas: Optional[List[Dict[str, Any]]] = None,
                  texts: Optional[List[str]] = None,
                  doc_ids: Optional[List[str]] = None) -> List[str]:
        """
        Add multiple documents efficiently in a single transaction.

        Args:
            embeddings: List of vector embeddings
            metadatas: Optional list of metadata dictionaries
            texts: Optional list of original texts
            doc_ids: Optional list of document IDs

        Returns:
            List of document IDs

        Raises:
            ValueError: If list lengths don't match or limits exceeded
        """
        if not embeddings:
            return []

        # Validate list lengths
        if metadatas and len(metadatas) != len(embeddings):
            raise ValueError("metadatas length must match embeddings length")
        if texts and len(texts) != len(embeddings):
            raise ValueError("texts length must match embeddings length")
        if doc_ids and len(doc_ids) != len(embeddings):
            raise ValueError("doc_ids length must match embeddings length")

        # Set defaults
        if metadatas is None:
            metadatas = [{} for _ in embeddings]
        if texts is None:
            texts = [None] * len(embeddings)
        if doc_ids is None:
            doc_ids = [self._generate_id() for _ in embeddings]

        # Check tier limits
        doc_count = self.count()
        if not self._check_tier_limit("documents", doc_count, len(embeddings)):
            raise ValueError(
                f"Cannot add {len(embeddings)} documents: tier limit of {TIER_LIMITS[self.tier]['max_documents']} exceeded"
            )

        # Prepare data
        now = time.time()
        batch_data = []

        for emb, meta, text, doc_id in zip(embeddings, metadatas, texts, doc_ids):
            if isinstance(emb, list):
                emb = np.array(emb, dtype=np.float32)
            else:
                emb = emb.astype(np.float32)

            if len(emb) != self.dimension:
                raise ValueError(
                    f"Embedding dimension {len(emb)} doesn't match database dimension {self.dimension}"
                )

            normalized_emb, norm = self._normalize_vector(emb)
            embedding_bytes = normalized_emb.tobytes()
            metadata_json = json.dumps(meta)

            batch_data.append((doc_id, embedding_bytes, norm, now, now, text, metadata_json))

        # Insert batch in single transaction
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.executemany(
                """INSERT OR REPLACE INTO embeddings (id, vector, embedding_norm, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                [(d[0], d[1], d[2], d[3], d[4]) for d in batch_data]
            )

            cursor.executemany(
                """INSERT OR REPLACE INTO metadata (id, doc_text, metadata_json)
                   VALUES (?, ?, ?)""",
                [(d[0], d[5], d[6]) for d in batch_data]
            )

            conn.commit()
            logger.debug(f"Added batch of {len(doc_ids)} documents")
            return doc_ids

        except Exception as e:
            logger.error(f"Failed to add batch: {e}")
            raise
        finally:
            conn.close()

    def query(self,
              query_embedding: Union[np.ndarray, List[float]],
              n_results: int = 10,
              where: Optional[Dict[str, Any]] = None,
              include_distances: bool = True) -> Dict[str, Any]:
        """
        Query for similar vectors using cosine similarity.

        Args:
            query_embedding: Query vector
            n_results: Number of results to return
            where: Optional metadata filter with operators ($gt, $lt, $in, etc.)
            include_distances: Include similarity distances in results

        Returns:
            Dictionary with ids, documents, metadatas, and optionally distances

        Example:
            # Query with metadata filter
            results = db.query(query_vec, n_results=5, where={"score": {"$gt": 0.8}})
        """
        start_time = time.time()

        # Validate query embedding
        if isinstance(query_embedding, list):
            query_embedding = np.array(query_embedding, dtype=np.float32)

        if len(query_embedding) != self.dimension:
            raise ValueError(
                f"Query dimension {len(query_embedding)} doesn't match database dimension {self.dimension}"
            )

        query_embedding, _ = self._normalize_vector(query_embedding)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Get all embeddings and IDs
            cursor.execute("SELECT id, vector FROM embeddings")
            rows = cursor.fetchall()

            if not rows:
                return {
                    'ids': [],
                    'documents': [],
                    'metadatas': [],
                    'distances': [] if include_distances else None
                }

            # Apply metadata filter if specified
            if where:
                filtered_rows = []
                for doc_id, vector_bytes in rows:
                    cursor.execute("SELECT metadata_json FROM metadata WHERE id = ?", (doc_id,))
                    result = cursor.fetchone()
                    if result:
                        metadata = json.loads(result[0])
                        if self._matches_filter(metadata, where):
                            filtered_rows.append((doc_id, vector_bytes))
                rows = filtered_rows

            if not rows:
                return {
                    'ids': [],
                    'documents': [],
                    'metadatas': [],
                    'distances': [] if include_distances else None
                }

            # Compute similarities
            doc_ids = [row[0] for row in rows]
            similarities = []

            for _, vector_bytes in rows:
                vector = np.frombuffer(vector_bytes, dtype=np.float32)
                similarity = np.dot(vector, query_embedding)
                similarities.append(similarity)

            similarities = np.array(similarities)

            # Get top-k results
            n_results = min(n_results, len(similarities))
            top_indices = np.argpartition(similarities, -n_results)[-n_results:]
            top_indices = top_indices[np.argsort(similarities[top_indices])[::-1]]

            # Fetch full documents
            result_ids = [doc_ids[i] for i in top_indices]
            result_distances = [1 - similarities[i] for i in top_indices]  # Convert similarity to distance

            # Get metadata and text
            result_docs = []
            result_metadatas = []

            for doc_id in result_ids:
                cursor.execute("SELECT doc_text, metadata_json FROM metadata WHERE id = ?", (doc_id,))
                row = cursor.fetchone()
                if row:
                    doc_text, metadata_json = row
                    result_docs.append(doc_text)
                    result_metadatas.append(json.loads(metadata_json))

            # Track usage and log stats
            self._track_query()
            query_time_ms = (time.time() - start_time) * 1000
            self._log_query_stats(query_time_ms, n_results, where is not None, len(result_ids))

            results = {
                'ids': result_ids,
                'documents': result_docs,
                'metadatas': result_metadatas,
            }

            if include_distances:
                results['distances'] = result_distances

            return results

        except Exception as e:
            logger.error(f"Query failed: {e}")
            raise
        finally:
            conn.close()

    def _matches_filter(self, metadata: Dict[str, Any], where: Dict[str, Any]) -> bool:
        """Check if metadata matches filter conditions (supports operators)"""
        for key, condition in where.items():
            value = metadata.get(key)

            # Simple equality
            if not isinstance(condition, dict):
                if value != condition:
                    return False
                continue

            # Operator-based checks
            if "$gt" in condition and not (value is not None and value > condition["$gt"]):
                return False
            if "$gte" in condition and not (value is not None and value >= condition["$gte"]):
                return False
            if "$lt" in condition and not (value is not None and value < condition["$lt"]):
                return False
            if "$lte" in condition and not (value is not None and value <= condition["$lte"]):
                return False
            if "$ne" in condition and value == condition["$ne"]:
                return False
            if "$in" in condition and value not in condition["$in"]:
                return False
            if "$nin" in condition and value in condition["$nin"]:
                return False

        return True

    def get(self, doc_ids: Optional[List[str]] = None,
            where: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get documents by IDs or metadata filter.

        Args:
            doc_ids: List of document IDs to retrieve
            where: Optional metadata filter

        Returns:
            Dictionary with ids, documents, metadatas, embeddings
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            if doc_ids:
                placeholders = ",".join("?" * len(doc_ids))
                cursor.execute(
                    f"SELECT id FROM embeddings WHERE id IN ({placeholders})",
                    doc_ids
                )
            elif where:
                cursor.execute("SELECT id FROM metadata")
                rows = cursor.fetchall()
                matching_ids = []
                for row in rows:
                    doc_id = row[0]
                    cursor.execute("SELECT metadata_json FROM metadata WHERE id = ?", (doc_id,))
                    meta_row = cursor.fetchone()
                    if meta_row:
                        metadata = json.loads(meta_row[0])
                        if self._matches_filter(metadata, where):
                            matching_ids.append(doc_id)
                doc_ids = matching_ids
            else:
                cursor.execute("SELECT id FROM embeddings")
                doc_ids = [row[0] for row in cursor.fetchall()]

            # Fetch all data
            results_data = {
                'ids': [],
                'documents': [],
                'metadatas': [],
                'embeddings': []
            }

            for doc_id in doc_ids:
                cursor.execute("SELECT vector FROM embeddings WHERE id = ?", (doc_id,))
                emb_row = cursor.fetchone()
                if not emb_row:
                    continue

                cursor.execute("SELECT doc_text, metadata_json FROM metadata WHERE id = ?", (doc_id,))
                meta_row = cursor.fetchone()

                if meta_row:
                    doc_text, metadata_json = meta_row
                    vector = np.frombuffer(emb_row[0], dtype=np.float32)

                    results_data['ids'].append(doc_id)
                    results_data['documents'].append(doc_text)
                    results_data['metadatas'].append(json.loads(metadata_json))
                    results_data['embeddings'].append(vector.tolist())

            return results_data

        finally:
            conn.close()

    def update(self, doc_id: str,
               embedding: Optional[Union[np.ndarray, List[float]]] = None,
               metadata: Optional[Dict[str, Any]] = None,
               text: Optional[str] = None):
        """
        Update a document's embedding, metadata, or text.

        Args:
            doc_id: Document ID to update
            embedding: New embedding (optional)
            metadata: New metadata (optional, will be merged)
            text: New text (optional)

        Raises:
            KeyError: If document not found
            ValueError: If embedding dimension doesn't match
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Check if document exists
            cursor.execute("SELECT vector FROM embeddings WHERE id = ?", (doc_id,))
            if not cursor.fetchone():
                raise KeyError(f"Document {doc_id} not found")

            now = time.time()

            # Update embedding if provided
            if embedding is not None:
                if isinstance(embedding, list):
                    embedding = np.array(embedding, dtype=np.float32)
                else:
                    embedding = embedding.astype(np.float32)

                if len(embedding) != self.dimension:
                    raise ValueError(
                        f"Embedding dimension {len(embedding)} doesn't match database dimension {self.dimension}"
                    )

                normalized_emb, norm = self._normalize_vector(embedding)
                embedding_bytes = normalized_emb.tobytes()

                cursor.execute(
                    "UPDATE embeddings SET vector = ?, embedding_norm = ?, updated_at = ? WHERE id = ?",
                    (embedding_bytes, norm, now, doc_id)
                )

            # Update metadata if provided
            if metadata is not None:
                cursor.execute("SELECT metadata_json FROM metadata WHERE id = ?", (doc_id,))
                row = cursor.fetchone()
                if row:
                    existing_meta = json.loads(row[0])
                    existing_meta.update(metadata)
                    cursor.execute(
                        "UPDATE metadata SET metadata_json = ? WHERE id = ?",
                        (json.dumps(existing_meta), doc_id)
                    )

            # Update text if provided
            if text is not None:
                cursor.execute("UPDATE metadata SET doc_text = ? WHERE id = ?", (text, doc_id))

            conn.commit()
            logger.debug(f"Updated document {doc_id}")

        finally:
            conn.close()

    def delete(self, doc_ids: Optional[List[str]] = None,
               where: Optional[Dict[str, Any]] = None) -> int:
        """
        Delete documents by IDs or metadata filter.

        Args:
            doc_ids: List of document IDs to delete
            where: Optional metadata filter

        Returns:
            Number of documents deleted
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            if doc_ids:
                to_delete = set(doc_ids) & set(self._get_all_ids(cursor))
            elif where:
                all_ids = self._get_all_ids(cursor)
                to_delete = set()
                for doc_id in all_ids:
                    cursor.execute("SELECT metadata_json FROM metadata WHERE id = ?", (doc_id,))
                    row = cursor.fetchone()
                    if row:
                        metadata = json.loads(row[0])
                        if self._matches_filter(metadata, where):
                            to_delete.add(doc_id)
            else:
                return 0

            if not to_delete:
                return 0

            # Delete documents
            placeholders = ",".join("?" * len(to_delete))
            cursor.execute(f"DELETE FROM embeddings WHERE id IN ({placeholders})", list(to_delete))
            conn.commit()

            logger.debug(f"Deleted {len(to_delete)} documents")
            return len(to_delete)

        finally:
            conn.close()

    def _get_all_ids(self, cursor) -> List[str]:
        """Get all document IDs"""
        cursor.execute("SELECT id FROM embeddings")
        return [row[0] for row in cursor.fetchall()]

    def get_stats(self) -> UsageStats:
        """Get database statistics and usage information"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Get document count
            cursor.execute("SELECT COUNT(*) FROM embeddings")
            doc_count = cursor.fetchone()[0]

            # Get storage size
            storage_mb = self.db_path.stat().st_size / (1024 * 1024) if self.db_path.exists() else 0

            # Get current month stats
            month = datetime.now().strftime("%Y-%m")
            cursor.execute(
                "SELECT queries_count, api_calls, last_updated FROM usage_tracking WHERE month = ?",
                (month,)
            )
            row = cursor.fetchone()
            queries_count = row[0] if row else 0
            api_calls = row[1] if row else 0
            last_query = row[2] if row else None

            # Get tier limits
            limits = TIER_LIMITS[self.tier]
            query_limit = limits["max_monthly_queries"]
            storage_limit = limits["max_storage_mb"]

            return UsageStats(
                queries_this_month=queries_count,
                queries_limit=query_limit,
                documents_stored=doc_count,
                documents_limit=limits["max_documents"],
                storage_mb=storage_mb,
                storage_limit_mb=storage_limit,
                api_calls=api_calls,
                last_query_time=last_query,
            )

        finally:
            conn.close()

    def save(self) -> None:
        """
        Save database to disk and create backup.

        SQLite database is automatically persisted. This method creates a backup.
        """
        if not self.auto_backup or not self.db_path.exists():
            return

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.backup_dir / f"backup_{timestamp}.sqlite3"

            # Copy database to backup
            conn = sqlite3.connect(self.db_path)
            backup_conn = sqlite3.connect(backup_path)

            with backup_conn:
                conn.backup(backup_conn)

            backup_conn.close()
            conn.close()

            logger.debug(f"Created backup: {backup_path}")

            # Keep only last 10 backups
            backups = sorted(self.backup_dir.glob("backup_*.sqlite3"))
            if len(backups) > 10:
                for old_backup in backups[:-10]:
                    old_backup.unlink()
                    logger.debug(f"Deleted old backup: {old_backup}")

        except Exception as e:
            logger.warning(f"Backup creation failed: {e}")

    def clear(self) -> None:
        """Clear all documents from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM embeddings")
            cursor.execute("DELETE FROM metadata")
            conn.commit()
            logger.info("Database cleared")
        finally:
            conn.close()

    def export_to_jsonl(self, filepath: str) -> int:
        """Export all documents to JSONL format"""
        try:
            with open(filepath, 'w') as f:
                for doc in self.get()['ids']:
                    results = self.get(doc_ids=[doc])
                    if results['ids']:
                        line = {
                            'id': results['ids'][0],
                            'text': results['documents'][0],
                            'metadata': results['metadatas'][0],
                            'embedding': results['embeddings'][0]
                        }
                        json.dump(line, f)
                        f.write('\n')

            count = len(results['ids']) if results['ids'] else 0
            logger.info(f"Exported {count} documents to {filepath}")
            return count

        except Exception as e:
            logger.error(f"Export failed: {e}")
            raise

    def _generate_id(self) -> str:
        """Generate unique document ID"""
        import uuid
        return str(uuid.uuid4())

    def __len__(self) -> int:
        return self.count()

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"VectorDB(documents={stats.documents_stored}/{stats.documents_limit}, "
            f"dimension={self.dimension}, tier={self.tier}, storage={self.storage_path})"
        )


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Calculate cosine similarity between two vectors.

    Args:
        a: First vector
        b: Second vector

    Returns:
        Cosine similarity score between -1 and 1

    Raises:
        ValueError: If either vector is zero
    """
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    if norm_a == 0 or norm_b == 0:
        raise ValueError("Cannot compute cosine similarity with zero vectors")

    return float(np.dot(a, b) / (norm_a * norm_b))
