"""OpenCode integration module.

This module provides a client to interact with OpenCode CLI server
via its REST API.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import pathlib
import subprocess
import time
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

# OpenCode server configuration
OPENCODE_HOST = "127.0.0.1"
OPENCODE_PORT = 4096
OPENCODE_BASE_URL = f"http://{OPENCODE_HOST}:{OPENCODE_PORT}"

# Default model (text only)
OPENCODE_PROVIDER_ID = "zai-coding-plan"
OPENCODE_MODEL_ID = "glm-4.7"

# Vision model (for messages with images)
OPENCODE_VISION_PROVIDER_ID = "groq"
OPENCODE_VISION_MODEL_ID = "meta-llama/llama-4-scout-17b-16e-instruct"


def _ensure_auth() -> None:
    """Write auth.json with available API keys so OpenCode can use them."""
    auth_dir = pathlib.Path.home() / ".local" / "share" / "opencode"
    auth_dir.mkdir(parents=True, exist_ok=True)
    auth_file = auth_dir / "auth.json"

    # Read existing auth to preserve other providers
    auth_data: dict[str, Any] = {}
    if auth_file.exists():
        try:
            auth_data = json.loads(auth_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    changed = False
    zhipu_key = os.environ.get("ZHIPU_API_KEY", "")
    if zhipu_key and auth_data.get("zai-coding-plan", {}).get("apiKey") != zhipu_key:
        auth_data["zai-coding-plan"] = {"apiKey": zhipu_key}
        changed = True

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key and auth_data.get("anthropic", {}).get("apiKey") != anthropic_key:
        auth_data["anthropic"] = {"apiKey": anthropic_key}
        changed = True

    if changed:
        auth_file.write_text(json.dumps(auth_data))
        logger.info("Updated OpenCode auth.json")


class OpenCodeClient:
    """Client for interacting with OpenCode server via REST API."""

    def __init__(self, directory: str | None = None):
        self.directory = directory or str(settings.vault_path)
        self.server_process: subprocess.Popen | None = None
        self.client: httpx.AsyncClient | None = None
        self._server_url: str | None = None

    async def start_server(self, timeout: int = 30) -> str:
        """Start OpenCode server if not already running."""
        if self._server_url:
            return self._server_url

        # Always ensure auth is up to date
        _ensure_auth()

        # Check if server is already running
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{OPENCODE_BASE_URL}/global/health", timeout=2.0)
                if resp.status_code == 200:
                    self._server_url = OPENCODE_BASE_URL
                    logger.info(f"OpenCode server already running at {OPENCODE_BASE_URL}")
                    return self._server_url
        except (httpx.ConnectError, httpx.TimeoutException):
            pass

        # Start OpenCode server
        logger.info("Starting OpenCode server...")

        config_content = {
            "directory": self.directory,
            "model": f"{OPENCODE_PROVIDER_ID}/{OPENCODE_MODEL_ID}",
        }

        self.server_process = subprocess.Popen(
            ["opencode", "serve", f"--hostname={OPENCODE_HOST}", f"--port={OPENCODE_PORT}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                **os.environ,
                "OPENCODE_CONFIG_CONTENT": json.dumps(config_content),
            },
        )

        # Wait for server to be ready
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{OPENCODE_BASE_URL}/global/health", timeout=2.0)
                    if resp.status_code == 200:
                        self._server_url = OPENCODE_BASE_URL
                        logger.info(f"OpenCode server started at {OPENCODE_BASE_URL}")
                        return self._server_url
            except (httpx.ConnectError, httpx.TimeoutException):
                await asyncio.sleep(0.5)

        if self.server_process.poll() is not None:
            stderr = self.server_process.stderr.read().decode() if self.server_process.stderr else ""
            raise RuntimeError(f"OpenCode server failed to start: {stderr}")

        raise RuntimeError(f"OpenCode server did not respond within {timeout}s")

    async def stop_server(self) -> None:
        """Stop OpenCode server if we started it."""
        if self.server_process:
            logger.info("Stopping OpenCode server...")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
            self.server_process = None
            self._server_url = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if not self.client:
            self.client = httpx.AsyncClient(
                base_url=OPENCODE_BASE_URL,
                timeout=300.0,
                headers={"x-opencode-directory": self.directory},
            )
        return self.client

    async def create_session(self, title: str | None = None) -> dict[str, Any]:
        """Create a new OpenCode session."""
        client = self._get_client()
        body = {}
        if title:
            body["title"] = title
        resp = await client.post("/session", json=body)
        resp.raise_for_status()
        return resp.json()

    async def send_message(
        self,
        session_id: str,
        prompt: str,
        agent: str | None = None,
        model: dict[str, str] | None = None,
        images: list[tuple[bytes, str]] | None = None,
    ) -> dict[str, Any]:
        """Send a message to OpenCode and wait for the response."""
        client = self._get_client()

        parts: list[dict[str, Any]] = []

        if images:
            for image_data, mime_type in images:
                b64 = base64.b64encode(image_data).decode("ascii")
                parts.append({
                    "type": "file",
                    "mime": mime_type,
                    "url": f"data:{mime_type};base64,{b64}",
                })

        parts.append({"type": "text", "text": prompt})

        body: dict[str, Any] = {"parts": parts}
        if agent:
            body["agent"] = agent
        if model:
            body["model"] = model

        resp = await client.post(f"/session/{session_id}/message", json=body)
        resp.raise_for_status()

        # Handle empty responses gracefully
        if not resp.content:
            return {"info": {}, "parts": []}
        return resp.json()

    async def _extract_text_from_images(
        self,
        session_id: str,
        images: list[tuple[bytes, str]],
        context: str,
    ) -> str:
        """Use the vision model to extract text/content from images.

        This is the first step of the two-step process for image handling.
        """
        vision_model = {
            "providerID": OPENCODE_VISION_PROVIDER_ID,
            "modelID": OPENCODE_VISION_MODEL_ID,
        }

        vision_prompt = (
            "Analyze the attached image(s) and extract ALL visible information:\n"
            "- If it's a book cover: title, author, subtitle, publisher\n"
            "- If it's a book page: page number, all readable text, highlights/underlines\n"
            "- If it's handwritten notes: transcribe everything\n"
            "- If it's a screenshot: describe and extract text\n"
            "Mark anything illegible with [illegible]. Do NOT invent text.\n"
            "Return ONLY the extracted information, no commentary.\n"
            f"\nUser's context: {context}"
        )

        response = await self.send_message(
            session_id, vision_prompt, model=vision_model, images=images,
        )

        info = response.get("info", {})
        error = info.get("error")
        if error:
            error_msg = error.get("data", {}).get("message", str(error))
            raise RuntimeError(f"Vision extraction failed: {error_msg}")

        parts = []
        for part in response.get("parts", []):
            if part.get("type") == "text":
                parts.append(part.get("text", ""))

        return "\n".join(parts)

    @staticmethod
    def _extract_text_parts(response: dict[str, Any]) -> str:
        """Extract text from response parts, raising on API errors."""
        info = response.get("info", {})
        error = info.get("error")
        if error:
            error_msg = error.get("data", {}).get("message", str(error))
            raise RuntimeError(f"OpenCode API error: {error_msg}")

        text_parts = []
        for part in response.get("parts", []):
            if part.get("type") == "text":
                text_parts.append(part.get("text", ""))

        return "\n".join(text_parts)

    async def execute_task(
        self,
        prompt: str,
        agent: str | None = None,
        session_title: str | None = None,
        images: list[tuple[bytes, str]] | None = None,
    ) -> str:
        """Execute a task with OpenCode and return the response.

        When images are present, uses a two-step process:
        1. Extract text/content from images using the vision model (Groq)
        2. Send extracted text + original prompt to the target agent with its own model
        """
        await self.start_server()

        session = await self.create_session(title=session_title)
        session_id = session["id"]

        default_model = {
            "providerID": OPENCODE_PROVIDER_ID,
            "modelID": OPENCODE_MODEL_ID,
        }

        if images:
            # Step 1: Extract content from images using vision model
            extracted = await self._extract_text_from_images(
                session_id, images, context=prompt,
            )

            # Step 2: Send extracted content to the target agent
            augmented_prompt = (
                f"The user sent {len(images)} image(s). "
                f"Here is the extracted content from the image(s):\n\n"
                f"---\n{extracted}\n---\n\n"
                f"User's request: {prompt}"
            )

            response = await self.send_message(
                session_id, augmented_prompt, agent=agent, model=default_model,
            )
        else:
            response = await self.send_message(
                session_id, prompt, agent=agent, model=default_model,
            )

        return self._extract_text_parts(response)

    async def close(self) -> None:
        """Close the client and optionally stop the server."""
        if self.client:
            await self.client.aclose()
            self.client = None


# Global client instance
_client: OpenCodeClient | None = None


def get_client() -> OpenCodeClient:
    """Get or create the global OpenCode client."""
    global _client
    if _client is None:
        _client = OpenCodeClient()
    return _client


async def execute_opencode_task(
    prompt: str,
    agent: str | None = None,
    images: list[tuple[bytes, str]] | None = None,
) -> str:
    """Execute a task with OpenCode."""
    client = get_client()
    return await client.execute_task(prompt, agent=agent, images=images)
