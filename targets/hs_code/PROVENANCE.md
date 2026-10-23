# Provenance of the copied CargoLint files

The sacrificial HS-code target runs CargoLint's HS-6 classifier. The files below are copied, unchanged, from CargoLint so that this folder runs on its own; nothing here imports from the CargoLint repo.

- **Source**: CargoLint (Turing College AI Engineering, Sprint 2), author Yong Zhang, local repo `C:\ai\CargoLint`
- **Commit**: `51ec448` ("docs(spec): absorb TARIC suggestion failures and apply the last analysis fixes (feature 004)")
- **Method**: `git -C C:/ai/CargoLint show 51ec448:<path> > <path>`. Each copy was checked against the commit's blob hash and is byte-identical.

## Copied files (all unchanged)

| Path | Purpose here |
|---|---|
| `agent/__init__.py` | Package marker |
| `agent/config.py` | Paths, model settings, `OPENROUTER_API_KEY` |
| `agent/llm.py` | Model client (`get_client`, `StructuredCaller`) |
| `agent/prompts.py` | Prompt fencing used by the classifier |
| `agent/routing.py` | Code validation used by the classifier |
| `agent/schemas.py` | Pydantic schemas (`Candidate`, `Classification`, ...) |
| `rag/__init__.py` | Package marker |
| `rag/nomenclature.py` | `NomenclatureIndex` over the CN 2026 chunks |
| `rag/retriever.py` | `BM25Index` and `HybridRetriever` |
| `rag/rules.py` | Imported by the classifier (shipper lookups, unused here) |
| `rag/translate.py` | Query translation and expansion (one model call) |
| `tools/__init__.py` | Tool registry the classifier registers itself in |
| `tools/classify_hs6.py` | The HS-6 classifier: `classify_lines`, `ClassifyContext` |
| `tools/common.py` | `LineText` and per-line execution |
| `data/nomenclature_2026.jsonl` | EU Combined Nomenclature 2026 chunks (5.2 MB) |
| `data/rules/firm_stop_words.json` | Rules data loaded by `rag/rules.py` |
| `data/rules/ics2_aliases.json` | Rules data |
| `data/rules/ics2_stop_words.json` | Rules data |
| `data/rules/ics2_unacceptable_terms.json` | Rules data |
| `data/model_prices.json` | Model prices read by `agent/llm.py` |
| `data/SOURCES.md` | Data provenance and licences |
| `tests/fakes.py` | `FakeRawClient`, the offline model double used by `tests/test_app.py` |

## Licences

From `data/SOURCES.md`:

- **EU Combined Nomenclature 2026**: CC BY 4.0 (Commission Decision 2011/833/EU). Source: European Commission.
- **DG TAXUD guidance on acceptable and unacceptable terms, and the ICS2 stop-word list**: European Commission documents, reuse permitted with acknowledgement.

## Deliberately not copied

| Left out | Why |
|---|---|
| `rag/loader.py` | It builds CargoLint's full knowledge base and pulls in the TARIC, PGP and BTI code. `kb.py` builds the light knowledge base this target needs instead. |
| `rag/embeddings.py` and the Chroma indexes (`store/chroma`, 134 MB; `store/chroma-bti`, 1.8 GB) | Retrieval here is BM25-only: `kb.NullVectorSearch` stands in for the vector leg, so there are no embeddings, no index build and no chromadb dependency. Retrieval quality doesn't matter for a target that exists to be attacked. |
| `rag/bti.py` and the BTI rulings | The precedent leg is off (`bti_vectors = None`, `precedents=False`). |
| CargoLint's UI, agent loop, store and other tools | Not needed to classify one line. |

## Written for this target

`app.py`, `kb.py`, `tests/test_app.py`, `pyproject.toml` and this file.
