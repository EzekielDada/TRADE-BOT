#!/usr/bin/env python3
"""Installation and dependency verification script."""

from __future__ import annotations

import sys
from pathlib import Path


def check_python_version() -> bool:
    """Verify Python version is 3.10 or higher."""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 10):
        print(f"❌ Python 3.10+ required, found {version.major}.{version.minor}")
        return False
    print(f"✓ Python version: {version.major}.{version.minor}.{version.micro}")
    return True


def check_dependencies() -> bool:
    """Check all required packages are installed."""
    dependencies = [
        ("ccxt", "Exchange API"),
        ("pandas", "Data processing"),
        ("pandas_ta", "Technical indicators"),
        ("groq", "Groq API client"),
        ("google.generativeai", "Gemini API client"),
        ("newsapi", "NewsAPI client"),
        ("pytrends", "Google Trends"),
        ("streamlit", "Dashboard"),
        ("plotly", "Charts"),
        ("backtrader", "Backtesting"),
        ("dotenv", "Environment variables"),
        ("aiohttp", "Async HTTP"),
        ("sqlalchemy", "Database ORM"),
        ("loguru", "Logging"),
        ("schedule", "Job scheduling"),
        ("rapidfuzz", "Fuzzy matching"),
    ]

    missing = []
    for package, description in dependencies:
        try:
            __import__(package)
            print(f"✓ {package:25} - {description}")
        except ImportError:
            print(f"❌ {package:25} - {description}")
            missing.append(package)

    if missing:
        print(f"\nMissing packages: {', '.join(missing)}")
        print("Run: pip install -r requirements.txt")
        return False
    return True


def check_env_file() -> bool:
    """Check if .env file exists and has required keys."""
    env_path = Path(".env")

    if not env_path.exists():
        print("❌ .env file not found")
        print("   Copy .env.example to .env and fill in API keys")
        return False

    print("✓ .env file exists")

    required_keys = [
        "GROQ_API_KEY",
        "GEMINI_API_KEY",
        "BYBIT_API_KEY",
        "BYBIT_SECRET",
    ]

    with open(env_path) as f:
        env_content = f.read()

    missing_keys = []
    for key in required_keys:
        if key not in env_content or f"{key}=" not in env_content:
            missing_keys.append(key)

    if missing_keys:
        print(f"❌ Missing keys in .env: {', '.join(missing_keys)}")
        return False

    print(f"✓ All required keys present in .env")
    return True


def check_directory_structure() -> bool:
    """Check all required directories exist."""
    required_dirs = [
        "ai",
        "data",
        "strategies",
        "execution",
        "backtesting",
        "dashboard",
        "tests",
    ]

    missing = []
    for dir_name in required_dirs:
        if not Path(dir_name).is_dir():
            missing.append(dir_name)
        else:
            print(f"✓ {dir_name}/ exists")

    if missing:
        print(f"❌ Missing directories: {', '.join(missing)}")
        return False
    return True


def check_database() -> bool:
    """Check database connection."""
    try:
        from config import Settings
        from storage import Storage

        settings = Settings.from_env()
        storage = Storage(settings.sqlite_path)
        print(f"✓ Database: {settings.sqlite_path}")
        return True
    except Exception as e:
        print(f"❌ Database error: {e}")
        return False


def check_api_connections() -> bool:
    """Test API connections (optional, requires valid keys)."""
    print("\nTesting API connections...")

    try:
        from config import Settings

        settings = Settings.from_env()

        # Test Groq
        if settings.groq_api_key:
            try:
                from groq import Groq

                client = Groq(api_key=settings.groq_api_key)
                client.models.list()
                print("✓ Groq API connection successful")
            except Exception as e:
                print(f"⚠ Groq API connection failed: {e}")

        # Test Gemini
        if settings.gemini_api_key:
            try:
                import google.generativeai as genai

                genai.configure(api_key=settings.gemini_api_key)
                genai.list_models()
                print("✓ Gemini API connection successful")
            except Exception as e:
                print(f"⚠ Gemini API connection failed: {e}")

        # Test Bybit
        if settings.bybit_api_key and settings.bybit_secret:
            try:
                import ccxt

                testnet_url = "https://api-testnet.bybit.com"
                live_url = "https://api.bybit.com"
                exchange = ccxt.bybit(
                    {
                        "apiKey": settings.bybit_api_key,
                        "secret": settings.bybit_secret,
                        "urls": {
                            "api": {
                                "public": testnet_url if settings.bybit_testnet else live_url,
                                "private": testnet_url if settings.bybit_testnet else live_url,
                            }
                        },
                    }
                )
                exchange.fetch_ticker("BTC/USDT")
                print("✓ Bybit API connection successful")
            except Exception as e:
                print(f"⚠ Bybit API connection failed: {e}")

    except Exception as e:
        print(f"⚠ Could not test APIs: {e}")

    return True


def main() -> int:
    """Run all checks."""
    print("=" * 60)
    print("🤖 Trading Bot Setup Verification")
    print("=" * 60)

    checks = [
        ("Python Version", check_python_version),
        ("Dependencies", check_dependencies),
        (".env Configuration", check_env_file),
        ("Directory Structure", check_directory_structure),
        ("Database", check_database),
        ("API Connections", check_api_connections),
    ]

    results = []
    for name, check_func in checks:
        print(f"\n▶ {name}:")
        try:
            results.append(check_func())
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            results.append(False)

    print("\n" + "=" * 60)
    if all(results):
        print("✅ All checks passed! Ready to run the bot.")
        print("\nNext steps:")
        print("1. Start the bot:       python main.py")
        print("2. Open dashboard:      streamlit run dashboard/app.py")
        print("3. Monitor logs:        tail -f logs/bot.log")
        return 0
    else:
        print("❌ Some checks failed. See details above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
