"""Unit tests for code tokenizer, BM25, and hybrid retriever with RRF."""

from app.models import RepoChunk
from app.rag.indexer import bm25_cache, index_chunks, tokenize_code
from app.rag.retriever import retrieve


def test_tokenize_code():
    tokens = tokenize_code("function getUserById(userId) { const auth_token = 123; }")
    # Subwords and original tokens preserved
    assert "getuserbyid" in tokens
    assert "get" in tokens
    assert "user" in tokens
    assert "id" in tokens
    assert "auth_token" in tokens
    assert "auth" in tokens
    assert "token" in tokens


def test_retrieval_bm25_and_hybrid():
    repo_id = "test_retrieval_repo"
    chunks = [
        RepoChunk(
            id="1",
            repo_id=repo_id,
            chunk_id="auth.py:login:1",
            path="auth.py",
            language="python",
            kind="function",
            symbol_name="login",
            start_line=1,
            end_line=20,
            text="def login(username, password):\n    validate_credentials(username, password)\n    return token",
            embed_text="auth.py > login\ndef login(username, password):\n    validate_credentials(username, password)\n    return token",
        ),
        RepoChunk(
            id="2",
            repo_id=repo_id,
            chunk_id="db.py:connect:1",
            path="db.py",
            language="python",
            kind="function",
            symbol_name="connect",
            start_line=1,
            end_line=15,
            text="def connect(db_url):\n    engine = create_engine(db_url)\n    return engine",
            embed_text="db.py > connect\ndef connect(db_url):\n    engine = create_engine(db_url)\n    return engine",
        ),
    ]

    index_chunks(repo_id, chunks)

    # BM25 Search
    bm25_res, bm25_conf = retrieve(repo_id, "validate_credentials login", mode="bm25", top_k=2)
    assert len(bm25_res) > 0
    assert bm25_res[0].path == "auth.py"
    assert bm25_res[0].bm25_rank == 1
    assert bm25_conf > 0.0

    # Hybrid Search
    hybrid_res, hybrid_conf = retrieve(repo_id, "database connection create_engine", mode="hybrid", top_k=2)
    assert len(hybrid_res) > 0
    top_result = hybrid_res[0]
    assert top_result.path == "db.py"
    assert top_result.score > 0.0
    assert 0.0 <= hybrid_conf <= 1.0


def test_retrieval_filtering():
    repo_id = "test_filter_repo"
    chunks = [
        RepoChunk(
            id="1",
            repo_id=repo_id,
            chunk_id="app/main.py:app:1",
            path="app/main.py",
            language="python",
            kind="module",
            symbol_name=None,
            start_line=1,
            end_line=10,
            text="app = FastAPI()",
            embed_text="app/main.py\napp = FastAPI()",
        ),
        RepoChunk(
            id="2",
            repo_id=repo_id,
            chunk_id="tests/test_main.py:test_app:1",
            path="tests/test_main.py",
            language="python",
            kind="test",
            symbol_name="test_app",
            start_line=1,
            end_line=10,
            text="def test_app():\n    assert client.get('/health').status_code == 200",
            embed_text="tests/test_main.py > test_app\ndef test_app(): assert 200",
        ),
    ]
    index_chunks(repo_id, chunks)

    # Filter by kind
    filtered_res, _ = retrieve(repo_id, "FastAPI app", mode="bm25", top_k=5, filters={"kind": "module"})
    assert len(filtered_res) == 1
    assert filtered_res[0].path == "app/main.py"
