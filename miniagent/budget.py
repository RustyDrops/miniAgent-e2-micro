"""Persistent, transactional spending reservations in microdollars (UTC days)."""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

class BudgetExceeded(RuntimeError):
    pass


def microdollars(tokens: int, usd_per_million: Decimal) -> int:
    # One token at one USD/million costs one microdollar.
    return int((Decimal(tokens) * usd_per_million).to_integral_value(rounding=ROUND_CEILING))


class Budget:
    def __init__(self, db_path: str, daily_usd: Decimal):
        self.db_path = db_path
        self.limit = int((daily_usd * 1000000).to_integral_value(rounding=ROUND_FLOOR))
        with closing(self._connect()) as db:
            db.execute('PRAGMA journal_mode = WAL')
            db.execute('PRAGMA synchronous = NORMAL')
            db.execute('CREATE TABLE IF NOT EXISTS spend (id INTEGER PRIMARY KEY, day TEXT NOT NULL, reserved INTEGER NOT NULL, actual INTEGER, status TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS spend_day ON spend(day)')
            db.execute('BEGIN IMMEDIATE')
            columns = {row[1] for row in db.execute('PRAGMA table_info(spend)')}
            for name, declaration in (('model', "TEXT NOT NULL DEFAULT 'unknown'"),
                                      ('tier', "TEXT NOT NULL DEFAULT 'unspecified'"),
                                      ('input_tokens', 'INTEGER'), ('output_tokens', 'INTEGER'),
                                      ('cached_tokens', 'INTEGER'),
                                      ('role', "TEXT NOT NULL DEFAULT 'orchestrator'")):
                if name not in columns:
                    db.execute('ALTER TABLE spend ADD COLUMN ' + name + ' ' + declaration)
            db.commit()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=15, isolation_level=None)
        conn.execute('PRAGMA busy_timeout = 5000')
        return conn

    def reserve(self, amount: int, model: str = 'unknown', tier: str = 'unspecified', role: str = 'orchestrator') -> int:
        if amount < 0:
            raise ValueError('negative reservation')
        day = datetime.now(timezone.utc).date().isoformat()
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            spent = db.execute('SELECT COALESCE(SUM(COALESCE(actual, reserved)), 0) FROM spend WHERE day=?', (day,)).fetchone()[0]
            if spent + amount > self.limit:
                db.rollback()
                raise BudgetExceeded(f'Daily model budget exhausted: ${spent / 1e6:.6f} committed of ${self.limit / 1e6:.2f} UTC')
            cur = db.execute('INSERT INTO spend(day,reserved,status,model,tier,role) VALUES(?,?,?,?,?,?)',
                             (day, amount, 'reserved', str(model)[:120], str(tier or 'unspecified')[:40], str(role or 'orchestrator')[:40]))
            db.commit()
            return cur.lastrowid

    def settle(self, reservation: int, actual: int, input_tokens=None, output_tokens=None, cached_tokens=None):
        # Never erase evidence of underestimation; record actual even above reservation.
        with closing(self._connect()) as db:
            db.execute('UPDATE spend SET actual=?, status=?, input_tokens=?, output_tokens=?, cached_tokens=? WHERE id=? AND actual IS NULL',
                       (actual, 'complete', input_tokens, output_tokens, cached_tokens, reservation))

    def today(self) -> tuple[int, int]:
        day = datetime.now(timezone.utc).date().isoformat()
        with closing(self._connect()) as db:
            spent = db.execute('SELECT COALESCE(SUM(COALESCE(actual, reserved)),0) FROM spend WHERE day=?', (day,)).fetchone()[0]
        return spent, self.limit

    def usage_today(self):
        day = datetime.now(timezone.utc).date().isoformat()
        with closing(self._connect()) as db:
            rows = db.execute('''SELECT model,tier,COUNT(*),SUM(COALESCE(actual,reserved)),
                COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0),
                COALESCE(SUM(cached_tokens),0),COUNT(cached_tokens),
                SUM(CASE WHEN actual IS NULL THEN 1 ELSE 0 END)
                FROM spend WHERE day=? GROUP BY model,tier ORDER BY 4 DESC LIMIT 11''', (day,)).fetchall()
        fields = ('model', 'tier', 'requests', 'committed_microdollars', 'input_tokens', 'output_tokens',
                  'cached_tokens', 'cache_reported_requests', 'unsettled_requests')
        return [dict(zip(fields, row)) for row in rows[:10]], len(rows) > 10

    def usage_by_role(self, day: str | None = None) -> list[dict]:
        """Aggregate token usage and committed microdollars broken down by specialist role."""
        target_day = day or datetime.now(timezone.utc).date().isoformat()
        with closing(self._connect()) as db:
            rows = db.execute('''SELECT COALESCE(role, 'orchestrator'), COUNT(*),
                SUM(COALESCE(actual, reserved)), COALESCE(SUM(input_tokens), 0),
                COALESCE(SUM(output_tokens), 0)
                FROM spend WHERE day=? GROUP BY COALESCE(role, 'orchestrator')
                ORDER BY 3 DESC''', (target_day,)).fetchall()
        fields = ('role', 'requests', 'committed_microdollars', 'input_tokens', 'output_tokens')
        return [dict(zip(fields, row)) for row in rows]

