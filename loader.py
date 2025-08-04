# loader.py
import json
import os
import subprocess
import sys
import time
from typing import Any, Tuple

from dotenv import load_dotenv

# AI was used for reference to write this code.

# Add the parent directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# Load environment variables from .env
load_dotenv()


def check_api_version_compatibility(version: str) -> bool:
    """
    Check if the given Shopify API version string is valid and supported.
    Valid format: YYYY-MM, where year is 2020-2030 and month is 01, 04, 07, or 10.
    """
    import re

    if not isinstance(version, str):
        return False
    match = re.fullmatch(r"(20[2-3][0-9])-(0[1|4|7]|10)", version)
    if not match:
        return False
    year, month = match.group(1), match.group(2)
    # Shopify supports versions from 2020-01 to 2030-10 (future-proof)
    if not ("2020" <= year <= "2030"):
        return False
    if month not in {"01", "04", "07", "10"}:
        return False
    return True


def fetch_schema_from_shopify(
    url, retries=3, delay=2, token_header: str = "", token: str = ""
):
    attempts = 0
    while attempts < retries:
        try:
            cmd = ["get-graphql-schema", url, "--json"]
            if token_header and token:
                cmd.extend(["--header", f"{token_header}={token}"])

            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,  # capture the standard output
                stderr=subprocess.PIPE,  # capture the standard error
                text=True,  # decode the output as a string
                check=True,  # raise an exception if the command fails
            )
            # invalid token or expired session
            if "error" in result.stderr.lower() or "not found" in result.stderr.lower():
                raise RuntimeError(
                    f"Shopify schema fetch returned an error:\n{result.stderr}"
                )
            try:
                # JSON parsing error
                parsed = json.loads(result.stdout)
                # token lacks the correct scope
                if isinstance(parsed, dict) and "errors" in parsed and parsed["errors"]:
                    raise RuntimeError(
                        f"Shopify schema fetch returned an error:\n{parsed['errors']}"
                    )
            # if the response is not valid JSON, not in a curly brace format
            except json.JSONDecodeError:
                # If not JSON (unexpected), return as-is
                pass
            return result.stdout  # 🧠 Schema content in memory

        # the get-graphql-schema CLI tool is not installed or not found in your PATH.
        except FileNotFoundError:
            raise RuntimeError(
                "The 'get-graphql-schema' CLI tool is not installed or not found in your PATH. "
                "Please install it using: npm install get-graphql-schema"
            )

        # invalid url
        except subprocess.CalledProcessError as e:
            attempts += 1
            if attempts >= retries:
                raise RuntimeError(
                    f"Failed to fetch schema from {url} after {retries} attempts:\n{e.stderr}"
                ) from e
            time.sleep(delay)


def fetch_shopify_schemas_with_tokens(version: str) -> Tuple[str, str]:
    """Fetch Shopify schemas using access tokens from environment variables."""
    import os

    from dotenv import load_dotenv

    # Load environment variables
    load_dotenv()

    SHOPIFY_SHOP = os.getenv("SHOPIFY_SHOP")
    SHOPIFY_ADMIN_ACCESS_TOKEN = os.getenv("SHOPIFY_ADMIN_ACCESS_TOKEN")
    SHOPIFY_STOREFRONT_ACCESS_TOKEN = os.getenv("SHOPIFY_STOREFRONT_ACCESS_TOKEN")

    if (
        not SHOPIFY_SHOP
        or not SHOPIFY_ADMIN_ACCESS_TOKEN
        or not SHOPIFY_STOREFRONT_ACCESS_TOKEN
    ):
        raise RuntimeError(
            "❌ Missing required environment variables: SHOPIFY_SHOP, SHOPIFY_ADMIN_ACCESS_TOKEN, SHOPIFY_STOREFRONT_ACCESS_TOKEN"
        )

    admin_url = f"https://{SHOPIFY_SHOP}.myshopify.com/admin/api/{version}/graphql.json"
    storefront_url = f"https://{SHOPIFY_SHOP}.myshopify.com/api/{version}/graphql.json"

    admin_schema = fetch_schema_from_shopify(
        admin_url,
        token_header="X-Shopify-Access-Token",
        token=SHOPIFY_ADMIN_ACCESS_TOKEN,
    )
    storefront_schema = fetch_schema_from_shopify(
        storefront_url,
        token_header="X-Shopify-Storefront-Access-Token",
        token=SHOPIFY_STOREFRONT_ACCESS_TOKEN,
    )

    return admin_schema, storefront_schema


def fetch_shopify_schemas_with_proxy(version: str) -> Tuple[str, str]:
    """Fetch Shopify schemas using proxy URLs."""
    if not check_api_version_compatibility(version):
        raise ValueError(f"Invalid or unsupported Shopify API version: {version}")

    admin_url = f"https://shopify.dev/admin-graphql-direct-proxy/{version}"
    storefront_url = f"https://shopify.dev/storefront-graphql-direct-proxy/{version}"

    admin_schema = fetch_schema_from_shopify(admin_url)
    storefront_schema = fetch_schema_from_shopify(storefront_url)

    return admin_schema, storefront_schema


def load_schemas(version: str) -> Tuple[Any, Any]:
    """Load both admin and storefront schemas using tokens or proxy based on version."""
    from graphql import build_client_schema

    # Check version to determine method: < 2024-10 use tokens, >= 2024-10 use proxy
    year, month = version.split("-")
    version_date = int(year + month)

    if version_date < 202410:  # Before 2024-10
        # Use tokens for older versions
        admin_schema, storefront_schema = fetch_shopify_schemas_with_tokens(version)
    else:
        # Use proxy for newer versions (2024-10 and later)
        admin_schema, storefront_schema = fetch_shopify_schemas_with_proxy(version)

    admin_json = json.loads(admin_schema)
    storefront_json = json.loads(storefront_schema)

    admin_data = admin_json.get("data", admin_json)
    storefront_data = storefront_json.get("data", storefront_json)

    return build_client_schema(admin_data), build_client_schema(storefront_data)
