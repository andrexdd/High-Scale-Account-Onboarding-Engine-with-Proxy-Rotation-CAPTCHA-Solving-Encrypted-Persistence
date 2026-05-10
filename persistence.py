import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet, InvalidToken

from .exceptions import PersistenceError, EncryptionError, DatabaseError
from .constants import DatabaseConstants
from .validators import DatabaseValidator

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS onboarding_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    encrypted_payload BLOB NOT NULL,
    status TEXT DEFAULT 'completed',
    last_updated TEXT NOT NULL
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_user_id ON onboarding_results(user_id);
CREATE INDEX IF NOT EXISTS idx_created_at ON onboarding_results(created_at);
CREATE INDEX IF NOT EXISTS idx_status ON onboarding_results(status);
"""


class PersistenceStore:
    def __init__(self, db_path: str, encryption_key: bytes, timeout: int = DatabaseConstants.CONNECTION_TIMEOUT) -> None:
        self.db_path: Path = Path(db_path)
        DatabaseValidator.validate_db_path(self.db_path)
        
        try:
            self._cipher: Fernet = Fernet(encryption_key)
        except Exception as exc:
            raise EncryptionError(f"Invalid encryption key: {exc}") from exc
        
        self._local = threading.local()
        self._timeout = timeout
        self._lock = threading.Lock()
        self._init_database()
    
    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=self._timeout
            )
            self._local.connection.isolation_level = None
            self._local.connection.execute("PRAGMA journal_mode=WAL")
            self._local.connection.execute("PRAGMA synchronous=NORMAL")
        return self._local.connection
    
    def _init_database(self) -> None:
        try:
            conn = self._get_connection()
            conn.execute(CREATE_TABLE_SQL)
            for index in CREATE_INDEX_SQL.strip().split('\n'):
                if index.strip():
                    conn.execute(index)
            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to initialize database: {exc}") from exc

    @classmethod
    def from_config(cls, db_path: str, key: Optional[str] = None) -> "PersistenceStore":
        if not key:
            raise PersistenceError("Encryption key is required for persistence store")
        try:
            DatabaseValidator.validate_encryption_key(key)
        except Exception as exc:
            raise PersistenceError(f"Invalid configuration: {exc}") from exc
        return cls(db_path, key.encode())

    @staticmethod
    def generate_key() -> bytes:
        return Fernet.generate_key()

    def _encrypt(self, data: bytes) -> bytes:
        try:
            return self._cipher.encrypt(data)
        except Exception as exc:
            raise EncryptionError(f"Encryption failed: {exc}") from exc

    def _decrypt(self, token: bytes) -> bytes:
        try:
            return self._cipher.decrypt(token)
        except InvalidToken as exc:
            raise EncryptionError(f"Decryption failed - invalid token: {exc}") from exc
        except Exception as exc:
            raise EncryptionError(f"Decryption failed: {exc}") from exc

    def save_record(self, user_id: str, payload: Dict[str, Any]) -> int:
        try:
            serialized = json.dumps(payload, default=str).encode("utf-8")
        except Exception as exc:
            raise PersistenceError(f"Failed to serialize payload: {exc}") from exc
        
        try:
            encrypted = self._encrypt(serialized)
        except EncryptionError as exc:
            raise PersistenceError(f"Failed to encrypt record: {exc}") from exc
        
        created_at = datetime.utcnow().isoformat() + "Z"
        last_updated = created_at
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "BEGIN TRANSACTION"
            )
            cursor.execute(
                "INSERT INTO onboarding_results "
                "(user_id, created_at, encrypted_payload, last_updated) "
                "VALUES (?, ?, ?, ?)",
                (user_id, created_at, encrypted, last_updated),
            )
            conn.commit()
            record_id = cursor.lastrowid
            logger.debug(f"Saved record {record_id} for user {user_id}")
            return record_id
        except sqlite3.IntegrityError as exc:
            raise PersistenceError(f"Duplicate user_id: {user_id}") from exc
        except sqlite3.Error as exc:
            raise DatabaseError(f"Database error during save: {exc}") from exc

    def load_records(self, limit: int = 100, status: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            if status:
                cursor.execute(
                    "SELECT id, user_id, created_at, encrypted_payload, status "
                    "FROM onboarding_results "
                    "WHERE status = ? "
                    "ORDER BY id DESC LIMIT ?",
                    (status, limit)
                )
            else:
                cursor.execute(
                    "SELECT id, user_id, created_at, encrypted_payload, status "
                    "FROM onboarding_results "
                    "ORDER BY id DESC LIMIT ?",
                    (limit,)
                )
            
            records = []
            for row in cursor.fetchall():
                record_id, user_id, created_at, encrypted_payload, record_status = row
                try:
                    decrypted = self._decrypt(encrypted_payload)
                    payload = json.loads(decrypted.decode("utf-8"))
                    records.append({
                        "id": record_id,
                        "user_id": user_id,
                        "created_at": created_at,
                        "status": record_status,
                        "payload": payload
                    })
                except EncryptionError as exc:
                    logger.warning(f"Failed to decrypt record {record_id}: {exc}")
                    continue
                except json.JSONDecodeError as exc:
                    logger.warning(f"Failed to parse record {record_id}: {exc}")
                    continue
            
            return records
        except sqlite3.Error as exc:
            raise DatabaseError(f"Database error during load: {exc}") from exc

    def update_record_status(self, record_id: int, status: str) -> None:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            last_updated = datetime.utcnow().isoformat() + "Z"
            cursor.execute(
                "UPDATE onboarding_results SET status = ?, last_updated = ? WHERE id = ?",
                (status, last_updated, record_id)
            )
            conn.commit()
            logger.debug(f"Updated record {record_id} status to {status}")
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to update record status: {exc}") from exc

    def get_total_records(self) -> int:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM onboarding_results")
            count = cursor.fetchone()[0]
            return count
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to get record count: {exc}") from exc

    def close(self) -> None:
        if hasattr(self._local, 'connection') and self._local.connection:
            try:
                self._local.connection.close()
                self._local.connection = None
                logger.info("Database connection closed")
            except sqlite3.Error as exc:
                logger.error(f"Error closing database: {exc}")
