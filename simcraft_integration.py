# simcraft_integration.py — SimCraft API client for Luminisbot

import aiohttp
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

SIMCRAFT_API_URL = os.getenv('SIMCRAFT_API_URL', 'https://sim.flipflix.no')
SIMCRAFT_API_KEY = os.getenv('SIMCRAFT_API_KEY', '')
SIMCRAFT_RESULT_URL = os.getenv('SIMCRAFT_RESULT_URL', SIMCRAFT_API_URL)

# Track running sims per Discord user ID to enforce one-at-a-time
_active_sims: dict[int, str] = {}


def has_active_sim(user_id: int) -> bool:
    return user_id in _active_sims


def get_active_sim_id(user_id: int) -> str | None:
    return _active_sims.get(user_id)


def set_active_sim(user_id: int, job_id: str):
    _active_sims[user_id] = job_id


def clear_active_sim(user_id: int):
    _active_sims.pop(user_id, None)


async def submit_sim(simc_input: str, sim_type: str) -> dict:
    """Submit a simulation to the SimCraft backend.

    Returns dict with 'id', 'status', 'created_at' on success.
    Raises ValueError on API errors.
    """
    if not SIMCRAFT_API_KEY:
        raise ValueError("SIMCRAFT_API_KEY is not configured.")

    payload = {
        "simc_input": simc_input,
        "sim_type": sim_type,
        "api_key": SIMCRAFT_API_KEY,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{SIMCRAFT_API_URL}/api/bot/sim",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            data = await resp.json()
            if resp.status != 200:
                detail = data.get("detail", "Unknown error from SimCraft API.")
                raise ValueError(detail)
            return data


async def poll_sim_status(job_id: str, timeout_seconds: int = 600, interval: float = 5.0) -> dict:
    """Poll a job until it completes or times out.

    Returns the final status dict with 'status', 'result', 'error' etc.
    Raises TimeoutError if the sim doesn't finish in time.
    """
    elapsed = 0.0
    async with aiohttp.ClientSession() as session:
        while elapsed < timeout_seconds:
            async with session.get(
                f"{SIMCRAFT_API_URL}/api/sim/{job_id}",
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
                status = data.get("status", "")
                if status in ("done", "failed", "cancelled"):
                    return data
            await asyncio.sleep(interval)
            elapsed += interval

    raise TimeoutError(f"Simulation {job_id} did not complete within {timeout_seconds}s.")


def build_result_url(job_id: str) -> str:
    return f"{SIMCRAFT_RESULT_URL}/sim/{job_id}"


async def fetch_text_from_url(url: str) -> str:
    """Fetch plain text content from a URL (pastebin, hastebin, etc)."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                raise ValueError(f"Failed to fetch URL (HTTP {resp.status}).")
            text = await resp.text()
            if len(text) < 50:
                raise ValueError("URL content too short to be a valid SimC string.")
            return text
