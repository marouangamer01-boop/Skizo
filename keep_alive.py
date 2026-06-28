import os
import threading
import time
import math


def _cpu_tickle():
    """
    Lightweight endless loop that keeps CPU usage at ~1-2%.
    Does simple math for a short burst, then sleeps — repeat forever.
    """
    n = 0
    while True:
        # ~10 ms of real work per iteration
        for _ in range(5000):
            n = math.sqrt(n * n + 1)
        time.sleep(0.5)   # rest for 500 ms → ≈2% duty cycle


def keep_alive():
    """Start the CPU tickle thread and print the public ping URL."""
    t = threading.Thread(target=_cpu_tickle, daemon=True, name="cpu-tickle")
    t.start()

    domains = os.environ.get("REPLIT_DOMAINS", "")
    if domains:
        domain = domains.split(",")[0].strip()
        ping_url = f"https://{domain}/api/healthz"
    else:
        ping_url = "http://localhost:8080/api/healthz"

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  Keep-alive ping URL:")
    print(f"  {ping_url}")
    print("  Add this to UptimeRobot / cron-job.org")
    print("  to keep the bot running 24/7.")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
