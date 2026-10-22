# Contracts

JSON Schemas for the payloads that cross the Python ⇄ TypeScript boundary (plan §20, Appendix B/C, §12.4).

| Schema | Produced by | Checked by |
| --- | --- | --- |
| `schemas/article.schema.json` | A3 Writer / A4 Editor (`article_versions.payload.article`) | `apps/api/tests/test_contracts.py` |
| `schemas/research-pack.schema.json` | A2 Research (`research_packs.payload`) | `apps/api/tests/test_contracts.py` |
| `schemas/feed-item.schema.json` | `GET /api/v1/feed` items | `apps/api/tests/test_contracts.py` |

The dashboard's types in `apps/web/lib/types.ts` mirror `apps/api/app/serializers.py`; change a schema, the
serializer and the TypeScript type in the same PR.
