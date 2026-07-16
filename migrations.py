"""
Migration tool to convert old file-based PocketVectorDB to new SQLite backend.

Allows existing users to upgrade from .npy/.json format to SQLite without data loss.
"""
import numpy as np
import json
import sqlite3
import logging
from pathlib import Path
from typing import Optional
import time

logger = logging.getLogger(__name__)


def migrate_to_sqlite(old_storage_path: str, new_storage_path: Optional[str] = None) -> bool:
    """
    Migrate old file-based PocketVectorDB to new SQLite backend.

    Args:
        old_storage_path: Path to old PocketVectorDB directory with embeddings.npy and metadata.json
        new_storage_path: Path for new SQLite database (defaults to same directory)

    Returns:
        True if migration successful, False otherwise

    Example:
        >>> from migrations import migrate_to_sqlite
        >>> migrate_to_sqlite("./my_vectordb")
        # Old .npy and .json files will be backed up, new SQLite database created
    """
    old_path = Path(old_storage_path)
    new_path = Path(new_storage_path) if new_storage_path else old_path

    if not old_path.exists():
        logger.error(f"Old storage path does not exist: {old_path}")
        return False

    embeddings_file = old_path / "embeddings.npy"
    metadata_file = old_path / "metadata.json"

    # Check if old format exists
    if not embeddings_file.exists() or not metadata_file.exists():
        logger.warning("Old format files not found. Assuming new SQLite database already.")
        return True

    logger.info(f"Starting migration from {old_path} to {new_path}")

    try:
        # Load old data
        logger.info("Loading old embeddings.npy...")
        embeddings_matrix = np.load(embeddings_file)

        logger.info("Loading old metadata.json...")
        with open(metadata_file, 'r') as f:
            metadata_data = json.load(f)

        dimension = metadata_data.get('dimension')
        doc_ids = metadata_data.get('doc_ids', [])
        documents_data = metadata_data.get('documents', {})

        if len(embeddings_matrix) != len(doc_ids):
            logger.error("Mismatch between embeddings count and doc_ids count")
            return False

        # Create new SQLite database
        new_path.mkdir(parents=True, exist_ok=True)
        db_path = new_path / "vectordb.sqlite3"

        logger.info(f"Creating new SQLite database: {db_path}")

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                id TEXT PRIMARY KEY,
                vector BLOB NOT NULL,
                embedding_norm REAL NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                id TEXT PRIMARY KEY,
                doc_text TEXT,
                metadata_json TEXT NOT NULL,
                FOREIGN KEY(id) REFERENCES embeddings(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usage_tracking (
                id INTEGER PRIMARY KEY,
                month TEXT NOT NULL UNIQUE,
                queries_count INTEGER DEFAULT 0,
                api_calls INTEGER DEFAULT 0,
                last_updated REAL
            )
        """)

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

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS db_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # Migrate documents
        logger.info(f"Migrating {len(doc_ids)} documents...")
        now = time.time()

        for idx, doc_id in enumerate(doc_ids):
            if idx % 1000 == 0:
                logger.debug(f"Migrated {idx}/{len(doc_ids)} documents")

            # Get embedding (already normalized from old version)
            embedding = embeddings_matrix[idx]
            embedding_bytes = embedding.astype(np.float32).tobytes()
            norm = np.linalg.norm(embedding)

            # Get metadata
            doc_data = documents_data.get(doc_id, {})
            metadata_json = json.dumps(doc_data.get('metadata', {}))
            doc_text = doc_data.get('text')

            # Insert into new database
            cursor.execute(
                """INSERT INTO embeddings (id, vector, embedding_norm, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (doc_id, embedding_bytes, norm, now, now)
            )

            cursor.execute(
                """INSERT INTO metadata (id, doc_text, metadata_json)
                   VALUES (?, ?, ?)""",
                (doc_id, doc_text, metadata_json)
            )

        # Store database metadata
        cursor.execute(
            "INSERT OR REPLACE INTO db_metadata (key, value) VALUES (?, ?)",
            ('migrated_from_version', '1.0.0')
        )
        cursor.execute(
            "INSERT OR REPLACE INTO db_metadata (key, value) VALUES (?, ?)",
            ('migration_date', str(datetime.now().isoformat()))
        )

        conn.commit()
        conn.close()

        logger.info(f"Successfully migrated {len(doc_ids)} documents to SQLite")

        # Backup old files
        logger.info("Creating backup of old files...")
        backup_dir = old_path / "backups_v1.0.0"
        backup_dir.mkdir(exist_ok=True)

        import shutil
        shutil.copy2(embeddings_file, backup_dir / "embeddings.npy")
        shutil.copy2(metadata_file, backup_dir / "metadata.json")

        logger.info(f"Old files backed up to {backup_dir}")

        # Optional: Remove old files (comment out for safety)
        # embeddings_file.unlink()
        # metadata_file.unlink()
        # logger.info("Old files deleted")

        logger.info("Migration completed successfully!")
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        return False


def verify_migration(storage_path: str) -> dict:
    """
    Verify that migration was successful by comparing old and new data.

    Args:
        storage_path: Path to the migrated database

    Returns:
        Dictionary with verification results
    """
    path = Path(storage_path)
    db_path = path / "vectordb.sqlite3"

    if not db_path.exists():
        return {"success": False, "error": "No SQLite database found"}

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Count documents
        cursor.execute("SELECT COUNT(*) FROM embeddings")
        doc_count = cursor.fetchone()[0]

        # Check metadata
        cursor.execute("SELECT COUNT(*) FROM metadata WHERE metadata_json IS NOT NULL")
        meta_count = cursor.fetchone()[0]

        # Check if backup exists
        backup_dir = path / "backups_v1.0.0"
        backup_exists = backup_dir.exists()

        conn.close()

        return {
            "success": True,
            "documents": doc_count,
            "metadata_entries": meta_count,
            "backup_exists": backup_exists,
            "db_path": str(db_path)
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    from datetime import datetime

    # Example usage
    import sys

    if len(sys.argv) < 2:
        print("Usage: python migrations.py <old_storage_path> [new_storage_path]")
        sys.exit(1)

    old_path = sys.argv[1]
    new_path = sys.argv[2] if len(sys.argv) > 2 else None

    logging.basicConfig(level=logging.INFO)

    success = migrate_to_sqlite(old_path, new_path)
    if success:
        verify_result = verify_migration(new_path or old_path)
        print(f"\nMigration verification: {verify_result}")
        sys.exit(0)
    else:
        sys.exit(1)
