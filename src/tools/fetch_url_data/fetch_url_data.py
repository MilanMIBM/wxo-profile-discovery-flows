from typing import List, Union

from ibm_watsonx_orchestrate.agent_builder.tools import tool
from pydantic import BaseModel, Field


class FetchUrlDataOutput(BaseModel):
    """The converted documents, one string per requested URL."""

    documents: List[str] = Field(
        ...,
        description="""The converted content, one entry per requested URL, in the order the URLs were supplied. Always a list, even for a single URL. A URL that failed to convert yields an entry beginning with 'ERROR:' followed by the reason.""",
    )


@tool(
    name="fetch_url_data",
    display_name="Fetch URL Data",
    description="""Fetches one or more URLs and converts each document into Markdown or plain text using Docling. Use this to read the contents of a web page or an online document (PDF, DOCX, PPTX, HTML) so the text can be summarized or analyzed.""",
)
def fetch_url_data(
    urls: Union[str, List[str]],
    return_markdown_output: bool = True,
) -> FetchUrlDataOutput:
    """Fetches and converts the content of one or more URLs using Docling.

    Each URL is downloaded and parsed with Docling's DocumentConverter, then exported
    as Markdown or plain text. The result is always a list of strings, one per URL, in
    the order supplied - a single URL yields a one-element list. A failure on one URL
    does not abort the others; that entry is an 'ERROR: ...' string instead.

    Args:
        urls (Union[str, List[str]]): A single URL or a list of URLs to fetch and convert.
        return_markdown_output (bool): True (default) to export Markdown, False for plain text.

    Returns:
        FetchUrlDataOutput: The converted content, one string per requested URL.
    """
    from docling.document_converter import DocumentConverter

    url_list: List[str] = [urls] if isinstance(urls, str) else list(urls)

    converter = DocumentConverter()
    documents: List[str] = []

    for url in url_list:
        try:
            result = converter.convert(url)
            documents.append(
                result.document.export_to_markdown()
                if return_markdown_output
                else result.document.export_to_text()
            )
        except Exception as exc:  # noqa: BLE001 - one bad URL must not fail the batch
            documents.append(
                f"ERROR: {url} could not be converted - {type(exc).__name__}: {exc}"
            )

    return FetchUrlDataOutput(documents=documents)
