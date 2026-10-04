import json
from pathlib import Path

try:
    from mcp.server.mcpserver import MCPServer as Server
except ImportError:
    from mcp.server.fastmcp import FastMCP as Server

HERE = Path(__file__).resolve().parent
DESCRIPTIONS = json.loads((HERE / "descriptions.json").read_text(encoding="utf-8"))
FORECASTS = {"bengaluru": "24C, light rain", "mumbai": "31C, humid", "delhi": "35C, clear", "san francisco": "17C, fog"}

server = Server("weather")


@server.tool(description=DESCRIPTIONS["get_forecast"])
def get_forecast(city: str, days: int = 1) -> str:
    base = FORECASTS.get(city.strip().lower(), "no data")
    return json.dumps({"city": city, "days": days, "forecast": base})


@server.tool(description=DESCRIPTIONS["get_air_quality"])
def get_air_quality(city: str) -> str:
    return json.dumps({"city": city, "aqi": 88 if city.lower() == "delhi" else 42})


if __name__ == "__main__":
    server.run()
