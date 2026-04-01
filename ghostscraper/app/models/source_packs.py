from pydantic import BaseModel, Field


class SourcePack(BaseModel):
    pack_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    description: str = Field(min_length=1)
    domains: list[str] = []
    seed_urls: list[str] = []
    query_terms: list[str] = []
    intent_terms: dict[str, list[str]] = {}
    intent_query_templates: dict[str, list[str]] = {}


class ResolvedSourcePacks(BaseModel):
    pack_ids: list[str] = []
    categories: list[str] = []
    domains: list[str] = []
    domain_categories: dict[str, list[str]] = {}
    seed_urls: list[str] = []
    query_terms: list[str] = []
    query_templates: list[str] = []