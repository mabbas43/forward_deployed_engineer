"""P8 load test. 50 then 200 concurrent users; record p95, queue depth, 429 rate, $ burn, escalation rate.

    uv run uvicorn atlas.api.main:app --port 8000      # terminal 1
    uv run --extra load locust -f load/locustfile.py --host http://localhost:8000 -u 50 -r 10
"""

import random
import uuid

from locust import HttpUser, between, task

from atlas.mcp.auth import mint_token

TICKETS = ["I forgot my password, please reset it", "My account is locked", "How many vacation days do I get?",
           "Outlook crashes when I open attachments", "Invoice INV-88231 was paid twice", "What does E-4471 mean?"]


class Employee(HttpUser):
    wait_time = between(0.5, 2)

    def on_start(self):
        tenant = random.choice(["acme", "acme", "acme", "globex"])  # a noisy neighbour + a small tenant
        self.h = {"Authorization": "Bearer " + mint_token(f"user{random.randint(1, 500)}@{tenant}.example", tenant,
                                                          "employee", aud="atlas-api")}

    @task(4)
    def submit(self):
        self.client.post("/tickets", json={"text": random.choice(TICKETS)},
                         headers={**self.h, "Idempotency-Key": uuid.uuid4().hex}, name="POST /tickets")

    @task(2)
    def ask(self):
        self.client.post("/ask", json={"question": random.choice(TICKETS)}, headers=self.h, name="POST /ask")

    @task(1)
    def health(self):
        self.client.get("/healthz")
