import os
from pathlib import Path
from typing import Any, List, Union

from langchain_community.document_loaders import CSVLoader, Docx2txtLoader, JSONLoader, PyPDFLoader, TextLoader
from langchain_community.document_loaders.excel import UnstructuredExcelLoader


def load_file(file_path: Union[str, Path]) -> List[Any]:
    """
    Load a single document file and convert it into LangChain Document objects.
    Supported extensions: .pdf, .txt, .csv, .xlsx, .xls, .docx, .json
    """
    p = Path(file_path).resolve()
    suffix = p.suffix.lower()
    docs: List[Any] = []

    print(f"[DEBUG] [Consumer Loader] Loading file: {p} (type: {suffix})")

    try:
        if suffix == ".pdf":
            loader = PyPDFLoader(str(p))
            docs = loader.load()
        elif suffix == ".txt":
            try:
                loader = TextLoader(str(p), encoding="utf-8")
                docs = loader.load()
            except UnicodeDecodeError:
                loader = TextLoader(str(p))
                docs = loader.load()
        elif suffix == ".csv":
            loader = CSVLoader(str(p))
            docs = loader.load()
        elif suffix in (".xlsx", ".xls"):
            loader = UnstructuredExcelLoader(str(p))
            docs = loader.load()
        elif suffix == ".docx":
            loader = Docx2txtLoader(str(p))
            docs = loader.load()
        elif suffix == ".json":
            try:
                loader = JSONLoader(str(p), jq_schema=".", text_content=False)
                docs = loader.load()
            except Exception:
                loader = JSONLoader(str(p))
                docs = loader.load()
        else:
            print(f"[WARN] [Consumer Loader] Unsupported file extension '{suffix}' for file: {p}")
            return []

        print(f"[DEBUG] [Consumer Loader] Loaded {len(docs)} document chunks/pages from {p.name}")
    except Exception as e:
        print(f"[ERROR] [Consumer Loader] Failed to load {p.name}: {e}")

    return docs
