"""
Pocket Vector Database - Fast, persistent vector storage with semantic search

A lightweight, offline-first vector database for Python and edge devices.
Designed for semantic search, local LLM memory, and offline AI applications.

Features:
- Minimal dependencies (NumPy only)
- Fast cosine similarity search
- Persistent storage (embeddings.npy + metadata.json)
- Metadata filtering and CRUD operations
- Perfect for mobile/edge/Termux environments

Example:
    >>> from pocketvectordb import VectorDB
    >>> import numpy as np
    >>> db = VectorDB("./my_vectors", dimension=384)
    >>> embedding = np.random.randn(384)
    >>> doc_id = db.add(embedding, text="Hello world", metadata={"tag": "greeting"})
    >>> results = db.query(embedding, n_results=5)
    >>> db.save()
"""
import numpy as np
import pickle
import json
import os
import logging
from typing import List, Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass, asdict
import hashlib
import uuid
from pathlib import Path

__version__ = "1.1.0"
__all__ = ["VectorDB", "Document", "cosine_similarity"]

logger = logging.getLogger(__name__)


@dataclass
class Document:
    """Document with vector embedding and metadata"""
    id: str
    embedding: np.ndarray
    metadata: Dict[str, Any]
    text: Optional[str] = None
    
    def to_dict(self):
        return {
            'id': self.id,
            'embedding': self.embedding.tolist(),
            'metadata': self.metadata,
            'text': self.text
        }


class VectorDB:
    """
    Fast personal vector database with persistent storage and semantic search.
    
    Features:
    - Persistent storage using efficient binary format
    - Fast similarity search using numpy operations
    - Support for metadata filtering
    - CRUD operations (Create, Read, Update, Delete)
    - Batch operations for efficiency
    """
    
    def __init__(self, storage_path: str = "./vectordb_storage", dimension: Optional[int] = None):
        """
        Initialize VectorDB
        
        Args:
            storage_path: Directory to store database files
            dimension: Vector dimension (auto-detected from first insert if None)
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self.dimension = dimension
        self.documents: Dict[str, Document] = {}
        self.embeddings_matrix: Optional[np.ndarray] = None
        self.doc_ids: List[str] = []
        
        # File paths
        self.embeddings_file = self.storage_path / "embeddings.npy"
        self.metadata_file = self.storage_path / "metadata.json"
        
        # Load existing data
        self.load()
    
    def _generate_id(self, text: str) -> str:
        """Generate unique ID from text"""
        return str(uuid.uuid4())
    
    def _normalize_vector(self, vector: np.ndarray) -> np.ndarray:
        """Normalize vector for cosine similarity"""
        norm = np.linalg.norm(vector)
        if norm == 0:
            return vector
        return vector / norm
    
    def _rebuild_matrix(self):
        """Rebuild embeddings matrix from documents"""
        if not self.documents:
            self.embeddings_matrix = None
            self.doc_ids = []
            return
        
        self.doc_ids = list(self.documents.keys())
        embeddings_list = [self.documents[doc_id].embedding for doc_id in self.doc_ids]
        self.embeddings_matrix = np.vstack(embeddings_list)
    
    def add(self, 
            embedding: Union[np.ndarray, List[float]], 
            metadata: Optional[Dict[str, Any]] = None,
            text: Optional[str] = None,
            doc_id: Optional[str] = None) -> str:
        """
        Add a document with its embedding
        
        Args:
            embedding: Vector embedding (will be normalized)
            metadata: Optional metadata dictionary
            text: Optional original text
            doc_id: Optional document ID (auto-generated if None)
        
        Returns:
            Document ID
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
            raise ValueError(f"Embedding dimension {len(embedding)} doesn't match database dimension {self.dimension}")
        
        # Generate ID if not provided
        if doc_id is None:
            if text:
                doc_id = self._generate_id(text)
            else:
                doc_id = self._generate_id(str(embedding[:10]))
        
        # Normalize embedding
        embedding = self._normalize_vector(embedding)
        
        # Create document
        doc = Document(
            id=doc_id,
            embedding=embedding,
            metadata=metadata or {},
            text=text
        )
        
        # Add to documents
        self.documents[doc_id] = doc
        
        # Rebuild matrix
        self._rebuild_matrix()
        self.save()
        return doc_id
    
    def add_batch(self, 
                  embeddings: List[Union[np.ndarray, List[float]]], 
                  metadatas: Optional[List[Dict[str, Any]]] = None,
                  texts: Optional[List[str]] = None,
                  doc_ids: Optional[List[str]] = None) -> List[str]:
        """
        Add multiple documents efficiently
        
        Args:
            embeddings: List of vector embeddings
            metadatas: Optional list of metadata dictionaries
            texts: Optional list of original texts
            doc_ids: Optional list of document IDs
        
        Returns:
            List of document IDs
        """
        if metadatas is None:
            metadatas = [{}] * len(embeddings)
        if texts is None:
            texts = [None] * len(embeddings)
        if doc_ids is None:
            doc_ids = [None] * len(embeddings)
        
        added_ids = []
        for emb, meta, text, doc_id in zip(embeddings, metadatas, texts, doc_ids):
            added_id = self.add(emb, meta, text, doc_id)
            added_ids.append(added_id)
            
        self.save()
        return added_ids

    def _filter_by_metadata(self, where: Dict[str, Any], doc_ids: List[str]) -> List[int]:
        """
        Filter document indices by metadata with operator support.

        Supports operators:
        - Direct match: {"key": "value"}
        - Greater than: {"key": {"$gt": value}}
        - Less than: {"key": {"$lt": value}}
        - In list: {"key": {"$in": [v1, v2, v3]}}
        - Not equal: {"key": {"$ne": value}}
        - Multiple conditions on same key: {"key": {"$gte": 0, "$lte": 100}}

        Args:
            where: Metadata filter dictionary
            doc_ids: List of doc IDs to filter

        Returns:
            List of matching indices in the embeddings matrix
        """
        valid_indices = []

        for i, doc_id in enumerate(doc_ids):
            doc = self.documents[doc_id]
            match = True

            for key, condition in where.items():
                value = doc.metadata.get(key)

                # Simple equality check
                if not isinstance(condition, dict):
                    if value != condition:
                        match = False
                        break
                    continue

                # Operator-based checks
                if "$gt" in condition and not (value is not None and value > condition["$gt"]):
                    match = False
                    break
                if "$gte" in condition and not (value is not None and value >= condition["$gte"]):
                    match = False
                    break
                if "$lt" in condition and not (value is not None and value < condition["$lt"]):
                    match = False
                    break
                if "$lte" in condition and not (value is not None and value <= condition["$lte"]):
                    match = False
                    break
                if "$ne" in condition and value == condition["$ne"]:
                    match = False
                    break
                if "$in" in condition and value not in condition["$in"]:
                    match = False
                    break
                if "$nin" in condition and value in condition["$nin"]:
                    match = False
                    break

            if match:
                valid_indices.append(i)

        return valid_indices

    def query(self, 
              query_embedding: Union[np.ndarray, List[float]], 
              n_results: int = 10,
              where: Optional[Dict[str, Any]] = None,
              include_distances: bool = True) -> Dict[str, Any]:
        """
        Query for similar vectors using cosine similarity
        
        Args:
            query_embedding: Query vector
            n_results: Number of results to return
            where: Optional metadata filter (exact match)
            include_distances: Include similarity distances in results
        
        Returns:
            Dictionary with ids, documents, metadatas, and optionally distances
        """
        if self.embeddings_matrix is None or len(self.documents) == 0:
            return {
                'ids': [],
                'documents': [],
                'metadatas': [],
                'distances': [] if include_distances else None
            }
        
        # Convert to numpy array and normalize
        if isinstance(query_embedding, list):
            query_embedding = np.array(query_embedding, dtype=np.float32)
        
        if len(query_embedding) != self.dimension:
            raise ValueError(
                f"Query dimension {len(query_embedding)} "
                f"doesn't match database dimension {self.dimension}"
            )    
        
        query_embedding = self._normalize_vector(query_embedding)
        
        # Filter by metadata if specified
        if where:
            valid_indices = self._filter_by_metadata(where, self.doc_ids)

            if not valid_indices:
                return {
                    'ids': [],
                    'documents': [],
                    'metadatas': [],
                    'distances': [] if include_distances else None
                }
            
            filtered_embeddings = self.embeddings_matrix[valid_indices]
            filtered_doc_ids = [self.doc_ids[i] for i in valid_indices]
        else:
            filtered_embeddings = self.embeddings_matrix
            filtered_doc_ids = self.doc_ids
        
        # Compute cosine similarity (dot product since vectors are normalized)
        similarities = np.dot(filtered_embeddings, query_embedding)
        
        # Get top k results
        n_results = min(n_results, len(similarities))
        top_indices = np.argpartition(
            similarities,
            -n_results
        )[-n_results:]

        top_indices = top_indices[
            np.argsort(similarities[top_indices])[::-1]
        ]
        
        # Prepare results
        result_ids = [filtered_doc_ids[i] for i in top_indices]
        result_docs = [self.documents[doc_id] for doc_id in result_ids]
        
        results = {
            'ids': result_ids,
            'documents': [doc.text for doc in result_docs],
            'metadatas': [doc.metadata for doc in result_docs],
        }
        
        if include_distances:
            # Convert similarity to distance (1 - similarity for cosine distance)
            results['distances'] = [1 - similarities[i] for i in top_indices]
        
        return results
    
    def get(self, doc_ids: Optional[List[str]] = None,
            where: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get documents by IDs or metadata filter.

        Supports advanced operators in 'where': $gt, $gte, $lt, $lte, $ne, $in, $nin

        Args:
            doc_ids: List of document IDs to retrieve
            where: Optional metadata filter with operator support

        Returns:
            Dictionary with ids, documents, metadatas, embeddings

        Example:
            # Get all docs with score > 0.8
            docs = db.get(where={"score": {"$gt": 0.8}})
        """
        if doc_ids:
            docs = [self.documents.get(doc_id) for doc_id in doc_ids]
            docs = [d for d in docs if d is not None]
        elif where:
            valid_indices = self._filter_by_metadata(where, list(self.documents.keys()))
            docs = [self.documents[list(self.documents.keys())[i]] for i in valid_indices]
        else:
            docs = list(self.documents.values())

        return {
            'ids': [doc.id for doc in docs],
            'documents': [doc.text for doc in docs],
            'metadatas': [doc.metadata for doc in docs],
            'embeddings': [doc.embedding.tolist() for doc in docs]
        }
    
    def delete(self, doc_ids: Optional[List[str]] = None,
               where: Optional[Dict[str, Any]] = None) -> int:
        """
        Delete documents by IDs or metadata filter.

        Supports advanced operators in 'where': $gt, $gte, $lt, $lte, $ne, $in, $nin

        Args:
            doc_ids: List of document IDs to delete
            where: Optional metadata filter with operator support

        Returns:
            Number of documents deleted

        Example:
            # Delete all docs with score < 0.5
            deleted = db.delete(where={"score": {"$lt": 0.5}})
        """
        if doc_ids:
            to_delete = set(doc_ids) & set(self.documents.keys())
        elif where:
            valid_indices = self._filter_by_metadata(where, list(self.documents.keys()))
            to_delete = {list(self.documents.keys())[i] for i in valid_indices}
        else:
            return 0
        
        for doc_id in to_delete:
            del self.documents[doc_id]
        
        self._rebuild_matrix()
        self.save()           
        return len(to_delete)
    
    def update(self, doc_id: str,
               embedding: Optional[Union[np.ndarray, List[float]]] = None,
               metadata: Optional[Dict[str, Any]] = None,
               text: Optional[str] = None):
        """
        Update a document's embedding, metadata, or text

        Args:
            doc_id: Document ID to update
            embedding: New embedding (optional)
            metadata: New metadata (optional, will be merged)
            text: New text (optional)

        Raises:
            KeyError: If document ID not found
            ValueError: If embedding dimension doesn't match database dimension
        """
        if doc_id not in self.documents:
            raise KeyError(f"Document {doc_id} not found")

        doc = self.documents[doc_id]

        if embedding is not None:
            if isinstance(embedding, list):
                embedding = np.array(embedding, dtype=np.float32)
            else:
                embedding = embedding.astype(np.float32)

            if len(embedding) != self.dimension:
                raise ValueError(
                    f"Embedding dimension {len(embedding)} doesn't match "
                    f"database dimension {self.dimension}"
                )

            doc.embedding = self._normalize_vector(embedding)
            self._rebuild_matrix()

        if metadata is not None:
            doc.metadata.update(metadata)

        if text is not None:
            doc.text = text

        self.save()

    def update_batch(self,
                     doc_ids: List[str],
                     embeddings: Optional[List[Union[np.ndarray, List[float]]]] = None,
                     metadatas: Optional[List[Dict[str, Any]]] = None,
                     texts: Optional[List[str]] = None) -> int:
        """
        Update multiple documents efficiently.

        Args:
            doc_ids: List of document IDs to update
            embeddings: Optional list of new embeddings
            metadatas: Optional list of metadata updates
            texts: Optional list of new texts

        Returns:
            Number of documents successfully updated

        Raises:
            ValueError: If list lengths don't match or dimensions invalid
        """
        if not doc_ids:
            return 0

        # Validate list lengths match doc_ids
        if embeddings and len(embeddings) != len(doc_ids):
            raise ValueError(f"embeddings length {len(embeddings)} doesn't match doc_ids length {len(doc_ids)}")
        if metadatas and len(metadatas) != len(doc_ids):
            raise ValueError(f"metadatas length {len(metadatas)} doesn't match doc_ids length {len(doc_ids)}")
        if texts and len(texts) != len(doc_ids):
            raise ValueError(f"texts length {len(texts)} doesn't match doc_ids length {len(doc_ids)}")

        updated_count = 0
        for i, doc_id in enumerate(doc_ids):
            if doc_id not in self.documents:
                logger.warning(f"Document not found: {doc_id}")
                continue

            emb = embeddings[i] if embeddings else None
            meta = metadatas[i] if metadatas else None
            text = texts[i] if texts else None

            try:
                self.update(doc_id, embedding=emb, metadata=meta, text=text)
                updated_count += 1
            except Exception as e:
                logger.warning(f"Failed to update {doc_id}: {e}")

        return updated_count

    def count(self) -> int:
        """Get total number of documents"""
        return len(self.documents)

    def query_paginated(self,
                        query_embedding: Union[np.ndarray, List[float]],
                        n_results: int = 10,
                        offset: int = 0,
                        where: Optional[Dict[str, Any]] = None,
                        include_distances: bool = True) -> Dict[str, Any]:
        """
        Query with pagination support.

        Args:
            query_embedding: Query vector
            n_results: Number of results to return per page
            offset: Number of results to skip (for pagination)
            where: Optional metadata filter
            include_distances: Include similarity distances in results

        Returns:
            Dictionary with ids, documents, metadatas, and optionally distances + total_count

        Example:
            page1 = db.query_paginated(query, n_results=10, offset=0)
            page2 = db.query_paginated(query, n_results=10, offset=10)
        """
        # Get all matching results first
        all_results = self.query(query_embedding, n_results=len(self.documents), where=where, include_distances=True)

        total_count = len(all_results['ids'])
        start_idx = offset
        end_idx = offset + n_results

        # Apply pagination
        paginated_results = {
            'ids': all_results['ids'][start_idx:end_idx],
            'documents': all_results['documents'][start_idx:end_idx],
            'metadatas': all_results['metadatas'][start_idx:end_idx],
            'total_count': total_count,
            'offset': offset,
            'has_more': end_idx < total_count,
        }

        if include_distances:
            paginated_results['distances'] = all_results['distances'][start_idx:end_idx]

        return paginated_results

    def get_stats(self) -> Dict[str, Any]:
        """
        Get database statistics.

        Returns:
            Dictionary with statistics about the database
        """
        if not self.documents:
            return {
                'total_documents': 0,
                'dimension': self.dimension,
                'storage_path': str(self.storage_path),
                'embeddings_file_size': 0,
                'metadata_file_size': 0,
            }

        # Calculate file sizes
        embeddings_size = 0
        metadata_size = 0
        if self.embeddings_file.exists():
            embeddings_size = self.embeddings_file.stat().st_size
        if self.metadata_file.exists():
            metadata_size = self.metadata_file.stat().st_size

        # Calculate embedding statistics
        embedding_norms = [np.linalg.norm(doc.embedding) for doc in self.documents.values()]

        return {
            'total_documents': len(self.documents),
            'dimension': self.dimension,
            'storage_path': str(self.storage_path),
            'embeddings_file_size': embeddings_size,
            'metadata_file_size': metadata_size,
            'total_size': embeddings_size + metadata_size,
            'avg_embedding_norm': float(np.mean(embedding_norms)),
            'min_embedding_norm': float(np.min(embedding_norms)),
            'max_embedding_norm': float(np.max(embedding_norms)),
        }


    def save(self) -> None:
        """
        Save database to disk.

        Creates embeddings.npy and metadata.json in the storage path.
        Uses atomic writes (temp file + os.replace) to prevent corruption.
        """
        if not self.documents:
            logger.debug(f"No documents to save in {self.storage_path}")
            return

        try:
            # Save embeddings matrix
            if self.embeddings_matrix is not None:
                np.save(self.embeddings_file, self.embeddings_matrix)
                logger.debug(f"Saved {len(self.doc_ids)} embeddings to {self.embeddings_file}")

            # Save metadata and texts
            metadata_data = {
                'dimension': self.dimension,
                'doc_ids': self.doc_ids,
                'documents': {
                    doc_id: {
                        'metadata': doc.metadata,
                        'text': doc.text
                    }
                    for doc_id, doc in self.documents.items()
                }
            }

            temp_file = str(self.metadata_file) + ".tmp"

            with open(temp_file, 'w') as f:
                json.dump(metadata_data, f)

            os.replace(temp_file, self.metadata_file)
            logger.debug(f"Saved metadata to {self.metadata_file}")

        except Exception as e:
            logger.error(f"Failed to save database: {e}")
            raise
    
    def load(self) -> None:
        """
        Load database from disk.

        Reconstructs documents from embeddings.npy and metadata.json.
        If files are missing or corrupted, starts with empty database.
        """
        if not self.metadata_file.exists():
            logger.debug(f"No existing database at {self.storage_path}")
            return

        try:
            # Load metadata
            with open(self.metadata_file, 'r') as f:
                metadata_data = json.load(f)

            self.dimension = metadata_data.get('dimension')
            self.doc_ids = metadata_data.get('doc_ids', [])

            # Load embeddings
            if self.embeddings_file.exists():
                self.embeddings_matrix = np.load(self.embeddings_file)
                logger.debug(f"Loaded {len(self.doc_ids)} embeddings from {self.embeddings_file}")
            else:
                logger.warning(f"Embeddings file not found: {self.embeddings_file}")

            # Reconstruct documents
            documents_data = metadata_data.get('documents', {})
            for i, doc_id in enumerate(self.doc_ids):
                doc_data = documents_data.get(doc_id)
                if doc_data is None:
                    logger.warning(f"Document data missing for ID: {doc_id}")
                    continue

                self.documents[doc_id] = Document(
                    id=doc_id,
                    embedding=self.embeddings_matrix[i] if self.embeddings_matrix is not None else None,
                    metadata=doc_data['metadata'],
                    text=doc_data['text']
                )

            logger.info(f"Loaded database: {len(self.documents)} documents, dimension={self.dimension}")

        except json.JSONDecodeError as e:
            logger.error(f"Corrupted metadata file: {e}")
            self.documents = {}
            self.embeddings_matrix = None
            self.doc_ids = []
        except Exception as e:
            logger.error(f"Failed to load database: {e}")
            self.documents = {}
            self.embeddings_matrix = None
            self.doc_ids = []
    
    def clear(self) -> None:
        """
        Clear all documents from database and remove files.

        Removes embeddings.npy and metadata.json from storage path.
        """
        try:
            self.documents = {}
            self.embeddings_matrix = None
            self.doc_ids = []

            if self.embeddings_file.exists():
                os.remove(self.embeddings_file)
                logger.debug(f"Removed {self.embeddings_file}")

            if self.metadata_file.exists():
                os.remove(self.metadata_file)
                logger.debug(f"Removed {self.metadata_file}")

            logger.info(f"Cleared database at {self.storage_path}")
        except Exception as e:
            logger.error(f"Failed to clear database: {e}")
            raise

    def export_to_jsonl(self, filepath: str) -> int:
        """
        Export all documents to JSONL format.

        Args:
            filepath: Path to write JSONL file to

        Returns:
            Number of documents exported
        """
        try:
            with open(filepath, 'w') as f:
                for doc in self.documents.values():
                    line = {
                        'id': doc.id,
                        'text': doc.text,
                        'metadata': doc.metadata,
                        'embedding': doc.embedding.tolist()
                    }
                    json.dump(line, f)
                    f.write('\n')

            logger.info(f"Exported {len(self.documents)} documents to {filepath}")
            return len(self.documents)
        except Exception as e:
            logger.error(f"Failed to export to JSONL: {e}")
            raise

    def import_from_jsonl(self, filepath: str, skip_on_error: bool = True) -> int:
        """
        Import documents from JSONL file.

        Args:
            filepath: Path to JSONL file
            skip_on_error: Whether to skip documents with errors or raise

        Returns:
            Number of documents imported
        """
        try:
            count = 0
            with open(filepath, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        data = json.loads(line)
                        embedding = np.array(data['embedding'], dtype=np.float32)
                        self.add(
                            embedding,
                            text=data.get('text'),
                            metadata=data.get('metadata', {}),
                            doc_id=data.get('id')
                        )
                        count += 1
                    except Exception as e:
                        if skip_on_error:
                            logger.warning(f"Skipped line {line_num}: {e}")
                        else:
                            raise

            self.save()
            logger.info(f"Imported {count} documents from {filepath}")
            return count
        except Exception as e:
            logger.error(f"Failed to import from JSONL: {e}")
            raise

    def to_dict(self) -> Dict[str, Any]:
        """
        Export database to dictionary format.

        Returns:
            Dictionary representation of database
        """
        return {
            'dimension': self.dimension,
            'documents': {
                doc_id: {
                    'text': doc.text,
                    'metadata': doc.metadata,
                    'embedding': doc.embedding.tolist()
                }
                for doc_id, doc in self.documents.items()
            }
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """
        Load database from dictionary format.

        Args:
            data: Dictionary with dimension and documents
        """
        self.dimension = data.get('dimension')
        self.documents = {}

        for doc_id, doc_data in data.get('documents', {}).items():
            embedding = np.array(doc_data['embedding'], dtype=np.float32)
            self.documents[doc_id] = Document(
                id=doc_id,
                embedding=embedding,
                metadata=doc_data.get('metadata', {}),
                text=doc_data.get('text')
            )

        self._rebuild_matrix()
        self.save()
        logger.info(f"Loaded {len(self.documents)} documents from dictionary")

    def __len__(self) -> int:
        return len(self.documents)

    def __repr__(self) -> str:
        return f"VectorDB(documents={len(self.documents)}, dimension={self.dimension}, storage='{self.storage_path}')"

    def __enter__(self):
        """Context manager entry - allows 'with VectorDB(...) as db:' syntax"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Context manager exit - saves database on exit"""
        try:
            self.save()
        except Exception as e:
            logger.error(f"Error saving database on context exit: {e}")
        return False


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
