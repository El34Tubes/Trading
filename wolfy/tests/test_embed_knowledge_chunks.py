import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / 'embed_knowledge_chunks.py'
spec = importlib.util.spec_from_file_location('embed_knowledge_chunks', MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_default_provider_is_local_hash_fallback_without_config(monkeypatch):
    monkeypatch.delenv('WOLFY_EMBEDDING_PROVIDER', raising=False)
    monkeypatch.delenv('WOLFY_EMBEDDING_MODEL', raising=False)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)

    provider = mod.resolve_provider(provider='auto', model=None, require_semantic=False)

    assert provider.provider == 'local'
    assert provider.model == 'local_hashing_vector_v1'
    assert provider.method == 'local_hashing_vector_v1'
    assert provider.dimensions == 1536
    assert len(provider.embed_one('risk managed swing trading setup')) == 1536


def test_openai_provider_preserves_1536_dimensions_and_metadata(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    provider = mod.resolve_provider(provider='openai', model='text-embedding-3-small', require_semantic=True)

    assert provider.provider == 'openai'
    assert provider.model == 'text-embedding-3-small'
    assert provider.method == 'semantic_embedding_v1'
    assert provider.dimensions == 1536

    metadata = mod.embedding_metadata(provider)
    assert metadata['embedding_provider'] == 'openai'
    assert metadata['embedding_model'] == 'text-embedding-3-small'
    assert metadata['embedding_method'] == 'semantic_embedding_v1'
    assert metadata['embedding_dimensions'] == 1536


def test_reembed_clause_controls_provider_metadata_and_force_mode(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    provider = mod.resolve_provider(provider='openai', model='text-embedding-3-small', require_semantic=True)

    normal_clause, normal_params = mod.build_selection_filter(provider, reembed_all=False)
    force_clause, force_params = mod.build_selection_filter(provider, reembed_all=True)

    assert "metadata->>'embedding_provider' IS DISTINCT FROM %s" in normal_clause
    assert "metadata->>'embedding_model' IS DISTINCT FROM %s" in normal_clause
    assert normal_params == ['openai', 'text-embedding-3-small', 'semantic_embedding_v1', 1536]
    assert force_clause == 'TRUE'
    assert force_params == []


def test_smoke_test_sql_compares_vector_and_trigram_paths():
    sql = mod.SMOKE_TEST_SQL
    assert 'vector_rank' in sql
    assert 'trigram_rank' in sql
    assert '<=>' in sql
    assert 'similarity(content' in sql
