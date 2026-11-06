"""Adaptive Multinomial Naive Bayes task router with online self-improvement."""
from contextlib import closing
import math
import os
import re
import sqlite3
import time

STOPWORDS = {
    'a', 'about', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
    'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the', 'to',
    'was', 'were', 'will', 'with', 'this', 'but', 'they', 'have', 'had',
    'what', 'when', 'where', 'who', 'which', 'why', 'how', 'do', 'does', 'did',
    'can', 'could', 'should', 'would', 'i', 'you', 'my', 'your', 'we', 'our',
    'one', 'two', 'also', 'all', 'any', 'some'
}

DEFAULT_CONFIDENCE_THRESHOLD = 0.85
MIN_CLASS_SAMPLES = 2


def tokenize(text):
    """Extract lowercase words, skipping numbers and common stopwords."""
    if not isinstance(text, str):
        return []
    tokens = re.findall(r'\b[a-z_][a-z0-9_-]{1,29}\b', text.lower())
    return [w for w in tokens if w not in STOPWORDS and not w.isdigit()]


class NaiveBayesRouter:
    def __init__(self, db_path='miniagent.db'):
        self.db_path = db_path
        self._init_db()

    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        conn.execute('PRAGMA busy_timeout = 5000')
        return conn

    def _init_db(self):
        with closing(self.connect()) as db:
            db.execute('PRAGMA journal_mode = WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS bayes_word_counts (
                    word TEXT NOT NULL,
                    plan TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (word, plan)
                );
                CREATE TABLE IF NOT EXISTS bayes_plan_counts (
                    plan TEXT PRIMARY KEY,
                    count INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS bayes_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bayes_audit (
                    id INTEGER PRIMARY KEY,
                    task TEXT NOT NULL,
                    predicted_plan TEXT,
                    confidence REAL,
                    actual_plan TEXT NOT NULL,
                    source TEXT NOT NULL,
                    success INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_bayes_audit_time ON bayes_audit(created_at);
            ''')

    def get_threshold(self):
        with closing(self.connect()) as db:
            row = db.execute("SELECT value FROM bayes_settings WHERE key='confidence_threshold'").fetchone()
            if row:
                try:
                    return float(row[0])
                except ValueError:
                    pass
            return DEFAULT_CONFIDENCE_THRESHOLD

    def set_threshold(self, threshold):
        val = max(0.50, min(0.98, float(threshold)))
        with closing(self.connect()) as db:
            db.execute("INSERT INTO bayes_settings(key, value) VALUES('confidence_threshold', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(val),))

    def predict(self, task):
        """Predict the role sequence for a task. Returns (plan_tuple, confidence, source)."""
        words = tokenize(task)
        if not words:
            return None, 0.0, 'uncertain'

        with closing(self.connect()) as db:
            plans = db.execute('SELECT plan, count FROM bayes_plan_counts').fetchall()
            if not plans:
                return None, 0.0, 'no_data'

            total_plans = sum(c for _, c in plans)
            vocab_size = db.execute('SELECT COUNT(DISTINCT word) FROM bayes_word_counts').fetchone()[0] or 1

            word_totals_by_plan = dict(db.execute('SELECT plan, SUM(count) FROM bayes_word_counts GROUP BY plan').fetchall())

            # Fetch relevant word counts in one query
            placeholders = ','.join('?' for _ in words)
            rows = db.execute(f'SELECT word, plan, count FROM bayes_word_counts WHERE word IN ({placeholders})', words).fetchall()
            word_map = {}
            for w, p, cnt in rows:
                word_map[(w, p)] = cnt

            scores = {}
            alpha = 1.0  # Laplace smoothing
            for plan_str, plan_count in plans:
                # Prior: log P(plan)
                log_prob = math.log((plan_count + alpha) / (total_plans + alpha * len(plans)))
                plan_word_total = word_totals_by_plan.get(plan_str, 0)
                denominator = plan_word_total + alpha * vocab_size

                # Likelihood: sum log P(word | plan)
                for w in words:
                    w_count = word_map.get((w, plan_str), 0)
                    log_prob += math.log((w_count + alpha) / denominator)
                scores[plan_str] = log_prob

        # Softmax normalization to get confidence
        max_score = max(scores.values())
        exp_scores = {p: math.exp(s - max_score) for p, s in scores.items()}
        sum_exp = sum(exp_scores.values())
        probs = {p: exp_s / sum_exp for p, exp_s in exp_scores.items()}

        sorted_plans = sorted(probs.items(), key=lambda item: item[1], reverse=True)
        top_plan_str, confidence = sorted_plans[0]

        threshold = self.get_threshold()
        # Verify min class samples to avoid premature decisions
        plan_counts = dict(plans)
        if confidence >= threshold and plan_counts.get(top_plan_str, 0) >= MIN_CLASS_SAMPLES:
            plan_tuple = tuple(top_plan_str.split(','))
            return plan_tuple, round(confidence, 4), 'naive_bayes'

        return None, round(confidence, 4), 'uncertain'

    def learn(self, task, plan, source='teacher', success=True):
        """Increment word and plan frequency counters from a successful task run."""
        words = tokenize(task)
        if not words:
            return
        plan_str = ','.join(plan) if isinstance(plan, (list, tuple)) else str(plan)

        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            # Update plan count
            db.execute('INSERT INTO bayes_plan_counts(plan, count) VALUES(?, 1) ON CONFLICT(plan) DO UPDATE SET count=count+1', (plan_str,))
            
            # Update word counts
            for w in words:
                db.execute('INSERT INTO bayes_word_counts(word, plan, count) VALUES(?, ?, 1) ON CONFLICT(word, plan) DO UPDATE SET count=count+1', (w, plan_str))

            # Record audit log
            db.execute('''INSERT INTO bayes_audit(task, predicted_plan, confidence, actual_plan, source, success, created_at)
                          VALUES(?, ?, ?, ?, ?, ?, ?)''',
                       (task[:200], plan_str, 1.0 if source == 'naive_bayes' else 0.0, plan_str, source, 1 if success else 0, int(time.time())))
            db.commit()

    def record_decision(self, task, predicted_plan, confidence, actual_plan, source, success=True):
        """Record a routing decision into audit trail."""
        pred_str = ','.join(predicted_plan) if isinstance(predicted_plan, (list, tuple)) else (predicted_plan or '')
        act_str = ','.join(actual_plan) if isinstance(actual_plan, (list, tuple)) else str(actual_plan)
        with closing(self.connect()) as db:
            db.execute('''INSERT INTO bayes_audit(task, predicted_plan, confidence, actual_plan, source, success, created_at)
                          VALUES(?, ?, ?, ?, ?, ?, ?)''',
                       (task[:200], pred_str, float(confidence or 0.0), act_str, source, 1 if success else 0, int(time.time())))

    def daily_audit(self, hours=24):
        """Evaluate recent routing accuracy, compute token savings, and self-improve model weights."""
        since = int(time.time()) - (hours * 3600)
        with closing(self.connect()) as db:
            rows = db.execute('''SELECT id, task, predicted_plan, confidence, actual_plan, source, success, created_at
                                 FROM bayes_audit WHERE created_at >= ? ORDER BY id ASC''', (since,)).fetchall()

            total = len(rows)
            nb_routes = sum(1 for r in rows if r[5] == 'naive_bayes')
            teacher_routes = sum(1 for r in rows if r[5] in ('teacher', 'llm', 'fallback'))
            nb_successes = sum(1 for r in rows if r[5] == 'naive_bayes' and r[6] == 1)
            nb_failures = nb_routes - nb_successes

            # Vocabulary and plan counts
            vocab_count = db.execute('SELECT COUNT(*) FROM bayes_word_counts').fetchone()[0]
            plans_summary = dict(db.execute('SELECT plan, count FROM bayes_plan_counts').fetchall())

            # Self-Improvement: Prune noisy single-occurrence words if vocabulary exceeds 1,500
            pruned = 0
            if vocab_count > 1500:
                cur = db.execute('DELETE FROM bayes_word_counts WHERE count = 1')
                pruned = cur.rowcount

            # Self-Improvement: Calibrate confidence threshold based on accuracy
            current_th = self.get_threshold()
            new_th = current_th
            if nb_routes >= 3:
                accuracy = nb_successes / nb_routes
                if accuracy < 0.90:
                    # Too many mistakes: increase threshold to be more conservative
                    new_th = min(0.95, current_th + 0.03)
                elif accuracy == 1.0 and current_th > 0.80:
                    # Perfect accuracy: gradually allow more tasks to be handled locally
                    new_th = max(0.80, current_th - 0.01)
                if new_th != current_th:
                    self.set_threshold(new_th)

        # Token & cost savings estimate ($0.0002 per avoided LLM planner call)
        cost_saved_usd = round(nb_routes * 0.0002, 4)
        accuracy_pct = round((nb_successes / nb_routes * 100), 1) if nb_routes > 0 else 100.0

        return {
            'period_hours': hours,
            'total_routed': total,
            'naive_bayes_routed': nb_routes,
            'teacher_llm_routed': teacher_routes,
            'naive_bayes_accuracy_pct': accuracy_pct,
            'cost_saved_usd': cost_saved_usd,
            'pruned_words': pruned,
            'active_vocab_size': vocab_count - pruned,
            'plans_distribution': plans_summary,
            'confidence_threshold': new_th
        }
