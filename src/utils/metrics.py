from prometheus_client import Counter, Histogram, Gauge, start_http_server

# --- ОБЩИЕ МЕТРИКИ ---
SYSTEM_ERRORS = Counter('rex_system_errors_total', 'Total exceptions caught', ['service', 'error_type'])

# --- AI WORKER ---
AI_TASK_PROCESSED = Counter('rex_ai_tasks_total', 'Total AI tasks processed', ['mode', 'status'])
AI_TASK_DURATION = Histogram('rex_ai_duration_seconds', 'Time spent generating AI response', ['mode'])

# --- SENDER WORKER ---
MESSAGES_SENT = Counter('rex_messages_sent_total', 'Total messages sent to Telegram', ['status']) # status: success, failed, rate_limit
SENDER_QUEUE_LATENCY = Histogram('rex_sender_latency_seconds', 'Time from generation to sending')

# --- BOT POLLING ---
USER_UPDATES = Counter('rex_bot_updates_total', 'Total updates received from Telegram', ['type']) # message, callback
ACTIVE_USERS_GAUGE = Gauge('rex_active_users_now', 'Approximate active users processing')

# --- SCHEDULER ---
SCHEDULER_JOBS_RUN = Counter('rex_scheduler_jobs_total', 'Total cron jobs executed', ['job_id', 'status'])

def start_metrics_server(port):
    """Запускает веб-сервер для Prometheus на указанном порту."""
    try:
        start_http_server(port)
        print(f"📊 Metrics server started on port {port}")
    except Exception as e:
        print(f"❌ Failed to start metrics server: {e}")