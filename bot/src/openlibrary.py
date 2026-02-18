"""Open Library API integration module.

This module provides functions to search for books using the Open Library API.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Open Library API base URL
OPEN_LIBRARY_BASE_URL = "https://openlibrary.org"


async def search_books(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search for books by title, author, or general query.
    
    Args:
        query: Search query (title, author, ISBN, etc.)
        limit: Maximum number of results to return
        
    Returns:
        List of book dictionaries with basic information
    """
    books: list[dict[str, Any]] = []
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Search by general query
            search_url = f"{OPEN_LIBRARY_BASE_URL}/search.json"
            params = {
                "q": query,
                "limit": limit,
                "fields": "key,title,author_name,first_publish_year,isbn,publisher,cover_i,number_of_pages_median,ia",
            }
            
            response = await client.get(search_url, params=params)
            response.raise_for_status()
            
            data = response.json()
            docs = data.get("docs", [])
            
            for doc in docs:
                book = {
                    "key": doc.get("key", ""),
                    "title": doc.get("title", "Unknown"),
                    "author": ", ".join(doc.get("author_name", [])) or "Unknown",
                    "year": doc.get("first_publish_year"),
                    "isbn": doc.get("isbn", [None])[0] if doc.get("isbn") else None,
                    "publisher": doc.get("publisher", [None])[0] if doc.get("publisher") else None,
                    "cover_url": None,
                    "pages": doc.get("number_of_pages_median"),
                }
                
                # Get cover image
                cover_i = doc.get("cover_i")
                if cover_i:
                    book["cover_url"] = f"https://covers.openlibrary.org/b/id/{cover_i}-M.jpg"
                
                books.append(book)
                
    except httpx.HTTPError as e:
        logger.error(f"Open Library API error: {e}")
    except Exception as e:
        logger.error(f"Error searching books: {e}")
    
    return books


async def get_book_details(work_key: str) -> dict[str, Any] | None:
    """Get detailed information about a book by its work key.
    
    Args:
        work_key: Open Library work key (e.g., "/works/OL123W")
        
    Returns:
        Dictionary with detailed book information
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{OPEN_LIBRARY_BASE_URL}{work_key}.json"
            response = await client.get(url)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract relevant fields
            details = {
                "key": data.get("key", ""),
                "title": data.get("title", "Unknown"),
                "description": None,
                "subjects": [],
                "authors": [],
                "covers": [],
            }
            
            # Get description
            desc = data.get("description")
            if isinstance(desc, str):
                details["description"] = desc
            elif isinstance(desc, dict):
                details["description"] = desc.get("value", "")
            
            # Get subjects
            details["subjects"] = data.get("subjects", [])[:10]
            
            # Get authors
            author_refs = data.get("authors", [])
            if author_refs:
                author_keys = [a.get("author", {}).get("key") for a in author_refs]
                for author_key in author_keys[:3]:
                    if author_key:
                        author_url = f"{OPEN_LIBRARY_BASE_URL}{author_key}.json"
                        try:
                            author_resp = await client.get(author_url)
                            if author_resp.status_code == 200:
                                author_data = author_resp.json()
                                details["authors"].append(author_data.get("name", "Unknown"))
                        except Exception:
                            pass
            
            # Get covers
            details["covers"] = data.get("covers", [])
            
            return details
            
    except httpx.HTTPError as e:
        logger.error(f"Open Library API error: {e}")
    except Exception as e:
        logger.error(f"Error getting book details: {e}")
    
    return None


def format_book_search_results(books: list[dict[str, Any]], query: str) -> str:
    """Format book search results as a readable string.
    
    Args:
        books: List of book dictionaries
        query: Original search query
        
    Returns:
        Formatted string with book information
    """
    if not books:
        return f"🔍 No se encontraron libros para: *{query}*"
    
    lines = [f"🔍 *Resultados para:* \"{query}\"\n"]
    
    for i, book in enumerate(books, 1):
        title = book.get("title", "Unknown")
        author = book.get("author", "Unknown")
        year = book.get("year", "?")
        cover_url = book.get("cover_url")
        
        lines.append(f"{i}. *{title}*")
        lines.append(f"   ✍️ {author} ({year})")
        
        if cover_url:
            lines.append(f"   🖼️ Portada: {cover_url}")
        
        lines.append("")
    
    return "\n".join(lines)
