import json
import os
import signal
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

try:
    from consumer.loader import load_file
    from consumer.vectorstore import FaissVectorStore
except ImportError:
    from loader import load_file
    from vectorstore import FaissVectorStore

# Load consumer-specific environment variables strictly from consumer/.env
_here = Path(__file__).resolve().parent
load_dotenv(dotenv_path=_here / ".env")
load_dotenv()

DEFAULT_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-southeast-2"
DEFAULT_QUEUE_NAME = "file-vector-queue"


def get_aws_credentials() -> Dict[str, Any]:
    """Extract optional explicit AWS credentials if configured."""
    kwargs: Dict[str, Any] = {}
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    if access_key and secret_key:
        kwargs["aws_access_key_id"] = access_key
        kwargs["aws_secret_access_key"] = secret_key
    return kwargs


def get_sqs_client(region_name: Optional[str] = None):
    """Returns a configured boto3 SQS client."""
    region = region_name or DEFAULT_REGION
    client_kwargs = {"region_name": region, **get_aws_credentials()}
    return boto3.client("sqs", **client_kwargs)


def get_s3_client(region_name: Optional[str] = None):
    """Returns a configured boto3 S3 client."""
    region = region_name or DEFAULT_REGION
    client_kwargs = {"region_name": region, **get_aws_credentials()}
    return boto3.client("s3", **client_kwargs)


class SQSConsumer:
    """
    Independent SQS Consumer service worker.
    Listens for file upload events, downloads files directly from S3,
    extracts content, generates embeddings, and incrementally updates the FAISS vector database on EFS.
    """

    def __init__(
        self,
        queue_url: Optional[str] = None,
        region_name: Optional[str] = None,
        vectorstore: Optional[FaissVectorStore] = None,
        persist_dir: Optional[str] = None,
    ):
        self.region_name = region_name or DEFAULT_REGION
        self.sqs = get_sqs_client(self.region_name)
        self.s3 = get_s3_client(self.region_name)
        self.running = True

        # Resolve Queue URL
        self.queue_url = queue_url or os.getenv("SQS_QUEUE_URL")
        if not self.queue_url:
            queue_name = os.getenv("SQS_QUEUE_NAME", DEFAULT_QUEUE_NAME)
            try:
                response = self.sqs.get_queue_url(QueueName=queue_name)
                self.queue_url = response["QueueUrl"]
                print(f"[INFO] Discovered SQS Queue URL: {self.queue_url}")
            except ClientError as e:
                print(f"[WARN] Could not find queue '{queue_name}' automatically: {e}")

        # Vector store instance (supports FAISS_PERSIST_DIR for shared Amazon EFS mount)
        target_persist_dir = persist_dir or os.getenv("FAISS_PERSIST_DIR", "faiss_store")
        self.vectorstore = vectorstore or FaissVectorStore(persist_dir=target_persist_dir)
        self.vectorstore.load()

        # Temporary download staging directory
        staging_env = os.getenv("SQS_STAGING_DIR")
        if staging_env:
            self.staging_dir = Path(staging_env)
        else:
            self.staging_dir = _here / "data" / "sqs_staging"
        self.staging_dir.mkdir(parents=True, exist_ok=True)

        print(f"[INFO] SQS Consumer initialized for queue: {self.queue_url} (vector store: {self.vectorstore.persist_dir})")

    def _parse_message_body(self, raw_body: str) -> Optional[Dict[str, str]]:
        """
        Extracts bucket and object key from the message body.
        Handles custom payload, S3 event notifications, and SNS-wrapped messages.
        """
        try:
            data = json.loads(raw_body)
        except Exception as e:
            print(f"[ERROR] Failed to parse JSON message body: {e}")
            return None

        # 1. Custom payload: {"bucket": "...", "key": "..."}
        if "bucket" in data and "key" in data:
            return {
                "bucket": data["bucket"],
                "key": urllib.parse.unquote_plus(data["key"]),
            }

        # 2. Standard S3 Event notification: {"Records": [{"s3": ...}]}
        if "Records" in data and len(data["Records"]) > 0:
            record = data["Records"][0]
            s3_data = record.get("s3", {})
            bucket = s3_data.get("bucket", {}).get("name")
            raw_key = s3_data.get("object", {}).get("key")
            if bucket and raw_key:
                return {
                    "bucket": bucket,
                    "key": urllib.parse.unquote_plus(raw_key),
                }

        # 3. SNS wrapped S3 message
        if "Message" in data and isinstance(data["Message"], str):
            return self._parse_message_body(data["Message"])

        print(f"[WARN] Unrecognized message structure: {data}")
        return None

    def process_message(self, message: Dict[str, Any]) -> bool:
        """
        Processes a single message: downloads file from S3, parses documents,
        embeds chunks into FAISS vectorstore, and deletes the message from SQS.
        """
        receipt_handle = message.get("ReceiptHandle")
        body_str = message.get("Body", "")

        parsed = self._parse_message_body(body_str)
        if not parsed:
            print("[WARN] Skipping message: unable to extract bucket and key.")
            self._delete_message(receipt_handle)
            return False

        bucket = parsed["bucket"]
        key = parsed["key"]
        print(f"\n[INFO] Processing SQS job -> Bucket: '{bucket}', Key: '{key}'")

        safe_filename = Path(key).name
        local_target_path = self.staging_dir / safe_filename

        try:
            # 1. Download file directly from S3
            print(f"[INFO] Downloading s3://{bucket}/{key} to {local_target_path}...")
            self.s3.download_file(bucket, key, str(local_target_path))

            # 2. Extract documents and pages
            print(f"[INFO] Extracting text from {local_target_path}...")
            docs = load_file(local_target_path)
            if not docs:
                print(f"[WARN] No readable text found in {local_target_path}")
            else:
                # 3. Add to Faiss vector store
                print(f"[INFO] Indexing {len(docs)} documents into FAISS vector store...")
                self.vectorstore.add_documents(docs)
                print(f"[SUCCESS] Successfully indexed '{key}' into vector database!")

            # 4. Delete message from SQS on success
            self._delete_message(receipt_handle)
            return True

        except Exception as e:
            print(f"[ERROR] Failed to process file '{key}': {e}")
            return False
        finally:
            # Clean up temporary staging file
            if local_target_path.exists():
                try:
                    local_target_path.unlink()
                except Exception:
                    pass

    def _delete_message(self, receipt_handle: str):
        """Deletes a processed message from SQS."""
        try:
            self.sqs.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle,
            )
            print("[INFO] Message deleted from SQS.")
        except ClientError as e:
            print(f"[ERROR] Failed to delete SQS message: {e}")

    def poll_messages(self, max_messages: int = 5, wait_time_seconds: int = 20) -> int:
        """
        Polls SQS for messages once (using long-polling) and processes them.
        Returns the number of messages processed.
        """
        if not self.queue_url:
            print("[ERROR] SQS_QUEUE_URL is not set.")
            return 0

        try:
            response = self.sqs.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=min(max_messages, 10),
                WaitTimeSeconds=wait_time_seconds,
                VisibilityTimeout=300,  # 5 minutes to chunk & embed
            )
        except ClientError as e:
            print(f"[ERROR] Failed to receive messages from SQS: {e}")
            return 0

        messages = response.get("Messages", [])
        if not messages:
            return 0

        print(f"[INFO] Received {len(messages)} message(s) from SQS.")
        processed_count = 0
        for msg in messages:
            success = self.process_message(msg)
            if success:
                processed_count += 1

        return processed_count

    def _handle_signal(self, signum, frame):
        signal_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        print(f"\n[INFO] Received {signal_name}. Initiating graceful shutdown of SQS consumer worker...")
        self.running = False

    def start_polling_loop(self, wait_time_seconds: int = 20, sleep_interval: int = 2):
        """
        Runs an independent polling loop for continuous background processing on ECS.
        Gracefully terminates on SIGTERM / SIGINT.
        """
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        print(f"[INFO] Starting continuous SQS consumer worker on {self.queue_url}...")
        print("[INFO] Worker is active and listening for SQS messages...")

        while self.running:
            try:
                processed = self.poll_messages(max_messages=5, wait_time_seconds=wait_time_seconds)
                if processed == 0 and self.running:
                    time.sleep(sleep_interval)
            except Exception as e:
                print(f"[ERROR] Unexpected error in polling loop: {e}")
                if self.running:
                    time.sleep(sleep_interval)

        print("[INFO] SQS consumer worker shut down cleanly.")


if __name__ == "__main__":
    consumer = SQSConsumer()
    consumer.start_polling_loop()
