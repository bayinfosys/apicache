import os
import json
import sqlite3
import logging
import hashlib

from contextlib import contextmanager
from datetime import datetime, timedelta



logger = logging.getLogger("apicache")


DEFAULT_LOCATION = "./api-cache.sqlite"


class APICache:
    """Client side, data-aware proxy"""

    def compute_hash(self, data: dict) -> str:
        """compute a SHA256 hash for deduplication."""
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()

    @contextmanager
    def _get_conn(self):
        """yield a connection object to the db"""
        with sqlite3.connect(self.location) as conn:
            # conn.row_factory = sqlite3.Row
            yield conn

    def __init__(self, request_fn, ttl: int = None, location: str = None):
        """initialize the proxy
        request_fn: function to populate the cache. Must accept (str, dict)
        ttl: time-to-live for records
        location: disk location of the sqlite3 backing.

        NB: :memory: backing will not work as expected
        """

        self.request_fn = request_fn
        self.ttl = ttl or DEFAULT_TTL_SECONDS
        self.location = location or DEFAULT_LOCATION

        sql_stmt = """
            CREATE TABLE IF NOT EXISTS raw_api_requests (
                id TEXT,                  -- Hash of (URL + params)
                request_url TEXT,         -- Full API request URL
                request_params TEXT,      -- Query params (if any)
                response_data JSON,       -- Full JSON response
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(id, fetched_at) -- PK is (id, timestamp)
            );
        """

        with self._get_conn() as conn:
            conn.execute(sql_stmt)

    def is_entry_fresh(self, fetched_at: str) -> bool:
        """Check if the cached response is still within TTL"""
        fetched_time = datetime.strptime(fetched_at, "%Y-%m-%d %H:%M:%S")
        return datetime.utcnow() - fetched_time < timedelta(seconds=self.ttl)

    def put(self, url: str, params: dict, response: dict):
        """insert a new request/response into the api cache table"""
        hash_id = self.compute_hash({"url": url, "params": params})

        sql_stmt = """
            INSERT OR IGNORE INTO raw_api_requests (
            id,
            request_url, request_params,
            response_data,
            fetched_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """
        sql_params = (hash_id, url, json.dumps(params), json.dumps(response))

        with self._get_conn() as conn:
            conn.execute(sql_stmt, sql_params)

        logger.info("insert %s[%s]->%s", url, str(params), hash_id)

    def get(self, url, params):
        """return a response from the cache"""
        hash_id = self.compute_hash({"url": url, "params": params})

        sql_stmt = """
            SELECT response_data
            FROM raw_api_requests
            WHERE id = ?
            ORDER BY fetched_at DESC
            LIMIT 1
        """
        sql_params = (hash_id,)

        with self._get_conn() as conn:
            row = conn.execute(sql_stmt, sql_params).fetchone()

            if row is None:
                return None

        return json.loads(row[0])

    def has(self, url, params, ignore_expiry=False):
        """check if a request has already been cached and is still fresh"""
        hash_id = self.compute_hash({"url": url, "params": params})

        sql_stmt = """
            SELECT fetched_at
            FROM raw_api_requests
            WHERE id = ?
            ORDER BY fetched_at DESC
            LIMIT 1
        """
        sql_params = (hash_id,)

        with self._get_conn() as conn:
            row = conn.execute(sql_stmt, sql_params).fetchone()

        if row:
            fetched_at = row[0]
            is_fresh = self.is_entry_fresh(fetched_at)

            if is_fresh or ignore_expiry:
                logger.debug("[%s] cache hit (fresh: %s)", hash_id, is_fresh)
                return True
            else:
                logger.debug("[%s] cache expired", hash_id)
                return False

        logger.debug("[%s] cache miss", hash_id)
        return False

    def request(self, url, params, cache_only=False) -> (bool, dict):
        """make a proxied api request

        populate the cache if necessary by calling `fetch_fn`

        Args:
            url (str): URL template.
            params (dict): URL params.
            fetch_fn (Callable): Function to fetch data live.
            cache_only (bool): If True, never hit the live API.

        Returns:
            (bool, dict): Tuple of (was_cache_hit, data)
        """
        cache_hit = self.has(url, params)

        if cache_hit is False:
            if cache_only:
                logger.warning("CACHE_ONLY enabled, no live data")
                return False, {}

            try:
                raw_data = self.request_fn(url, params)
            except Exception as e:
                logger.error("fetch_fn failed [%s]", str(e))
                raise e

            try:
                self.put(url, params, raw_data)
            except Exception as e:
                logger.error("failed to cache response [%s]", str(e))
                raise e

        return cache_hit, self.get(url, params)

    def clear_for_url(self, url_prefix: str):
        """
        delete all cached API responses for URLs starting with the prefix.
        eg: cache_clear_for_url("/company/12345")
        """
        sql_stmt = "DELETE FROM raw_api_requests WHERE request_url LIKE ?"
        sql_param = (f"{url_prefix}%",)

        with self._get_conn() as conn:
            affected = conn.execute(sql_stmt, sql_param).rowcount

        logger.info("cleared %i entries for '%s'", affected, url_prefix)

    def prune_old_versions(self):
        sql_stmt = """
            DELETE FROM raw_api_requests
            WHERE (id, fetched_at) NOT IN (
                SELECT id, MAX(fetched_at)
                FROM raw_api_requests
                GROUP BY id);
        """
        with self._get_conn() as conn:
            affected = conn.execute(sql_stmt).rowcount
            logger.info("deleted %i old entries", affected)

    def stats(self):
        """return usage stats"""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # count total cache entries
            cursor.execute("SELECT COUNT(*) FROM raw_api_requests")
            total_requests = cursor.fetchone()[0]

            # calculate total size in MB
            cursor.execute("SELECT SUM(LENGTH(response_data)) FROM raw_api_requests")
            total_size_bytes = cursor.fetchone()[0] or 0
            total_size_mb = total_size_bytes / (1024 * 1024)

            # get the most recent timestamp
            cursor.execute("SELECT MAX(fetched_at) FROM raw_api_requests")
            last_updated = cursor.fetchone()[0]

        return {
            "total_requests": total_requests,
            "cache_size": total_size_mb,
            "last_updated": last_updated or 0,
        }
