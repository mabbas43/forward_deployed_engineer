"""P8 — the ticket queue. Workers are stateless; the queue + checkpointer hold everything.

InMemoryQueue (dev/tests) models the SQS properties that matter:
- per-tenant lanes served round-robin → one tenant's 1,000 tickets can't starve another (fairness);
  SQS FIFO equivalent: MessageGroupId = tenant
- dedup id → the same submission enqueued twice is delivered once (SQS FIFO dedup)
- visibility timeout → an unacked message reappears (crashed worker); MUST exceed the graph deadline,
  otherwise a slow-but-alive worker's message is redelivered and executed twice
- max receives → dead-letter queue
SQSQueue (uv sync --extra infra) is the production adapter with the same interface.
"""

import itertools
import json
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field


@dataclass
class Message:
    id: str
    body: dict
    group: str
    receives: int = 0
    visible_at: float = 0.0
    receipt: str = field(default_factory=lambda: uuid.uuid4().hex)


class InMemoryQueue:
    def __init__(self, visibility_timeout: float = 360.0, max_receives: int = 3, clock=time.monotonic):
        self.vt, self.max_receives, self.clock = visibility_timeout, max_receives, clock
        self.lanes: OrderedDict[str, deque[Message]] = OrderedDict()
        self.inflight: dict[str, Message] = {}
        self.dlq: list[Message] = []
        self._dedup: dict[str, float] = {}
        self._rr = itertools.count()
        self._lock = threading.Lock()

    def send(self, body: dict, group: str, dedup_id: str | None = None) -> str | None:
        with self._lock:
            now = self.clock()
            if dedup_id and self._dedup.get(dedup_id, 0) > now:
                return None  # deduplicated (5-minute window like SQS FIFO)
            if dedup_id:
                self._dedup[dedup_id] = now + 300
            m = Message(uuid.uuid4().hex[:12], body, group)
            self.lanes.setdefault(group, deque()).append(m)
            return m.id

    def _requeue_expired(self):
        now = self.clock()
        for r, m in list(self.inflight.items()):
            if m.visible_at <= now:
                del self.inflight[r]
                if m.receives >= self.max_receives:
                    self.dlq.append(m)
                else:
                    m.receipt = uuid.uuid4().hex
                    self.lanes.setdefault(m.group, deque()).appendleft(m)

    def receive(self) -> Message | None:
        with self._lock:
            self._requeue_expired()
            groups = [g for g, q in self.lanes.items() if q]
            if not groups:
                return None
            g = groups[next(self._rr) % len(groups)]  # round-robin across tenants
            m = self.lanes[g].popleft()
            m.receives += 1
            m.visible_at = self.clock() + self.vt
            self.inflight[m.receipt] = m
            return m

    def ack(self, m: Message) -> None:
        with self._lock:
            self.inflight.pop(m.receipt, None)

    def extend(self, m: Message, seconds: float) -> None:
        with self._lock:
            if m.receipt in self.inflight:
                m.visible_at = self.clock() + seconds

    def depth(self) -> int:
        return sum(len(q) for q in self.lanes.values()) + len(self.inflight)


class SQSQueue:
    """Production adapter (FIFO queue + DLQ via redrive policy). Requires boto3."""

    def __init__(self, url: str, visibility_timeout: int = 360):
        import boto3

        self.url, self.vt, self.sqs = url, visibility_timeout, boto3.client("sqs")

    def send(self, body: dict, group: str, dedup_id: str | None = None):
        kw = {"QueueUrl": self.url, "MessageBody": json.dumps(body), "MessageGroupId": group}
        if dedup_id:
            kw["MessageDeduplicationId"] = dedup_id[:128]
        return self.sqs.send_message(**kw)["MessageId"]

    def receive(self) -> Message | None:
        r = self.sqs.receive_message(QueueUrl=self.url, MaxNumberOfMessages=1, WaitTimeSeconds=10,
                                     VisibilityTimeout=self.vt, AttributeNames=["All"])
        msgs = r.get("Messages", [])
        if not msgs:
            return None
        m = msgs[0]
        return Message(m["MessageId"], json.loads(m["Body"]), m["Attributes"].get("MessageGroupId", ""),
                       int(m["Attributes"].get("ApproximateReceiveCount", 1)), receipt=m["ReceiptHandle"])

    def ack(self, m: Message):
        self.sqs.delete_message(QueueUrl=self.url, ReceiptHandle=m.receipt)

    def extend(self, m: Message, seconds: float):
        self.sqs.change_message_visibility(QueueUrl=self.url, ReceiptHandle=m.receipt, VisibilityTimeout=int(seconds))

    def depth(self) -> int:
        a = self.sqs.get_queue_attributes(QueueUrl=self.url, AttributeNames=["ApproximateNumberOfMessages",
                                                                             "ApproximateNumberOfMessagesNotVisible"])
        return sum(int(v) for v in a["Attributes"].values())
