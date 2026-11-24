# Literature Search Data Sources

The service searches **all sources by default** when `sources` is not specified. Local knowledge base results are always displayed first.

| Source   | Description                  | Content Type                 |
| -------- | ---------------------------- | ---------------------------- |
| local    | RAGFlow local knowledge base | Imported full-text documents |
| arxiv    | arXiv preprint platform      | Physics, Math, CS, etc.      |
| crossref | DOI metadata database        | Journal paper metadata       |
| openalex | OpenAlex academic graph      | 250M+ academic papers        |

## Search response fields

Each article in the response contains:

| Field    | Type    | Description                                 |
| -------- | ------- | ------------------------------------------- |
| title    | string  | Article title                               |
| authors  | list    | Author list                                 |
| abstract | string  | Article abstract                            |
| year     | integer | Publication year                            |
| journal  | string  | Journal name                                |
| doi      | string  | DOI identifier                              |
| url      | string  | Original link                               |
| score    | float   | Relevance score                             |
| source   | string  | Data source (local/arxiv/crossref/openalex) |

Additional source-specific fields may be preserved in `extra_fields` inside `papers/literature_index.json`.

Common full-text or open-access hints include:

| Field                        | Meaning                                                   |
| ---------------------------- | --------------------------------------------------------- |
| pdf_url                      | Direct PDF URL if the service provides one                |
| full_text_url / fulltext_url | Candidate full-text URL                                   |
| download_url                 | Candidate download URL                                    |
| open_access                  | Open-access metadata block                                |
| best_oa_location             | Preferred open-access location from OpenAlex-like sources |
| primary_location             | Primary publication location metadata                     |

These fields are hints for Claude/user follow-up. The search command should still be considered successful even when no original PDF is available.

## Source Behavior Notes

- `local`: may already represent full text in the local knowledge base, but the saved workspace artifact is still a Markdown note.
- `arxiv`: often has a predictable PDF URL. Convert `/abs/<id>` to `/pdf/<id>.pdf` when the original PDF is needed.
- `crossref`: usually returns metadata and DOI links. It often does not provide open PDFs.
- `openalex`: may include open-access locations, but availability varies by paper.
