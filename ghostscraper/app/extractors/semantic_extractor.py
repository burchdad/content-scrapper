from app.extractors.base import ExtractionResult


class SemanticExtractor:
    async def extract(self, text: str, schema: dict) -> ExtractionResult:
        return ExtractionResult(data={}, notes=["semantic_extraction_disabled"])
