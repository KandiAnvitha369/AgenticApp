import mimetypes
import os
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Union

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# Ensure environment variables are loaded from backend/.env or CWD
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)
load_dotenv()

DEFAULT_BUCKET = "upload-files-377074487303-ap-southeast-2-an"
DEFAULT_REGION = "ap-southeast-2"

# Transfer config for fast multi-threaded uploads/downloads
TRANSFER_CONFIG = TransferConfig(
    multipart_threshold=5 * 1024 * 1024,  # 5 MB
    max_concurrency=10,
    multipart_chunksize=5 * 1024 * 1024,
    use_threads=True,
)


class S3Service:
    """
    AWS S3 service wrapper for document management in SSC CGL RAG Chatbot.
    Handles uploading documents, listing files from S3, and syncing S3 files to local storage.
    """

    def __init__(
        self,
        bucket_name: Optional[str] = None,
        region_name: Optional[str] = None,
    ):
        self.bucket_name = (
            bucket_name
            or os.getenv("S3_BUCKET_NAME")
            or DEFAULT_BUCKET
        )
        self.region_name = (
            region_name
            or os.getenv("AWS_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
            or DEFAULT_REGION
        )

        client_kwargs: Dict[str, Any] = {"region_name": self.region_name}

        access_key = os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        if access_key and secret_key:
            client_kwargs["aws_access_key_id"] = access_key
            client_kwargs["aws_secret_access_key"] = secret_key

        self.client = boto3.client("s3", **client_kwargs)
        print(f"[INFO] Initialized S3Service with bucket: '{self.bucket_name}' in region: '{self.region_name}'")

    def list_documents(self, prefix: str = "") -> List[Dict[str, Any]]:
        """
        List all documents in the S3 bucket.
        Returns a sorted list of file metadata dictionaries.
        """
        paginator = self.client.get_paginator("list_objects_v2")
        documents = []

        try:
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj.get("Key", "")
                    # Skip directory markers or empty keys
                    if not key or key.endswith("/"):
                        continue

                    size = int(obj.get("Size", 0))
                    last_modified = obj.get("LastModified")
                    mtime = last_modified.timestamp() if last_modified else 0.0

                    documents.append({
                        "filename": Path(key).name,
                        "key": key,
                        "size_bytes": size,
                        "extension": Path(key).suffix.lower(),
                        "modified_at": mtime,
                        "etag": obj.get("ETag", "").strip('"'),
                    })
        except ClientError as e:
            print(f"[ERROR] Failed to list objects in bucket '{self.bucket_name}': {e}")
            raise

        # Sort alphabetically by filename
        documents.sort(key=lambda d: d["filename"].lower())
        return documents

    def upload_file(
        self,
        file_path: Union[str, Path],
        object_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Upload a local file to the S3 bucket.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if object_name is None:
            object_name = file_path.name

        content_type, _ = mimetypes.guess_type(str(file_path))
        extra_args: Dict[str, str] = {}
        if content_type:
            extra_args["ContentType"] = content_type

        try:
            self.client.upload_file(
                str(file_path),
                self.bucket_name,
                object_name,
                ExtraArgs=extra_args if extra_args else None,
                Config=TRANSFER_CONFIG,
            )
            size_bytes = file_path.stat().st_size
            print(f"[INFO] Uploaded '{file_path.name}' -> s3://{self.bucket_name}/{object_name} ({size_bytes} bytes)")
            return {
                "bucket": self.bucket_name,
                "key": object_name,
                "filename": file_path.name,
                "size_bytes": size_bytes,
            }
        except ClientError as e:
            print(f"[ERROR] Failed to upload '{file_path}' to S3: {e}")
            raise

    def upload_fileobj(
        self,
        file_obj: BinaryIO,
        object_name: str,
    ) -> Dict[str, Any]:
        """
        Upload a file-like object directly to S3.
        """
        content_type, _ = mimetypes.guess_type(object_name)
        extra_args: Dict[str, str] = {}
        if content_type:
            extra_args["ContentType"] = content_type

        try:
            self.client.upload_fileobj(
                file_obj,
                self.bucket_name,
                object_name,
                ExtraArgs=extra_args if extra_args else None,
                Config=TRANSFER_CONFIG,
            )
            print(f"[INFO] Uploaded file-like object -> s3://{self.bucket_name}/{object_name}")
            return {
                "bucket": self.bucket_name,
                "key": object_name,
                "filename": object_name,
            }
        except ClientError as e:
            print(f"[ERROR] Failed to upload fileobj to S3: {e}")
            raise

    def download_file(
        self,
        object_name: str,
        target_path: Union[str, Path],
    ) -> Path:
        """
        Download a file from S3 to a local path.
        """
        target_path = Path(target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            print(f"[INFO] Downloading s3://{self.bucket_name}/{object_name} -> {target_path}")
            self.client.download_file(
                self.bucket_name,
                object_name,
                str(target_path),
                Config=TRANSFER_CONFIG,
            )
            return target_path
        except ClientError as e:
            print(f"[ERROR] Failed to download '{object_name}' from S3: {e}")
            raise

    def sync_s3_to_local(
        self,
        local_dir: Union[str, Path],
    ) -> List[Path]:
        """
        Sync all documents from S3 bucket to local directory.
        Only downloads new or modified files (comparing file size).
        Returns list of local Path objects for all files synced from S3.
        """
        local_dir = Path(local_dir)
        local_dir.mkdir(parents=True, exist_ok=True)

        documents = self.list_documents()
        synced_paths: List[Path] = []

        for doc in documents:
            key = doc["key"]
            filename = doc["filename"]
            local_file = local_dir / filename

            # Check if file already exists locally with same size
            if local_file.exists():
                local_size = local_file.stat().st_size
                if local_size == doc["size_bytes"]:
                    print(f"[INFO] File '{filename}' is already up-to-date locally ({local_size} bytes). Skipping download.")
                    synced_paths.append(local_file)
                    continue

            # Download or re-download
            print(f"[INFO] Syncing '{key}' from S3 to '{local_file}'...")
            self.download_file(key, local_file)
            synced_paths.append(local_file)

        print(f"[INFO] S3 sync complete. Synced {len(synced_paths)} file(s) to '{local_dir}'.")
        return synced_paths

    def sync_local_to_s3(
        self,
        local_dir: Union[str, Path],
    ) -> List[str]:
        """
        Upload any local files in local_dir that are not already present in S3.
        Returns list of uploaded object names.
        """
        local_dir = Path(local_dir)
        if not local_dir.exists():
            return []

        existing_docs = {d["key"]: d["size_bytes"] for d in self.list_documents()}
        uploaded_keys: List[str] = []

        for file_path in local_dir.iterdir():
            if file_path.is_file() and not file_path.name.startswith("."):
                name = file_path.name
                size = file_path.stat().st_size
                if name in existing_docs and existing_docs[name] == size:
                    continue  # already in S3

                print(f"[INFO] Syncing local file '{name}' to S3...")
                self.upload_file(file_path, name)
                uploaded_keys.append(name)

        return uploaded_keys


_s3_service_instance: Optional[S3Service] = None


def get_s3_service() -> S3Service:
    """
    Get or create the singleton S3Service instance.
    """
    global _s3_service_instance
    if _s3_service_instance is None:
        _s3_service_instance = S3Service()
    return _s3_service_instance

