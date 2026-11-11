from pathlib import Path
from typing import List, Any, Union
from langchain_community.document_loaders import PyPDFLoader, TextLoader, CSVLoader
from langchain_community.document_loaders import Docx2txtLoader
from langchain_community.document_loaders.excel import UnstructuredExcelLoader
from langchain_community.document_loaders import JSONLoader


def load_file(file_path: Union[str, Path]) -> List[Any]:
    """
    Load a single document file and convert it into LangChain Document objects.
    Supported extensions: .pdf, .txt, .csv, .xlsx, .xls, .docx, .json
    """
    p = Path(file_path).resolve()
    suffix = p.suffix.lower()
    docs: List[Any] = []

    print(f"[DEBUG] Loading file: {p} (type: {suffix})")

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
                # Fallback to default json loader without jq_schema if jq is unavailable
                loader = JSONLoader(str(p))
                docs = loader.load()
        else:
            print(f"[WARN] Unsupported file extension '{suffix}' for file: {p}")
            return []

        print(f"[DEBUG] Loaded {len(docs)} document chunks/pages from {p.name}")
    except Exception as e:
        print(f"[ERROR] Failed to load {p.name}: {e}")

    return docs


def load_documents_from_paths(file_paths: List[Union[str, Path]]) -> List[Any]:
    """
    Load documents from an explicit list of file paths.
    """
    all_docs: List[Any] = []
    for fp in file_paths:
        docs = load_file(fp)
        all_docs.extend(docs)

    print(f"[INFO] Total loaded documents from {len(file_paths)} files: {len(all_docs)}")
    return all_docs


def load_all_documents(data_dir: str = "data") -> List[Any]:
    """
    Load all supported files from the data directory and convert to LangChain document structure.
    Supported: PDF, TXT, CSV, Excel, Word, JSON
    """
    data_path = Path(data_dir)
    if not data_path.is_absolute():
        project_root = Path(__file__).resolve().parent.parent.parent
        data_path = project_root / data_dir

    data_path = data_path.resolve()
    print(f"[DEBUG] Data path: {data_path}")

    if not data_path.exists():
        print(f"[WARN] Data path does not exist: {data_path}")
        return []

    supported_patterns = ["*.pdf", "*.txt", "*.csv", "*.xlsx", "*.xls", "*.docx", "*.json"]
    file_paths: List[Path] = []
    for pattern in supported_patterns:
        file_paths.extend(data_path.rglob(pattern))

    # Filter out hidden or temporary files (e.g. starting with . or ~$)
    file_paths = [
        f for f in file_paths
        if not f.name.startswith(".") and not f.name.startswith("~$")
    ]

    return load_documents_from_paths(file_paths)


# Example usage
if __name__ == "__main__":
    docs = load_all_documents("data")
    print(f"Loaded {len(docs)} documents.")
    print("Example document:", docs[0] if docs else None)
